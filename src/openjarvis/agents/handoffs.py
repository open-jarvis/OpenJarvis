"""Run the receiving agent for each team handoff, safely and at most once.

The dispatcher lives inside the agent scheduler's lifecycle. For every due
handoff it re-checks policy, claims it atomically, runs one tick of the
recipient, then records the outcome. When a member finishes a task its result
returns to the team lead automatically as a report.

Safety rules:

* A paused agent is never resumed: its handoffs wait until the operator
  resumes it. Over-budget or failed agents block their handoffs visibly.
* Membership, communication permission and lead role are re-checked right
  before execution; a change after sending blocks the handoff.
* One claim per handoff; a run interrupted by a restart is requeued within its
  attempt budget. Every campaign has a run budget and depth/size limits.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from openjarvis.agents.campaigns import RETRY_DELAY_SECONDS, HandoffRejected

logger = logging.getLogger(__name__)

_BLOCKING_STATUS = {
    "budget_exceeded": (
        "تجاوز الوكيل حد الميزانية المحدد له؛ ارفع الحد أو أعد ضبطه ثم أعد المحاولة."
    ),
    "error": "الوكيل في حالة خطأ؛ راجع سجلّه ثم أعد المحاولة.",
    "needs_attention": "الوكيل يحتاج تدخّلك؛ راجع آخر تشغيل له ثم أعد المحاولة.",
    "stalled": "توقف الوكيل عن الاستجابة؛ راجع حالته ثم أعد المحاولة.",
}


class HandoffDispatcher:
    def __init__(
        self,
        manager: Any,
        executor: Any,
        *,
        poll_interval: float = 2.0,
    ) -> None:
        self._manager = manager
        self._executor = executor
        self._poll = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Lifecycle ───────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            recovered = self._manager.campaigns.recover_interrupted()
            if recovered:
                logger.info("Requeued %d interrupted handoff(s)", recovered)
        except Exception:
            logger.exception("Handoff recovery failed")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="handoff-dispatcher"
        )
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def wait_stopped(self, timeout: float = 10.0) -> bool:
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.dispatch_once()
            except Exception:
                logger.exception("Handoff dispatch error")
            self._stop.wait(self._poll)

    # ── One pass ────────────────────────────────────────────────

    def dispatch_once(self) -> int:
        """Run at most one due handoff. Returns runs."""
        for handoff in self._manager.campaigns.due_handoffs():
            if self._stop.is_set():
                return 0
            if self._run(handoff):
                return 1
        return 0

    def _block(self, handoff: Dict[str, Any], status: str, reason: str) -> None:
        store = self._manager.campaigns
        if handoff["status"] != status or handoff["status_reason"] != reason:
            store.update_handoff(handoff["id"], status=status, status_reason=reason)

    def _precheck(self, handoff: Dict[str, Any]) -> bool:
        """Re-check policy right before execution. True when it may run now."""
        m, store = self._manager, self._manager.campaigns
        campaign = store.get_campaign(handoff["campaign_id"])
        if campaign is None or campaign["status"] != "active":
            self._block(handoff, "cancelled", "الطلب لم يعد نشطًا.")
            return False
        target = m.get_agent(handoff["target_agent_id"])
        if target is None or target["status"] == "archived":
            self._block(handoff, "failed", "الوكيل المستلِم حُذف أو أُرشف.")
            return False
        if target["team_id"] != handoff["target_team_id"]:
            self._block(
                handoff,
                "blocked",
                "تغيّر فريق الوكيل المستلِم بعد التسليم؛ لم تُنفَّذ المهمة.",
            )
            return False
        source_id = handoff["source_agent_id"]
        if source_id:
            source = m.get_agent(source_id)
            if source is None or source["team_id"] != handoff["source_team_id"]:
                self._block(handoff, "blocked", "تغيّر فريق الوكيل المُرسِل بعد التسليم.")
                return False
            if not m.agents_can_communicate(source_id, target["id"]):
                self._block(
                    handoff, "blocked", "أُلغي إذن التواصل بين الفريقين قبل التنفيذ."
                )
                return False
            if handoff["kind"] == "task" and not store.is_current_lead(source_id):
                self._block(handoff, "blocked", "لم يعد مُرسِل المهمة منسّق الفريق.")
                return False
        if handoff["kind"] in {"request", "report"} and not store.is_current_lead(
            target["id"]
        ):
            self._block(handoff, "blocked", "تغيّر منسّق الفريق قبل التنفيذ.")
            return False
        if target["status"] == "paused":
            self._block(
                handoff,
                "waiting_paused",
                f"الوكيل «{target['name']}» موقوف بواسطتك؛ ستبدأ المهمة بعد "
                "استئنافك له.",
            )
            return False
        if target["status"] in _BLOCKING_STATUS:
            self._block(handoff, "blocked", _BLOCKING_STATUS[target["status"]])
            return False
        config = target.get("config") or {}
        max_cost = config.get("max_cost") or 0
        if max_cost and (target.get("total_cost") or 0) >= max_cost:
            self._block(handoff, "blocked", _BLOCKING_STATUS["budget_exceeded"])
            return False
        if campaign["runs_used"] >= campaign["max_runs"]:
            self._block(
                handoff,
                "blocked",
                f"وصل الطلب لحد التشغيل ({campaign['max_runs']} تشغيل). ارفع الحد "
                "أو راجع الطلب يدويًا.",
            )
            store.set_campaign_status(
                campaign["id"], "active", "وصل الطلب لحد التشغيل."
            )
            return False
        if handoff["status"] == "waiting_paused":
            store.update_handoff(
                handoff["id"], status="pending", status_reason="استؤنف الوكيل."
            )
        return target["status"] != "running"

    def _run(self, handoff: Dict[str, Any]) -> bool:
        m, store = self._manager, self._manager.campaigns
        if not self._precheck(handoff):
            return False
        agent_id = handoff["target_agent_id"]
        try:
            m.start_tick(agent_id)
        except ValueError:
            return False  # Busy with another run; try again next pass.
        batch: List[Dict[str, Any]] = []
        try:
            batch = store.claim_batch(handoff)
            if not batch:
                return False
            started = time.time()
            self._executor.execute_tick(agent_id, lock_already_held=True)
            self._finish(batch, started)
            return True
        except Exception:
            logger.exception("Handoff %s run failed", handoff["id"])
            for item in batch:
                store.update_handoff(
                    item["id"],
                    status="blocked",
                    status_reason="خطأ غير متوقع أثناء تشغيل الوكيل؛ أعد المحاولة.",
                )
            return bool(batch)
        finally:
            m.end_tick(agent_id)

    def _finish(self, batch: List[Dict[str, Any]], started: float) -> None:
        m, store = self._manager, self._manager.campaigns
        agent_id = batch[0]["target_agent_id"]
        agent = m.get_agent(agent_id) or {}
        reply = next(
            (
                msg
                for msg in m.list_messages(agent_id, limit=10)
                if msg["direction"] == "agent_to_user"
                and (msg.get("created_at") or 0) >= started
            ),
            None,
        )
        failed = reply is None or agent.get("status") in {"error", "needs_attention"}
        for item in batch:
            if not failed:
                store.update_handoff(
                    item["id"],
                    status="completed",
                    status_reason="",
                    result_message_id=reply["id"],
                )
                continue
            fresh = store.get_handoff(item["id"]) or item
            if agent.get("status") in _BLOCKING_STATUS:
                store.update_handoff(
                    item["id"],
                    status="blocked",
                    status_reason=f"فشل تشغيل «{agent.get('name', '')}»: "
                    + _BLOCKING_STATUS[agent["status"]],
                )
            elif fresh["attempts"] < fresh["max_attempts"]:
                store.update_handoff(
                    item["id"],
                    status="pending",
                    next_attempt_at=time.time() + RETRY_DELAY_SECONDS,
                    status_reason="لم يُرجع الوكيل نتيجة؛ ستُعاد المحاولة تلقائيًا "
                    "خلال دقيقة.",
                )
            else:
                store.update_handoff(
                    item["id"],
                    status="failed",
                    status_reason="لم يُرجع الوكيل نتيجة بعد المحاولات المسموح بها.",
                )
        if failed:
            return
        campaign = store.get_campaign(batch[0]["campaign_id"])
        for item in batch:
            if item["kind"] != "task" or campaign is None:
                continue
            root = store.campaign_dir(campaign["team_id"], campaign["id"])
            produced = [
                f["path"]
                for f in store.list_files(campaign)
                if f["modified_at"] >= started and (root / f["path"]).is_file()
            ][:20]
            calls = reply.get("tool_calls") or []
            facts = "، ".join(
                f"{c.get('tool')} ({'نجح' if c.get('success') else 'فشل'})"
                for c in calls
            )
            note = (
                "\n\n— ملاحظة من النظام (ليست من الوكيل): الأدوات المستدعاة فعلًا: "
                + (facts or "لا شيء")
                + ". الملفات الجديدة أو المعدّلة في هذا التشغيل: "
                + ("، ".join(produced) or "لا شيء")
                + "."
            )
            try:
                store.create_report(
                    item, content=reply["content"] + note, files=produced
                )
            except HandoffRejected as exc:
                store.update_handoff(
                    item["id"],
                    status_reason=f"اكتملت المهمة لكن تعذّر إبلاغ المنسّق: {exc}",
                )


__all__ = ["HandoffDispatcher"]
