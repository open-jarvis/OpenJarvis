"""Email triage benchmark dataset.

Synthetic email threads for evaluating urgency classification,
category assignment, and draft response generation.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are an AI email assistant. Analyze the following email and provide:
1. Urgency level: critical, high, medium, or low
2. Category: action, decision, info, or social
3. A brief draft reply (2-3 sentences)

Format your response exactly as:
urgency: <level>
category: <category>
draft: <your draft reply>

Email:
From: {sender}
Subject: {subject}
Date: {date}

{body}"""

# Synthetic email records covering a range of urgency/category combinations
_EMAILS = [
    {
        "sender": "cto@company.com",
        "subject": "URGENT: Production database is down",
        "date": "2025-12-01 03:14",
        "body": "Our primary Postgres cluster is unreachable. Customers are seeing 500 errors. I need the on-call team assembled immediately. Please acknowledge and start the incident runbook.",
        "urgency": "critical",
        "category": "action",
    },
    {
        "sender": "alice@partner.org",
        "subject": "Contract renewal deadline tomorrow",
        "date": "2025-12-01 09:00",
        "body": "Hi, just a reminder that our service contract expires tomorrow at midnight. We need your signed renewal by EOD or we'll need to pause service. The updated terms are attached. Please review and sign at your earliest convenience.",
        "urgency": "critical",
        "category": "decision",
    },
    {
        "sender": "security@company.com",
        "subject": "Security patch required: CVE-2025-4321",
        "date": "2025-12-01 10:30",
        "body": "A critical vulnerability has been disclosed in our authentication library. All production services must be patched within 24 hours. The fix is available in version 3.2.1. Please coordinate with your team to schedule the update.",
        "urgency": "critical",
        "category": "action",
    },
    {
        "sender": "boss@company.com",
        "subject": "Q4 budget approval needed",
        "date": "2025-12-02 08:00",
        "body": "I need your approval on the Q4 infrastructure budget by Friday. The proposal includes $45K for GPU servers and $12K for monitoring tools. Let me know if you have concerns or want to discuss before I submit to finance.",
        "urgency": "high",
        "category": "decision",
    },
    {
        "sender": "hr@company.com",
        "subject": "New hire starting Monday — setup needed",
        "date": "2025-12-02 11:00",
        "body": "Sarah Chen is joining the ML team on Monday. Please ensure her dev environment, Slack access, and GitHub permissions are set up before she arrives. She'll need access to the model-training and inference repos.",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "client@bigcorp.com",
        "subject": "API integration failing in staging",
        "date": "2025-12-02 14:00",
        "body": "We're getting 401 errors when calling your /v2/inference endpoint from our staging environment. Our API key was rotated last week. Could you check if the new key is properly allowlisted? We need this resolved before our Thursday demo.",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "pm@company.com",
        "subject": "Feature spec review: voice commands",
        "date": "2025-12-02 15:30",
        "body": "I've drafted the PRD for voice command support. It covers wake word detection, streaming transcription, and intent parsing. Can you review the technical feasibility section and leave comments by next Wednesday?",
        "urgency": "high",
        "category": "decision",
    },
    {
        "sender": "devops@company.com",
        "subject": "Kubernetes cluster upgrade scheduled",
        "date": "2025-12-03 09:00",
        "body": "We'll be upgrading the production k8s cluster from 1.28 to 1.30 this Saturday at 2am UTC. Expected downtime is 15 minutes. Please ensure your services are compatible with the new version. No action needed if you're using the standard Helm charts.",
        "urgency": "medium",
        "category": "info",
    },
    {
        "sender": "data-team@company.com",
        "subject": "Weekly model performance report",
        "date": "2025-12-03 10:00",
        "body": "Here's this week's performance summary:\n- Inference latency: P50=42ms, P99=180ms (stable)\n- Accuracy on validation set: 94.2% (up 0.3%)\n- Daily active users: 12,400 (up 8%)\n- Error rate: 0.02% (down from 0.05%)\nAll metrics within SLA. No action needed.",
        "urgency": "low",
        "category": "info",
    },
    {
        "sender": "intern@company.com",
        "subject": "Question about coding style",
        "date": "2025-12-03 11:00",
        "body": "Hi! I'm working on the data pipeline refactor. Should I use dataclasses or Pydantic models for the new config objects? I saw both patterns in the codebase and want to stay consistent. Thanks!",
        "urgency": "low",
        "category": "decision",
    },
    {
        "sender": "marketing@company.com",
        "subject": "Blog post draft for review",
        "date": "2025-12-03 13:00",
        "body": "I've written a blog post about our new on-device inference feature. Could you review the technical accuracy of the benchmarks section? No rush — we're planning to publish next week. Draft is in the shared Google Doc.",
        "urgency": "medium",
        "category": "action",
    },
    {
        "sender": "colleague@company.com",
        "subject": "Lunch tomorrow?",
        "date": "2025-12-03 16:00",
        "body": "Hey, want to grab lunch tomorrow? There's a new ramen place that opened on 5th street. I heard it's really good. Let me know if you're free around noon.",
        "urgency": "low",
        "category": "social",
    },
    {
        "sender": "legal@company.com",
        "subject": "Updated data processing agreement",
        "date": "2025-12-04 09:00",
        "body": "Please review the updated DPA for our EU customers. The main changes are around data retention periods and right-to-erasure timelines. We need engineering sign-off by end of next week to stay compliant with the new regulations.",
        "urgency": "medium",
        "category": "decision",
    },
    {
        "sender": "support@vendor.io",
        "subject": "Your support ticket #8842 has been resolved",
        "date": "2025-12-04 10:00",
        "body": "Hi, we've resolved the memory leak issue you reported in v4.1.2. The fix is included in v4.1.3 which was released today. Please upgrade at your convenience and let us know if the issue persists.",
        "urgency": "medium",
        "category": "action",
    },
    {
        "sender": "recruiter@external.com",
        "subject": "Exciting ML opportunity",
        "date": "2025-12-04 11:00",
        "body": "I came across your profile and think you'd be a great fit for our Senior ML Engineer role. We're building cutting-edge on-device AI systems. Would you be open to a brief chat next week?",
        "urgency": "low",
        "category": "social",
    },
    {
        "sender": "cfo@company.com",
        "subject": "Cost optimization meeting — Thursday 2pm",
        "date": "2025-12-04 14:00",
        "body": "I'm setting up a meeting to discuss cloud cost optimization. Our GPU compute spend increased 40% last quarter. Please come prepared with data on your team's usage and any ideas for reducing costs without impacting performance.",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "ops@company.com",
        "subject": "SSL certificate expiring in 7 days",
        "date": "2025-12-05 08:00",
        "body": "The SSL certificate for api.openjarvis.dev expires on December 12. Auto-renewal is configured but failed last time due to DNS validation issues. Please verify the CNAME record is correct and trigger a manual renewal if needed.",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "team@company.com",
        "subject": "Retrospective notes from sprint 47",
        "date": "2025-12-05 09:00",
        "body": "Here are the key takeaways from yesterday's retro:\n- What went well: shipped voice feature on time, test coverage improved to 92%\n- What to improve: PR review turnaround is still slow (avg 2 days)\n- Action items: implement PR review SLA, set up automated test reports\nFull notes in Confluence.",
        "urgency": "low",
        "category": "info",
    },
    {
        "sender": "partner@aicloud.io",
        "subject": "Partnership proposal — joint webinar",
        "date": "2025-12-05 10:00",
        "body": "We'd love to co-host a webinar on local vs cloud AI inference with your team. We think a balanced comparison would be valuable for both our audiences. Proposed date: January 15. Would you be interested?",
        "urgency": "medium",
        "category": "decision",
    },
    {
        "sender": "monitoring@company.com",
        "subject": "Alert: Memory usage at 85% on prod-gpu-03",
        "date": "2025-12-05 22:00",
        "body": "Memory usage on prod-gpu-03 has been above 85% for the past 30 minutes. Current usage: 85.2%. Threshold: 90%. The inference service is still healthy but may degrade if usage increases. Consider restarting the service or scaling out.",
        "urgency": "medium",
        "category": "action",
    },
    {
        "sender": "design@company.com",
        "subject": "New dashboard mockups ready",
        "date": "2025-12-06 09:00",
        "body": "The updated mockups for the savings dashboard are ready in Figma. Key changes: added monthly projection cards, cloud agent comparison section, and a cost calculator widget. Please take a look when you have a chance.",
        "urgency": "low",
        "category": "info",
    },
    {
        "sender": "board@company.com",
        "subject": "Board meeting prep — AI strategy deck",
        "date": "2025-12-06 10:00",
        "body": "The board meeting is next Thursday. I need 3-4 slides on our AI cost savings strategy — specifically how on-device inference reduces our operational costs. Can you prepare the slides with actual numbers by Tuesday?",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "opensource@contributor.dev",
        "subject": "PR submitted: improved memory backend",
        "date": "2025-12-06 11:00",
        "body": "Hi, I've submitted PR #234 with a hybrid memory backend that uses RRF fusion for better retrieval. Tests are passing. Would appreciate a review when you get a chance. Happy to make any changes.",
        "urgency": "medium",
        "category": "action",
    },
    {
        "sender": "training@company.com",
        "subject": "Mandatory security training due Dec 15",
        "date": "2025-12-06 13:00",
        "body": "This is a reminder that all engineering staff must complete the annual security awareness training by December 15. The course takes approximately 30 minutes. Access it through the Learning Portal. Please complete it at your earliest convenience.",
        "urgency": "medium",
        "category": "action",
    },
    {
        "sender": "friend@personal.com",
        "subject": "Happy holidays!",
        "date": "2025-12-06 17:00",
        "body": "Hey! Just wanted to wish you happy holidays. Hope you're doing well. Let's catch up over coffee sometime in January. Miss our chats!",
        "urgency": "low",
        "category": "social",
    },
    {
        "sender": "ceo@company.com",
        "subject": "Company all-hands: cost savings milestone",
        "date": "2025-12-07 08:00",
        "body": "Great news — we've saved over $500K this year by running AI inference locally. I want to highlight this at the all-hands on Friday. Can someone from the infra team prepare a 5-minute demo of the savings dashboard?",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "vendor@cloudprovider.com",
        "subject": "Your monthly invoice is ready",
        "date": "2025-12-07 09:00",
        "body": "Your December invoice for cloud compute services is now available. Total: $3,247.88. This represents a 60% reduction from your peak monthly spend in June ($8,120.00). View details in your account dashboard.",
        "urgency": "low",
        "category": "info",
    },
    {
        "sender": "qa@company.com",
        "subject": "Regression found in v2.8.1",
        "date": "2025-12-07 10:00",
        "body": "We found a regression in the latest release: the memory search endpoint returns empty results when the query contains special characters (e.g., '@', '#'). This affects the email triage workflow. Bisected to commit abc123. Please fix before the next release.",
        "urgency": "high",
        "category": "action",
    },
    {
        "sender": "newsletter@techdigest.com",
        "subject": "This week in AI: local inference trends",
        "date": "2025-12-07 12:00",
        "body": "Top stories this week:\n1. On-device AI adoption up 200% year-over-year\n2. New quantization techniques enable 70B models on consumer GPUs\n3. Cloud AI costs continue to rise, driving interest in local alternatives\n4. Open-source AI frameworks see record contributions",
        "urgency": "low",
        "category": "info",
    },
    {
        "sender": "compliance@company.com",
        "subject": "GDPR audit scheduled for January",
        "date": "2025-12-07 14:00",
        "body": "Our annual GDPR compliance audit is scheduled for January 20-22. The auditors will review our data processing pipelines, consent mechanisms, and retention policies. Please ensure your team's documentation is up to date. I'll send a detailed checklist next week.",
        "urgency": "medium",
        "category": "info",
    },
]


class EmailTriageDataset(DatasetProvider):
    """Email triage benchmark: urgency classification + category + draft reply."""

    dataset_id = "email_triage"
    dataset_name = "Email Triage"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = list(_EMAILS)

        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, email in enumerate(rows):
            prompt = _PROMPT_TEMPLATE.format(
                sender=email["sender"],
                subject=email["subject"],
                date=email["date"],
                body=email["body"],
            )
            reference = f"urgency: {email['urgency']}\ncategory: {email['category']}"
            self._records.append(
                EvalRecord(
                    record_id=f"email-triage-{idx}",
                    problem=prompt,
                    reference=reference,
                    category="use-case",
                    subject="email_triage",
                    metadata={
                        "urgency": email["urgency"],
                        "category": email["category"],
                        "sender": email["sender"],
                        "subject_line": email["subject"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["EmailTriageDataset"]
