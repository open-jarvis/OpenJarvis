"""Conservative independence grouping for candidate evidence."""

from __future__ import annotations

from openjarvis.learning.candidates.models import (
    EvaluationEnvelope,
    ExplicitFeedbackRecord,
    IndependenceAnchorKind,
    IndependenceGroup,
)
from openjarvis.learning.candidates.signatures import stable_digest


def group_for_evaluation(envelope: EvaluationEnvelope) -> IndependenceGroup:
    """Create one auditable group using the same rules as batch extraction."""

    return groups_for_evaluations((envelope,))[envelope.evaluation.evaluation_id]


def group_for_feedback(record: ExplicitFeedbackRecord) -> IndependenceGroup:
    anchor_digest = stable_digest(f"feedback:{record.feedback_group_id}")
    return IndependenceGroup(
        group_digest=stable_digest(
            {
                "anchor_kind": IndependenceAnchorKind.USER_FEEDBACK.value,
                "anchor_digest": anchor_digest,
            }
        ),
        anchor_kind=IndependenceAnchorKind.USER_FEEDBACK,
        anchor_digest=anchor_digest,
        source_evaluation_ids=(
            (record.source_evaluation_id,) if record.source_evaluation_id else ()
        ),
        source_task_ids=((record.task_id,) if record.task_id else ()),
        source_trace_ids=((record.trace_id,) if record.trace_id else ()),
        source_feedback_ids=(record.feedback_id,),
    )


def groups_for_evaluations(
    envelopes: tuple[EvaluationEnvelope, ...],
) -> dict[str, IndependenceGroup]:
    """Group related evaluations using task, input, thread, retry, and replay links."""

    ordered = tuple(sorted(envelopes, key=lambda item: item.evaluation.evaluation_id))
    parents = {
        item.evaluation.evaluation_id: item.evaluation.evaluation_id for item in ordered
    }

    def find(item_id: str) -> str:
        while parents[item_id] != item_id:
            parents[item_id] = parents[parents[item_id]]
            item_id = parents[item_id]
        return item_id

    def union(left_id: str, right_id: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        parents[second] = first

    task_index: dict[str, str] = {}
    trace_index: dict[str, str] = {}
    input_index: dict[str, str] = {}
    thread_index: dict[str, str] = {}
    for envelope in ordered:
        evaluation = envelope.evaluation
        evaluation_id = evaluation.evaluation_id
        for index, key in (
            (task_index, evaluation.task_id),
            (trace_index, evaluation.trace_id),
            (input_index, evaluation.input_digest),
        ):
            existing = index.setdefault(key, evaluation_id)
            union(existing, evaluation_id)
        if envelope.lineage.thread_id:
            existing = thread_index.setdefault(
                envelope.lineage.thread_id, evaluation_id
            )
            union(existing, evaluation_id)

    for envelope in ordered:
        evaluation_id = envelope.evaluation.evaluation_id
        lineage = envelope.lineage
        for task_id in (
            lineage.root_task_id,
            lineage.retry_of_task_id,
            lineage.parent_task_id,
        ):
            if task_id and task_id in task_index:
                union(evaluation_id, task_index[task_id])
        if lineage.replay_of_trace_id in trace_index:
            union(evaluation_id, trace_index[lineage.replay_of_trace_id])

    members: dict[str, list[EvaluationEnvelope]] = {}
    for envelope in ordered:
        members.setdefault(find(envelope.evaluation.evaluation_id), []).append(envelope)

    result: dict[str, IndependenceGroup] = {}
    for related in members.values():
        evaluations = tuple(item.evaluation for item in related)
        lineages = tuple(item.lineage for item in related)
        if any(lineage.replay_of_trace_id for lineage in lineages):
            kind = IndependenceAnchorKind.TRACE_REPLAY
        elif any(
            lineage.root_task_id or lineage.retry_of_task_id or lineage.parent_task_id
            for lineage in lineages
        ):
            kind = IndependenceAnchorKind.TASK_LINEAGE
        elif any(lineage.thread_id for lineage in lineages):
            kind = IndependenceAnchorKind.THREAD_LINEAGE
        else:
            kind = IndependenceAnchorKind.INPUT_DIGEST
        anchor_payload = {
            "sessions": sorted({item.session_id for item in evaluations}),
            "tasks": sorted({item.task_id for item in evaluations}),
            "traces": sorted({item.trace_id for item in evaluations}),
            "inputs": sorted({item.input_digest for item in evaluations}),
            "roots": sorted(
                {
                    value
                    for lineage in lineages
                    for value in (
                        lineage.root_task_id,
                        lineage.retry_of_task_id,
                        lineage.parent_task_id,
                        lineage.thread_id,
                        lineage.replay_of_trace_id,
                    )
                    if value
                }
            ),
        }
        anchor_digest = stable_digest(anchor_payload)
        group = IndependenceGroup(
            group_digest=stable_digest(
                {"anchor_kind": kind.value, "anchor_digest": anchor_digest}
            ),
            anchor_kind=kind,
            anchor_digest=anchor_digest,
            source_evaluation_ids=tuple(item.evaluation_id for item in evaluations),
            source_task_ids=tuple(item.task_id for item in evaluations),
            source_trace_ids=tuple(item.trace_id for item in evaluations),
        )
        for evaluation in evaluations:
            result[evaluation.evaluation_id] = group
    return result


def merge_groups(
    groups: tuple[IndependenceGroup, ...],
) -> tuple[IndependenceGroup, ...]:
    """Merge source references while retaining one count per stable anchor."""

    merged: dict[str, IndependenceGroup] = {}
    for group in groups:
        current = merged.get(group.group_digest)
        if current is None:
            merged[group.group_digest] = group
            continue
        merged[group.group_digest] = IndependenceGroup(
            group_digest=group.group_digest,
            anchor_kind=group.anchor_kind,
            anchor_digest=group.anchor_digest,
            source_evaluation_ids=(
                current.source_evaluation_ids + group.source_evaluation_ids
            ),
            source_task_ids=current.source_task_ids + group.source_task_ids,
            source_trace_ids=current.source_trace_ids + group.source_trace_ids,
            source_feedback_ids=(
                current.source_feedback_ids + group.source_feedback_ids
            ),
        )
    return tuple(merged[key] for key in sorted(merged))


__all__ = [
    "group_for_evaluation",
    "group_for_feedback",
    "groups_for_evaluations",
    "merge_groups",
]
