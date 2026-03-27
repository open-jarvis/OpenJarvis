"""daily_digest dataset — 30 realistic workday briefing tasks.

Each task provides a morning context (calendar, todos, messages, news interests)
and the agent must produce a prioritized daily digest.

Difficulty tiers:
- easy (10): simple day with 2-3 meetings, few messages, clear priorities
- medium (10): busy day with conflicting priorities, cross-team dependencies
- hard (10): crisis scenarios mixing urgent incidents with normal workload
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """You are a personal assistant preparing a daily briefing for {role} at {company}.

## Today's Date
{date}

## Calendar
{calendar}

## Todo List
{todos}

## Unread Messages
{messages}

## News Interests
{news_interests}

Produce a concise, prioritized daily digest that:
1. Highlights the most urgent items first
2. Groups related items together
3. Includes specific action items
4. Notes any scheduling conflicts or deadlines"""

# ---------------------------------------------------------------------------
# EASY tasks (10): simple workday
# ---------------------------------------------------------------------------

_EASY_TASKS: List[Dict[str, Any]] = [
    {
        "role": "Backend Engineer",
        "company": "Acme Corp",
        "date": "2025-09-15 (Monday)",
        "calendar": "09:00 - Sprint planning (1h)\n14:00 - 1:1 with manager (30m)",
        "todos": "- Review PR #342 for auth service\n- Update API docs for v2 endpoints",
        "messages": "- Slack from @alice: 'PR #342 is ready for review, no rush'\n- Email from manager: '1:1 agenda: Q4 goals discussion'",
        "news_interests": "Python, Kubernetes",
        "must_mention": ["sprint planning", "PR #342", "1:1", "Q4 goals"],
        "priority_order": ["sprint planning", "PR #342", "1:1"],
    },
    {
        "role": "Frontend Developer",
        "company": "StartupXYZ",
        "date": "2025-09-16 (Tuesday)",
        "calendar": "10:00 - Design review (1h)\n15:00 - Team standup (15m)",
        "todos": "- Fix CSS regression in checkout flow\n- Add unit tests for form validation",
        "messages": "- Slack from @bob: 'Checkout flow bug reported by 3 customers today'",
        "news_interests": "React, TypeScript",
        "must_mention": ["checkout flow bug", "design review", "form validation"],
        "priority_order": ["checkout flow bug", "design review"],
    },
    {
        "role": "Data Scientist",
        "company": "DataCo",
        "date": "2025-09-17 (Wednesday)",
        "calendar": "11:00 - ML model review (1h)\n16:00 - Weekly team sync (30m)",
        "todos": "- Retrain churn prediction model with Q3 data\n- Prepare slides for Friday demo",
        "messages": "- Email from product: 'Can you share churn model accuracy numbers for board deck?'",
        "news_interests": "LLMs, MLOps",
        "must_mention": ["churn model", "board deck numbers", "Friday demo"],
        "priority_order": ["board deck numbers", "churn model"],
    },
    {
        "role": "DevOps Engineer",
        "company": "CloudScale",
        "date": "2025-09-18 (Thursday)",
        "calendar": "09:30 - Infrastructure review (1h)\n13:00 - Lunch with new hire",
        "todos": "- Upgrade Kubernetes cluster to 1.28\n- Set up monitoring for new microservice",
        "messages": "- PagerDuty: 'Resolved — disk usage alert on prod-db-03 cleared at 06:42'",
        "news_interests": "Kubernetes, Terraform",
        "must_mention": ["K8s upgrade", "monitoring", "disk alert resolved"],
        "priority_order": ["K8s upgrade", "infrastructure review"],
    },
    {
        "role": "Product Manager",
        "company": "FinTech Inc",
        "date": "2025-09-19 (Friday)",
        "calendar": "09:00 - Sprint retro (1h)\n11:00 - Stakeholder demo (1h)\n15:00 - Happy hour",
        "todos": "- Finalize Q4 roadmap draft\n- Send release notes for v3.2",
        "messages": "- Slack from @eng-lead: 'v3.2 deployed to staging, all green'\n- Email from VP: 'Need roadmap by EOD Monday'",
        "news_interests": "Fintech regulations, payment APIs",
        "must_mention": [
            "stakeholder demo",
            "v3.2 staging",
            "Q4 roadmap",
            "EOD Monday deadline",
        ],
        "priority_order": ["stakeholder demo", "v3.2 staging", "Q4 roadmap"],
    },
    {
        "role": "Security Engineer",
        "company": "SecureNet",
        "date": "2025-09-22 (Monday)",
        "calendar": "10:00 - Vulnerability triage (1h)\n14:00 - SOC 2 prep meeting (1h)",
        "todos": "- Review Dependabot alerts for critical repos\n- Update incident response runbook",
        "messages": "- Email from compliance: 'SOC 2 auditor visit confirmed for Oct 3'\n- Slack from @sre: 'New CVE in OpenSSL, checking exposure'",
        "news_interests": "CVEs, zero-day exploits",
        "must_mention": ["OpenSSL CVE", "SOC 2 audit Oct 3", "Dependabot alerts"],
        "priority_order": ["OpenSSL CVE", "SOC 2 audit"],
    },
    {
        "role": "Mobile Developer",
        "company": "AppWorks",
        "date": "2025-09-23 (Tuesday)",
        "calendar": "09:30 - iOS release planning (1h)\n14:00 - Code review session (1h)",
        "todos": "- Fix crash in offline mode (Sentry issue #891)\n- Implement push notification deep links",
        "messages": "- Slack from QA: 'Sentry #891 affecting 2% of users on iOS 17'\n- App Store Connect: 'v4.1 approved for release'",
        "news_interests": "Swift, iOS",
        "must_mention": [
            "Sentry #891 crash",
            "v4.1 approved",
            "push notification deep links",
        ],
        "priority_order": ["Sentry #891 crash", "v4.1 approved"],
    },
    {
        "role": "Engineering Manager",
        "company": "MegaCorp",
        "date": "2025-09-24 (Wednesday)",
        "calendar": "09:00 - Leadership sync (1h)\n11:00 - 1:1 with Alice (30m)\n11:30 - 1:1 with Bob (30m)\n14:00 - Hiring debrief (1h)",
        "todos": "- Write performance review for Charlie\n- Approve Q4 headcount request",
        "messages": "- HR: 'Performance reviews due by Sept 30'\n- Recruiter: 'Strong senior candidate, debrief at 2pm'",
        "news_interests": "Engineering management, team scaling",
        "must_mention": ["performance reviews due Sept 30", "hiring debrief", "1:1s"],
        "priority_order": ["performance reviews", "hiring debrief"],
    },
    {
        "role": "QA Lead",
        "company": "TestFirst",
        "date": "2025-09-25 (Thursday)",
        "calendar": "10:00 - Release readiness review (1h)\n15:00 - Automation framework demo (30m)",
        "todos": "- Run regression suite for v5.0\n- Update test plan for payment module",
        "messages": "- Jira: 'RELEASE-50: v5.0 release candidate tagged'\n- Slack from dev: 'Payment module refactored, old tests may break'",
        "news_interests": "Test automation, Playwright",
        "must_mention": [
            "v5.0 regression suite",
            "payment module tests",
            "release readiness",
        ],
        "priority_order": ["v5.0 regression suite", "payment module tests"],
    },
    {
        "role": "SRE",
        "company": "UpTime Co",
        "date": "2025-09-26 (Friday)",
        "calendar": "09:00 - Incident review (1h)\n13:00 - Capacity planning (1h)",
        "todos": "- Write post-mortem for Wednesday's outage\n- Update runbook for database failover",
        "messages": "- Datadog: 'API p99 latency back to normal (12ms)'\n- Manager: 'Post-mortem draft needed before Monday'",
        "news_interests": "SRE practices, observability",
        "must_mention": [
            "post-mortem draft",
            "API latency normal",
            "capacity planning",
        ],
        "priority_order": ["post-mortem draft", "capacity planning"],
    },
]

# ---------------------------------------------------------------------------
# MEDIUM tasks (10): busy day with cross-team dependencies
# ---------------------------------------------------------------------------

_MEDIUM_TASKS: List[Dict[str, Any]] = [
    {
        "role": "Staff Engineer",
        "company": "Stripe",
        "date": "2025-10-06 (Monday)",
        "calendar": "09:00 - Architecture review (1.5h)\n11:00 - Cross-team sync with Payments (1h)\n14:00 - RFC review: event streaming (1h)\n16:00 - Mentoring session (30m)",
        "todos": "- Finalize RFC for webhook retry redesign\n- Review perf regression in checkout API\n- Respond to security review findings",
        "messages": "- Slack from @payments-lead: 'Webhook failures up 3x since Friday deploy'\n- Email from VP Eng: 'RFC deadline extended to Wednesday'\n- Jira INFRA-2847: 'Checkout API p99 jumped from 200ms to 800ms'",
        "news_interests": "distributed systems, payment processing",
        "must_mention": [
            "webhook failures 3x",
            "INFRA-2847 checkout latency",
            "RFC deadline Wednesday",
            "architecture review",
            "security review findings",
        ],
        "priority_order": [
            "webhook failures 3x",
            "INFRA-2847 checkout latency",
            "RFC deadline",
        ],
    },
    {
        "role": "ML Engineer",
        "company": "Recommendation AI",
        "date": "2025-10-07 (Tuesday)",
        "calendar": "09:30 - Model deployment standup (15m)\n11:00 - A/B test review (1h)\n14:00 - Data pipeline retrospective (1h)\n16:00 - Paper reading group (1h)",
        "todos": "- Investigate 5% CTR drop in product recommendations\n- Prepare training data for v3 model\n- Review feature store PR from junior engineer",
        "messages": "- Slack from product: 'Recommendation CTR dropped on mobile — exec visibility'\n- Airflow alert: 'DAG user_features failed at 03:00, 2 retries exhausted'\n- Email from research: 'New embedding approach shows 12% improvement in offline eval'",
        "news_interests": "recommendation systems, transformer architectures",
        "must_mention": [
            "CTR drop",
            "Airflow DAG failure",
            "v3 model training data",
            "A/B test review",
            "new embedding approach",
        ],
        "priority_order": ["CTR drop", "Airflow DAG failure", "A/B test review"],
    },
    {
        "role": "Platform Engineer",
        "company": "CloudNative Co",
        "date": "2025-10-08 (Wednesday)",
        "calendar": "09:00 - Platform team standup (15m)\n10:00 - Migration planning: monolith to microservices (2h)\n14:00 - Vendor eval: Datadog vs New Relic (1h)\n16:30 - On-call handoff (15m)",
        "todos": "- Complete service mesh POC documentation\n- Fix flaky integration tests in CI pipeline\n- Review IAM policy changes for staging env",
        "messages": "- Slack from SRE: 'CI pipeline blocked — flaky test_payment_flow failing 40% of runs'\n- Email from CTO: 'Need vendor recommendation by Friday for budget approval'\n- GitHub: '3 new Dependabot PRs — 1 critical (lodash prototype pollution)'",
        "news_interests": "service mesh, platform engineering",
        "must_mention": [
            "CI flaky test",
            "vendor recommendation Friday",
            "lodash critical CVE",
            "migration planning",
            "IAM policy review",
        ],
        "priority_order": [
            "CI flaky test",
            "lodash critical CVE",
            "vendor recommendation",
        ],
    },
    {
        "role": "Tech Lead",
        "company": "HealthTech",
        "date": "2025-10-09 (Thursday)",
        "calendar": "08:30 - HIPAA compliance review (1h)\n10:00 - Sprint planning (1.5h)\n13:00 - 1:1 with PM (30m)\n14:00 - API design review for patient portal (1h)",
        "todos": "- Audit PHI access logs for September\n- Design API for lab results integration\n- Mentor new hire on HIPAA data handling",
        "messages": "- Compliance team: 'September PHI audit due Oct 15 — need your section by Oct 10'\n- PM: 'Patient portal launch moved up to Nov 1'\n- QA: 'Found PHI leak in staging logs — ticket SEC-445'",
        "news_interests": "healthcare APIs, HIPAA compliance",
        "must_mention": [
            "PHI leak SEC-445",
            "audit due Oct 10",
            "patient portal Nov 1",
            "lab results API",
            "HIPAA compliance review",
        ],
        "priority_order": [
            "PHI leak SEC-445",
            "audit due Oct 10",
            "patient portal Nov 1",
        ],
    },
    {
        "role": "Backend Lead",
        "company": "E-Commerce Plus",
        "date": "2025-10-10 (Friday)",
        "calendar": "09:00 - Production deploy review (30m)\n10:00 - Black Friday capacity planning (2h)\n14:00 - Team retrospective (1h)\n16:00 - Drinks with team",
        "todos": "- Sign off on deploy for order management refactor\n- Review load test results (target: 10x normal traffic)\n- Update on-call rotation for holiday season",
        "messages": "- Load test results: 'System handles 7x but OOM at 8x on order-service'\n- Slack from payments: 'New Stripe API version — migration needed by Dec 1'\n- PagerDuty: 'Memory leak alert on cart-service, auto-scaled to 8 pods'",
        "news_interests": "e-commerce scaling, distributed systems",
        "must_mention": [
            "OOM at 8x load",
            "cart-service memory leak",
            "Stripe migration Dec 1",
            "Black Friday capacity",
            "deploy review",
        ],
        "priority_order": [
            "OOM at 8x load",
            "cart-service memory leak",
            "Black Friday capacity",
        ],
    },
    {
        "role": "Data Engineer",
        "company": "Analytics Corp",
        "date": "2025-10-13 (Monday)",
        "calendar": "09:00 - Data platform standup (15m)\n10:30 - Data quality review (1h)\n14:00 - Cross-team: marketing attribution model (1h)",
        "todos": "- Debug Spark job OOM on customer_360 pipeline\n- Implement CDC for new orders table\n- Review dbt model changes from analytics team",
        "messages": "- Airflow: 'customer_360 DAG failed — Spark executor OOM'\n- Marketing: 'Attribution numbers look off by 15% since last week'\n- Slack from manager: 'Quarterly data infrastructure review next Tuesday, prep needed'",
        "news_interests": "data engineering, Apache Spark",
        "must_mention": [
            "Spark OOM customer_360",
            "attribution 15% discrepancy",
            "CDC orders table",
            "infrastructure review prep",
        ],
        "priority_order": [
            "Spark OOM",
            "attribution discrepancy",
            "infrastructure review",
        ],
    },
    {
        "role": "iOS Lead",
        "company": "Social App Inc",
        "date": "2025-10-14 (Tuesday)",
        "calendar": "09:00 - iOS team standup (15m)\n10:00 - App Store review meeting (1h)\n13:00 - 1:1 with junior dev (30m)\n15:00 - SwiftUI migration planning (1h)",
        "todos": "- Fix crash in background refresh (Sentry #1204)\n- Prepare submission for iOS 18 compatibility update\n- Review accessibility audit findings",
        "messages": "- App Store Connect: 'v6.2.1 rejected — missing privacy manifest for tracking'\n- Sentry: '#1204 crash rate increased to 0.8% (was 0.2%)'\n- Apple developer news: 'Privacy manifest deadline extended to Oct 31'",
        "news_interests": "iOS development, SwiftUI",
        "must_mention": [
            "v6.2.1 rejected",
            "privacy manifest deadline Oct 31",
            "Sentry #1204 crash",
            "accessibility audit",
            "SwiftUI migration",
        ],
        "priority_order": [
            "v6.2.1 rejected",
            "Sentry #1204 crash",
            "privacy manifest deadline",
        ],
    },
    {
        "role": "VP of Engineering",
        "company": "GrowthStartup",
        "date": "2025-10-15 (Wednesday)",
        "calendar": "08:00 - Board prep with CEO (1h)\n09:30 - Engineering all-hands (1h)\n11:00 - Candidate interview: Director of Platform (1h)\n14:00 - 1:1s with tech leads (2h)\n16:30 - Investor update draft review",
        "todos": "- Finalize engineering section of board deck\n- Approve Q1 hiring plan (8 headcount)\n- Review SOC 2 Type II readiness",
        "messages": "- CEO: 'Board meeting moved to Oct 20, deck due Oct 17'\n- HR: 'Director candidate strong — competing offer from FAANG, need to move fast'\n- CTO: 'SOC 2 auditor found 2 medium findings, remediation needed'",
        "news_interests": "engineering leadership, scaling teams",
        "must_mention": [
            "board deck due Oct 17",
            "director candidate competing offer",
            "SOC 2 findings",
            "Q1 hiring plan",
            "engineering all-hands",
        ],
        "priority_order": ["director candidate", "board deck Oct 17", "SOC 2 findings"],
    },
    {
        "role": "Full-Stack Developer",
        "company": "EdTech Platform",
        "date": "2025-10-16 (Thursday)",
        "calendar": "09:00 - Sprint standup (15m)\n10:00 - Feature demo: video player (30m)\n13:00 - Design sync for new quiz module (1h)\n15:00 - Tech debt review (1h)",
        "todos": "- Fix video player buffering on slow connections\n- Implement quiz auto-save feature\n- Update staging with latest migrations",
        "messages": "- Support: '15 teachers reported video playback issues today'\n- PM: 'Quiz module launch is hard deadline — Nov 15'\n- Slack from DevOps: 'Staging DB needs migration, currently 3 behind'",
        "news_interests": "video streaming, education technology",
        "must_mention": [
            "video playback issues",
            "quiz module Nov 15",
            "staging migrations behind",
            "feature demo",
            "tech debt review",
        ],
        "priority_order": [
            "video playback issues",
            "quiz module Nov 15",
            "staging migrations",
        ],
    },
    {
        "role": "Infrastructure Engineer",
        "company": "FinServ Co",
        "date": "2025-10-17 (Friday)",
        "calendar": "09:00 - Change advisory board (1h)\n11:00 - DR test planning (1h)\n14:00 - Compliance tool eval (1h)",
        "todos": "- Prepare DR test runbook for Q4 drill\n- Migrate legacy monitoring to Grafana\n- Review firewall rule change requests",
        "messages": "- AWS: 'Scheduled maintenance us-east-1: Oct 25, 02:00-06:00 UTC'\n- Compliance: 'Annual DR test must complete before Dec 31'\n- Slack from SRE: 'Grafana migration 60% complete, need help with alert rules'",
        "news_interests": "cloud infrastructure, disaster recovery",
        "must_mention": [
            "AWS maintenance Oct 25",
            "DR test before Dec 31",
            "Grafana migration 60%",
            "firewall rule review",
            "change advisory board",
        ],
        "priority_order": [
            "AWS maintenance Oct 25",
            "DR test planning",
            "Grafana migration",
        ],
    },
]

# ---------------------------------------------------------------------------
# HARD tasks (10): crisis scenarios with urgent incidents
# ---------------------------------------------------------------------------

_HARD_TASKS: List[Dict[str, Any]] = [
    {
        "role": "Senior SRE",
        "company": "PayStream",
        "date": "2025-11-03 (Monday)",
        "calendar": "09:00 - Post-mortem: Friday payment outage (1.5h)\n11:00 - SRE team standup (15m)\n13:00 - 1:1 with VP Eng (30m)\n14:00 - Capacity review (1h)\n16:00 - On-call handoff (15m)",
        "todos": "- Complete post-mortem document for payment outage (5h downtime, $2.3M impact)\n- Implement circuit breaker for payment gateway\n- Review and merge hotfix for connection pool exhaustion\n- Update incident response playbook with lessons learned",
        "messages": "- PagerDuty: 'CRITICAL — Payment success rate dropped to 45% at 02:14, recovered at 07:30'\n- CEO: 'Need customer communication plan by noon'\n- VP Eng: 'Board wants root cause by Wednesday'\n- Slack from payments team: 'Connection pool fix in PR #891, needs urgent review'\n- Datadog: '3 new anomaly alerts on order-service since 08:00'\n- Customer success: '47 enterprise customers opened tickets about Friday outage'",
        "news_interests": "SRE, payment systems, incident management",
        "must_mention": [
            "payment outage $2.3M",
            "PR #891 connection pool",
            "customer communication noon",
            "board root cause Wednesday",
            "new anomaly alerts",
            "47 enterprise tickets",
            "post-mortem",
        ],
        "priority_order": [
            "customer communication noon",
            "PR #891 connection pool",
            "anomaly alerts",
            "board root cause Wednesday",
        ],
    },
    {
        "role": "CISO",
        "company": "DataVault",
        "date": "2025-11-04 (Tuesday)",
        "calendar": "08:00 - Incident war room (ongoing)\n10:00 - Board security briefing (1h)\n13:00 - Legal consultation (1h)\n15:00 - Vendor security review (1h)\n17:00 - Press response prep",
        "todos": "- Coordinate response to detected data exfiltration attempt\n- Prepare board briefing on security incident\n- Review forensic analysis from IR team\n- Determine notification obligations under GDPR/CCPA",
        "messages": "- SOC: 'Detected unusual data transfer — 2.3GB to external IP from staging-db-02 at 01:47'\n- IR team: 'Attack vector identified: compromised service account via phished credentials'\n- Legal: 'If PII confirmed, 72h GDPR notification clock starts now'\n- CEO: 'No external communication until legal approves messaging'\n- AWS GuardDuty: 'UnauthorizedAccess:IAMUser/MaliciousIPCaller on staging account'\n- HR: 'Phished employee identified, account disabled'",
        "news_interests": "cybersecurity, data breach response, compliance",
        "must_mention": [
            "2.3GB exfiltration",
            "phished credentials",
            "GDPR 72h notification",
            "board briefing",
            "legal messaging approval",
            "GuardDuty alert",
            "compromised service account",
        ],
        "priority_order": [
            "exfiltration incident",
            "GDPR notification",
            "board briefing",
            "legal approval",
        ],
    },
    {
        "role": "Engineering Director",
        "company": "ScaleUp",
        "date": "2025-11-05 (Wednesday)",
        "calendar": "08:30 - Executive standup (30m)\n09:30 - Emergency: API partner integration broken (1h)\n11:00 - Quarterly planning (2h)\n14:00 - Hiring pipeline review (1h)\n16:00 - 1:1 with struggling team lead (30m)",
        "todos": "- Resolve broken Salesforce integration (blocking $4M deal)\n- Prepare Q1 roadmap proposal for exec review\n- Address team morale issues in Platform team (3 resignations in 2 months)\n- Review compensation adjustments for retention",
        "messages": "- Salesforce partner: 'API breaking change in v58 — our integration returns 400s since midnight'\n- Sales VP: '$4M Acme deal closes Friday, integration must work by Thursday EOD'\n- HR: 'Exit interview themes: lack of growth, below-market comp'\n- CTO: 'Q1 roadmap proposal due Friday, include AI strategy'\n- Slack from platform-lead: 'Two more engineers gave notice yesterday'\n- GitHub: 'Salesforce integration fix in draft PR, needs API key rotation'",
        "news_interests": "engineering management, API integrations",
        "must_mention": [
            "Salesforce API breaking change",
            "$4M deal Thursday deadline",
            "platform team resignations",
            "Q1 roadmap Friday",
            "compensation adjustments",
            "API key rotation",
        ],
        "priority_order": [
            "Salesforce integration",
            "$4M deal deadline",
            "platform team resignations",
            "Q1 roadmap",
        ],
    },
    {
        "role": "Lead SRE",
        "company": "StreamMedia",
        "date": "2025-11-06 (Thursday)",
        "calendar": "07:00 - War room: global CDN outage (ongoing)\n10:00 - Customer escalation call (1h)\n13:00 - Infrastructure post-mortem planning\n15:00 - Vendor call with CDN provider",
        "todos": "- Coordinate failover to backup CDN\n- Estimate customer impact (MAU affected, SLA credits)\n- Prepare status page communications\n- Document timeline for incident report",
        "messages": "- CDN provider: 'Global edge outage affecting EU and APAC, ETA 4h for full recovery'\n- Monitoring: 'Video start failures at 78% (normal: 2%), 3.2M users affected'\n- Customer success: 'ESPN, Netflix, Disney+ all escalating — SLA breach imminent'\n- CEO: 'Status page must update every 30 minutes'\n- Finance: 'Estimated SLA credits: $850K if not resolved by noon'\n- Engineering: 'Backup CDN can handle 60% of traffic, degraded quality'",
        "news_interests": "CDN, video streaming, incident management",
        "must_mention": [
            "CDN outage EU APAC",
            "3.2M users affected",
            "SLA credits $850K",
            "backup CDN 60%",
            "status page updates 30min",
            "ETA 4h recovery",
            "ESPN Netflix Disney escalation",
        ],
        "priority_order": [
            "CDN failover",
            "status page updates",
            "customer escalations",
            "SLA credit estimate",
        ],
    },
    {
        "role": "CTO",
        "company": "AI Startup",
        "date": "2025-11-07 (Friday)",
        "calendar": "08:00 - Emergency board call (1h)\n09:30 - Engineering all-hands (1h)\n11:00 - 1:1 with co-founder/CEO (1h)\n13:00 - Investor meeting (2h)\n16:00 - Technical architecture review",
        "todos": "- Address GPU cost overrun ($180K over budget this quarter)\n- Prepare technical due diligence materials for Series B\n- Evaluate build vs buy for vector database\n- Respond to acquisition interest from BigTech",
        "messages": "- CFO: 'GPU costs 40% over budget — need cost reduction plan by Monday'\n- Lead investor: 'Series B term sheet ready, need tech DD materials by next Friday'\n- BigTech BD: 'Acquisition conversation request — CEO says explore quietly'\n- AWS: 'Reserved instance commitment expires Nov 30'\n- ML team: 'New model achieves SOTA on benchmark but requires 2x GPU'\n- VP Eng: 'Team burnout is real — 60h average weeks for past month'",
        "news_interests": "AI infrastructure, venture capital, GPU optimization",
        "must_mention": [
            "GPU cost overrun $180K",
            "Series B DD materials",
            "acquisition interest",
            "RI expiration Nov 30",
            "SOTA model 2x GPU",
            "team burnout 60h weeks",
        ],
        "priority_order": [
            "GPU cost reduction Monday",
            "Series B DD",
            "acquisition exploration",
            "team burnout",
        ],
    },
    {
        "role": "Principal Engineer",
        "company": "TradeTech",
        "date": "2025-11-10 (Monday)",
        "calendar": "08:00 - Market open monitoring (1h)\n09:30 - Architecture council (1.5h)\n11:30 - Regulatory compliance review (1h)\n14:00 - Performance optimization sprint kickoff (1h)\n16:00 - Mentoring: system design (1h)",
        "todos": "- Investigate 50ms latency spike in order matching engine\n- Review SEC Rule 15c3-5 compliance for new algorithm\n- Design circuit breaker for third-party market data feeds\n- Prepare tech brief on microsecond timestamping upgrade",
        "messages": "- Trading desk: 'Order matching 50ms slower since Friday deploy — losing $40K/day in slippage'\n- Compliance: 'SEC audit next month, need algorithm documentation by Nov 20'\n- Vendor: 'Market data feed v3 deprecating Dec 15, migration required'\n- CTO: 'Board approved microsecond upgrade budget, need timeline'\n- Monitoring: 'Memory leak detected in risk engine — growing 50MB/hour'\n- DevOps: 'Friday deploy rollback available but needs 2h maintenance window'",
        "news_interests": "low-latency systems, financial technology",
        "must_mention": [
            "order matching latency $40K/day",
            "SEC audit Nov 20",
            "market data feed migration Dec 15",
            "memory leak risk engine",
            "deploy rollback option",
            "microsecond upgrade timeline",
        ],
        "priority_order": [
            "order matching latency",
            "memory leak risk engine",
            "SEC audit documentation",
            "market data migration",
        ],
    },
    {
        "role": "VP Platform",
        "company": "SaaS Giant",
        "date": "2025-11-11 (Tuesday)",
        "calendar": "08:00 - Incident review (ongoing DDoS mitigation)\n09:30 - Executive war room (1h)\n11:00 - Customer escalation: Fortune 500 (1h)\n13:00 - Security vendor eval (1h)\n15:00 - Board risk committee prep",
        "todos": "- Coordinate DDoS mitigation (attack started 22:00 last night)\n- Prepare customer impact assessment\n- Evaluate WAF vendor proposals (Cloudflare vs Akamai)\n- Draft risk committee presentation",
        "messages": "- NOC: 'DDoS attack ongoing — 340Gbps, Cloudflare mitigating 95% but 5% getting through'\n- Fortune 500 client: 'Our SLA guarantees 99.99%, currently at 99.2% for November'\n- Legal: 'Three customers sent breach of contract notices'\n- Cloudflare TAM: 'Can upgrade to Enterprise+ with 1Tbps mitigation, $50K/month'\n- CFO: 'Board wants cyber insurance claim assessment'\n- CISO: 'Attack signature matches known botnet, FBI notified'",
        "news_interests": "DDoS mitigation, cloud security, SaaS operations",
        "must_mention": [
            "DDoS 340Gbps",
            "Fortune 500 SLA breach",
            "breach of contract notices",
            "Cloudflare upgrade $50K",
            "FBI notified",
            "cyber insurance claim",
            "risk committee prep",
        ],
        "priority_order": [
            "DDoS mitigation",
            "Fortune 500 SLA",
            "breach of contract",
            "cyber insurance",
        ],
    },
    {
        "role": "Head of ML",
        "company": "AutoDrive",
        "date": "2025-11-12 (Wednesday)",
        "calendar": "08:00 - Safety incident review (2h)\n10:30 - NHTSA call (1h)\n12:00 - Engineering all-hands (1h)\n14:00 - Model validation review (2h)\n16:30 - Press prep with comms",
        "todos": "- Investigate false negative in pedestrian detection model\n- Prepare safety data package for NHTSA\n- Review validation results for model v4.2\n- Coordinate OTA update for affected vehicles",
        "messages": "- Safety team: 'Vehicle #4892 near-miss incident — pedestrian not detected at dusk'\n- NHTSA: 'Requesting incident data within 48 hours per Standing General Order'\n- ML validation: 'v4.2 shows 0.3% regression in low-light pedestrian detection'\n- Legal: 'Do not communicate externally until safety review complete'\n- Fleet ops: '12,000 vehicles on v4.1, OTA update requires 72h rollout'\n- PR: 'Reuters reporter asking about safety incident reports'",
        "news_interests": "autonomous vehicles, ML safety, computer vision",
        "must_mention": [
            "pedestrian detection near-miss",
            "NHTSA 48h data request",
            "v4.2 low-light regression",
            "12000 vehicles OTA",
            "Reuters inquiry",
            "legal communication hold",
        ],
        "priority_order": [
            "NHTSA data request",
            "pedestrian detection investigation",
            "OTA update planning",
            "legal hold",
        ],
    },
    {
        "role": "VP Engineering",
        "company": "CloudBank",
        "date": "2025-11-13 (Thursday)",
        "calendar": "07:30 - Regulatory call: OCC examination (1h)\n09:00 - Incident bridge: core banking freeze (ongoing)\n11:00 - Customer impact triage (1h)\n14:00 - Vendor escalation: Oracle (1h)\n16:00 - Executive update to CEO/Board",
        "todos": "- Resolve core banking system freeze (customer transactions blocked)\n- Prepare OCC examination response materials\n- Coordinate Oracle emergency support (database deadlock)\n- Assess customer impact and communication plan",
        "messages": "- NOC: 'Core banking frozen at 06:15 — Oracle RAC deadlock, 450K transactions queued'\n- OCC examiner: 'Examination starts Monday, technology resilience focus area'\n- Customer ops: '2,300 customers called about failed transactions'\n- Oracle support: 'Severity 1 case opened, engineer assigned ETA 2h'\n- CFO: 'Regulatory fine risk if transactions not processed by EOD'\n- CISO: 'No security incident indicated, pure technology failure'",
        "news_interests": "banking technology, database systems, regulatory compliance",
        "must_mention": [
            "core banking freeze",
            "450K queued transactions",
            "OCC examination Monday",
            "Oracle RAC deadlock",
            "2300 customer calls",
            "regulatory fine risk EOD",
            "Oracle engineer ETA 2h",
        ],
        "priority_order": [
            "Oracle deadlock resolution",
            "regulatory fine risk",
            "customer communication",
            "OCC examination prep",
        ],
    },
    {
        "role": "Director of Engineering",
        "company": "HealthAI",
        "date": "2025-11-14 (Friday)",
        "calendar": "08:00 - FDA pre-submission meeting prep (2h)\n10:30 - Clinical validation review (1.5h)\n13:00 - Engineering sprint review (1h)\n14:30 - 1:1 with ML research lead (30m)\n15:30 - Compliance training (1h)",
        "todos": "- Finalize FDA 510(k) pre-submission package\n- Review clinical trial results for diagnostic AI accuracy\n- Address model drift detected in production deployment\n- Prepare for Monday's IRB ethics review",
        "messages": "- FDA liaison: 'Pre-submission meeting confirmed Nov 21, final materials due Nov 18'\n- Clinical team: 'Trial results: 94.2% sensitivity, 91.8% specificity — below 95% target for sensitivity'\n- ML ops: 'Model drift alert — AUC dropped from 0.96 to 0.89 over 30 days'\n- Legal: 'IRB flagged consent form language, revision needed before Monday'\n- Research lead: 'Promising approach to improve sensitivity — needs 2 weeks'\n- Quality: 'CAPA-2847 open: production model version mismatch between regions'",
        "news_interests": "medical AI, FDA regulation, clinical trials",
        "must_mention": [
            "FDA materials due Nov 18",
            "sensitivity below target 94.2%",
            "model drift AUC 0.89",
            "IRB consent revision Monday",
            "CAPA-2847 version mismatch",
            "2-week sensitivity improvement",
        ],
        "priority_order": [
            "model drift",
            "IRB consent revision",
            "FDA materials",
            "sensitivity improvement decision",
        ],
    },
]


class DailyDigestDataset(DatasetProvider):
    """30 realistic workday briefing tasks."""

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: str = "test",
        seed: Optional[int] = None,
    ) -> None:
        all_tasks = _EASY_TASKS + _MEDIUM_TASKS + _HARD_TASKS
        difficulties = (
            ["easy"] * len(_EASY_TASKS)
            + ["medium"] * len(_MEDIUM_TASKS)
            + ["hard"] * len(_HARD_TASKS)
        )

        paired = list(zip(all_tasks, difficulties))
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(paired)

        if max_samples is not None:
            paired = paired[:max_samples]

        self._records: List[EvalRecord] = []
        for idx, (task, diff) in enumerate(paired):
            prompt = _PROMPT_TEMPLATE.format(
                role=task["role"],
                company=task["company"],
                date=task["date"],
                calendar=task["calendar"],
                todos=task["todos"],
                messages=task["messages"],
                news_interests=task["news_interests"],
            )

            self._records.append(
                EvalRecord(
                    record_id=f"daily-digest-{idx:03d}",
                    problem=prompt,
                    reference="; ".join(task["must_mention"]),
                    category="agentic",
                    subject=diff,
                    metadata={
                        "role": task["role"],
                        "company": task["company"],
                        "must_mention": task["must_mention"],
                        "priority_order": task["priority_order"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["DailyDigestDataset"]
