"""Morning brief benchmark dataset.

Synthetic user-context records for evaluating daily briefing generation:
calendar events, todo items, news topics, and pending messages.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a personal AI assistant preparing a morning briefing. Based on the following context, generate a concise, prioritized morning brief.

The brief should:
1. Highlight the most important/urgent items first
2. Summarize calendar events for today
3. List top priorities from the todo list
4. Include relevant news highlights
5. Note any pending messages that need attention

Format your response as a structured briefing with clear sections.

--- User Context ---
Date: {date}

Calendar:
{calendar}

Todo List:
{todos}

News Topics of Interest:
{news_topics}

Pending Messages:
{messages}"""

_CONTEXTS = [
    {
        "date": "Monday, December 1, 2025",
        "calendar": "- 9:00 AM: Team standup (15 min)\n- 10:30 AM: 1:1 with Sarah (engineering lead)\n- 2:00 PM: Product review meeting\n- 4:00 PM: Candidate interview — senior ML engineer",
        "todos": "- Review PR #234 (memory backend optimization)\n- Submit Q4 budget proposal (due today)\n- Update deployment runbook\n- Prepare interview questions for 4pm candidate",
        "news_topics": "AI, machine learning, local inference, open source",
        "messages": "- Slack from CTO: 'Can we discuss cloud cost reduction at standup?'\n- Email from legal: contract renewal deadline is Wednesday\n- GitHub notification: CI failing on main branch",
        "key_priorities": "Q4 budget due today, CI failure on main, CTO wants cost discussion",
    },
    {
        "date": "Tuesday, December 2, 2025",
        "calendar": "- 8:30 AM: All-hands meeting (company update)\n- 11:00 AM: Architecture review — new caching layer\n- 1:00 PM: Lunch with visiting researcher\n- 3:30 PM: Sprint planning",
        "todos": "- Fix regression in search endpoint (high priority)\n- Write design doc for voice command feature\n- Review 3 pending PRs\n- Order new GPU server (approved in budget)",
        "news_topics": "semiconductor industry, GPU availability, NVIDIA earnings",
        "messages": "- Email from vendor: GPU server shipping delayed 2 weeks\n- Slack from QA: 'Found another edge case in triage workflow'\n- PR comment: need to address review feedback on #230",
        "key_priorities": "Search regression fix, GPU delay impacts timeline, QA edge case",
    },
    {
        "date": "Wednesday, December 3, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Security review (quarterly)\n- 2:00 PM: Demo to potential partner\n- 5:00 PM: Yoga class",
        "todos": "- Complete security training (due Dec 15)\n- Prepare demo slides for partner meeting\n- Merge approved PRs\n- Update CLAUDE.md with Phase 25 changes",
        "news_topics": "cybersecurity, data privacy, GDPR compliance",
        "messages": "- Email from partner: 'Looking forward to the demo, can you show the savings dashboard?'\n- Slack from intern: question about coding conventions\n- Calendar reminder: contract renewal deadline is today",
        "key_priorities": "Contract renewal deadline today, partner demo at 2pm, security review",
    },
    {
        "date": "Thursday, December 4, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 11:00 AM: Deep work block (no meetings)\n- 2:00 PM: Cost optimization meeting with CFO\n- 4:30 PM: Mentoring session with junior developer",
        "todos": "- Prepare cost analysis slides for CFO meeting\n- Implement rate limiting for API endpoints\n- Code review: agent loop guard improvements\n- Write blog post draft on local inference benefits",
        "news_topics": "cloud computing costs, serverless trends, edge AI",
        "messages": "- Email from CFO: 'Please bring specific numbers on GPU vs cloud costs'\n- Slack from devops: 'k8s upgrade went smoothly, all services healthy'\n- GitHub: 2 new issues filed by community users",
        "key_priorities": "CFO meeting needs cost data, rate limiting implementation, community issues",
    },
    {
        "date": "Friday, December 5, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Retrospective\n- 12:00 PM: Team lunch\n- 3:00 PM: Release planning for v3.0",
        "todos": "- Tag v2.9.1 release\n- Update changelog\n- Clear inbox (20+ unread)\n- Submit expense report\n- Plan next week's priorities",
        "news_topics": "open source funding, AI regulation, developer tools",
        "messages": "- Email from CEO: 'Great work on the cost savings! Can we present at all-hands?'\n- Slack from PM: 'v3.0 feature list needs final sign-off'\n- PR merged: speech backend improvements",
        "key_priorities": "Release v2.9.1, CEO presentation request, v3.0 planning",
    },
    {
        "date": "Monday, December 8, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Board meeting prep\n- 1:00 PM: Interview panel — engineering manager\n- 3:00 PM: Tech debt review",
        "todos": "- Prepare 3-4 slides on AI cost savings for board\n- Review candidate resume\n- Fix flaky test in CI (test_memory_search)\n- Update oncall rotation for holidays",
        "news_topics": "AI startups, venture capital, talent market",
        "messages": "- Email from board member: 'Send me the cost savings data before Thursday'\n- Slack from team: 'Who's covering oncall over the holidays?'\n- GitHub: security advisory for dependency",
        "key_priorities": "Board slides due, security advisory, holiday oncall coverage",
    },
    {
        "date": "Tuesday, December 9, 2025",
        "calendar": "- 8:00 AM: Breakfast meeting with advisor\n- 10:00 AM: Pair programming session\n- 2:00 PM: Customer feedback review\n- 4:00 PM: Design review — mobile app",
        "todos": "- Finish board presentation slides\n- Review customer feedback summary\n- Benchmark new quantization approach\n- Update documentation for new API endpoints",
        "news_topics": "mobile AI, quantization techniques, model compression",
        "messages": "- Email from customer: 'Love the product, but need better docs for the SDK'\n- Slack from design: 'Mobile mockups ready for review'\n- PR: community contribution for AMD GPU support",
        "key_priorities": "Board slides must be finished, customer docs feedback, mobile review",
    },
    {
        "date": "Wednesday, December 10, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 11:00 AM: Cross-team sync (ML + Platform)\n- 1:30 PM: Vendor call — monitoring tools\n- 3:00 PM: Office hours (open door)",
        "todos": "- Deploy rate limiter to staging\n- Test SSL certificate auto-renewal\n- Write incident postmortem from last week\n- Prepare for GDPR audit (January)",
        "news_topics": "observability, monitoring, SRE practices",
        "messages": "- Email from ops: 'SSL cert renewed successfully'\n- Slack from ML team: 'New model achieves 96% accuracy on benchmark'\n- Calendar reminder: GDPR audit docs due in 2 weeks",
        "key_priorities": "Rate limiter deployment, incident postmortem overdue, GDPR prep",
    },
    {
        "date": "Thursday, December 11, 2025",
        "calendar": "- 9:00 AM: Board meeting (all day)\n- 12:00 PM: Working lunch during board meeting\n- 5:00 PM: Team happy hour",
        "todos": "- Present AI cost savings slides at board meeting\n- Answer board questions on AI strategy\n- Send follow-up notes after board meeting\n- Approve holiday PTO requests",
        "news_topics": "corporate AI strategy, ROI of AI investments",
        "messages": "- Email from CEO: 'Board is excited about the cost savings numbers'\n- Slack from team: '3 PTO requests pending your approval'\n- Email from recruiter: candidate accepted the offer!",
        "key_priorities": "Board presentation today, PTO approvals needed, new hire accepted",
    },
    {
        "date": "Friday, December 12, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Post-board debrief with CEO\n- 11:30 AM: Release review\n- 2:00 PM: End of year planning",
        "todos": "- Send board meeting follow-up notes\n- Plan Q1 OKRs\n- Review and approve Q4 bonuses\n- Archive completed project boards\n- Buy holiday gifts for team",
        "news_topics": "year-end reviews, tech trends 2026, planning",
        "messages": "- Email from CEO: 'Board approved the 2026 AI budget, well done!'\n- Slack from HR: 'Q4 bonus recommendations due Monday'\n- Team Slack: 'Can we do Secret Santa?'",
        "key_priorities": "Board follow-up notes, Q1 OKR planning, bonus recommendations due Monday",
    },
    {
        "date": "Monday, December 15, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Q1 planning kickoff\n- 2:00 PM: Onboarding new hire — Sarah Chen\n- 4:00 PM: Security training deadline",
        "todos": "- Complete security training (deadline today!)\n- Prepare onboarding materials for Sarah\n- Submit Q4 bonus recommendations\n- Draft Q1 OKR proposals\n- Review year-end performance self-assessments",
        "news_topics": "hiring trends, employee onboarding best practices",
        "messages": "- Email from HR: 'Security training deadline is today'\n- Slack from Sarah: 'Excited to start! Any prep I should do?'\n- Email from finance: 'Bonus recommendations received, thank you'",
        "key_priorities": "Security training deadline TODAY, new hire onboarding, Q1 OKR drafts",
    },
    {
        "date": "Tuesday, December 16, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:00 AM: Sarah's first day — team intro\n- 1:00 PM: Architecture deep dive with Sarah\n- 3:00 PM: Vendor evaluation — new CI tool",
        "todos": "- Verify Sarah's access to all repos and tools\n- Review CI vendor proposals\n- Update team wiki with 2025 retrospective\n- Close out stale GitHub issues",
        "news_topics": "CI/CD trends, developer experience, DevOps",
        "messages": "- Slack from Sarah: 'All access is working, thank you!'\n- Email from CI vendor: 'Demo scheduled for 3pm today'\n- GitHub: 5 issues marked as stale, need triage",
        "key_priorities": "Sarah's onboarding going well, CI vendor evaluation, stale issue triage",
    },
    {
        "date": "Wednesday, December 17, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 10:30 AM: Performance review calibration\n- 2:00 PM: External talk prep — local AI meetup\n- 4:00 PM: 1:1 with Sarah (first week check-in)",
        "todos": "- Prepare performance review comments\n- Polish meetup talk slides\n- Review Sarah's first PR\n- Plan team holiday event",
        "news_topics": "AI community events, developer conferences, tech talks",
        "messages": "- Email from meetup organizer: 'Your talk is confirmed for Jan 8'\n- Slack from Sarah: 'Submitted my first PR!'\n- Email from HR: 'Performance reviews due Dec 22'",
        "key_priorities": "Performance reviews due in 5 days, Sarah's first PR, meetup talk prep",
    },
    {
        "date": "Thursday, December 18, 2025",
        "calendar": "- 9:00 AM: Team standup\n- 11:00 AM: Holiday party planning committee\n- 2:00 PM: Final architecture review for v3.0\n- 4:30 PM: Holiday card signing",
        "todos": "- Write performance reviews (3 direct reports)\n- Finalize v3.0 architecture decisions\n- Order catering for holiday party\n- Backup critical data before holiday freeze",
        "news_topics": "work-life balance, remote work, team culture",
        "messages": "- Slack from team: 'Can we do a white elephant gift exchange?'\n- Email from IT: 'Code freeze starts Dec 23'\n- GitHub: v3.0 milestone at 85% completion",
        "key_priorities": "Performance reviews writing, v3.0 architecture decisions, code freeze approaching",
    },
    {
        "date": "Friday, December 19, 2025",
        "calendar": "- 9:00 AM: Team standup (last of the year)\n- 10:00 AM: Year-end retrospective\n- 12:00 PM: Holiday lunch\n- 2:00 PM: Wrap-up and handoffs",
        "todos": "- Submit performance reviews (due Mon)\n- Document handoff for holiday oncall\n- Send team thank-you notes\n- Set out-of-office auto-reply\n- Final check on monitoring alerts",
        "news_topics": "year in review, tech predictions 2026",
        "messages": "- Email from CEO: 'Thank you for an amazing year!'\n- Slack from oncall volunteer: 'I have the runbook, all set'\n- Team Slack: 'Happy holidays everyone!'",
        "key_priorities": "Performance reviews due Monday, holiday handoffs, monitoring verification",
    },
]


class MorningBriefDataset(DatasetProvider):
    """Morning brief benchmark: generate prioritized daily briefing from context."""

    dataset_id = "morning_brief"
    dataset_name = "Morning Brief"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = list(_CONTEXTS)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, ctx in enumerate(rows):
            prompt = _PROMPT_TEMPLATE.format(
                date=ctx["date"],
                calendar=ctx["calendar"],
                todos=ctx["todos"],
                news_topics=ctx["news_topics"],
                messages=ctx["messages"],
            )
            self._records.append(
                EvalRecord(
                    record_id=f"morning-brief-{idx}",
                    problem=prompt,
                    reference=ctx["key_priorities"],
                    category="use-case",
                    subject="morning_brief",
                    metadata={"date": ctx["date"]},
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["MorningBriefDataset"]
