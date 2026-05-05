# Serena Remaining Legacy Skills Merge Scan

Purpose:

- Decide which remaining legacy skills should merge before continuing Membership Layer 1.

- Total legacy files scanned: 87
- Converted or already merged according to registry: 17
- Remaining or unconfirmed: 70

## Recommended merge strategy

### membership_programmes_subscriptions

- Likely operator: `serena_membership`
- Recommendation: Merge into Membership / Subscriptions / Patient Programmes. Do not build Payflow standalone unless it has a true external gateway workflow not covered by Accounting.
- Files detected: 13
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `45-payflow.js` ? DONE/MERGED ? triggers: PAYFLOW:, SUBSCRIPTION:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `62-memory.js` ? REMAINING ? triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `76-knowledge-business.js` ? REMAINING ? triggers: COURSE PLAN:, KNOWLEDGE BUSINESS:, MEMBERSHIP MODEL:, NEWSLETTER BUSINESS:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### ecommerce_woocommerce_store

- Likely operator: `serena_ecommerce`
- Recommendation: Build as Ecommerce / WooCommerce Store Operator, but reuse Accounting for payments/revenue and Membership for subscription/member outcomes.
- Files detected: 34
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `04-calendar.js` ? DONE/MERGED ? triggers: BOOK SLOT:, CANCEL APPOINTMENT:, CHECK AVAILABILITY:, TODAY SCHEDULE
  - `06-notebook.js` ? REMAINING ? triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:
  - `10-payfast.js` ? DONE/MERGED ? triggers: PAYMENT LINK:, PAYMENT STATUS:
  - `11-whatsapp.js` ? REMAINING ? triggers: N/A, POST, WHATSAPP:
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `20-booking.js` ? REMAINING ? triggers: BOOK APPOINTMENT:, CANCEL BOOKING:, MY BOOKINGS, NEW BOOKING:
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `27-gemini.js` ? REMAINING ? triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `32-video-generator.js` ? REMAINING ? triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `45-payflow.js` ? DONE/MERGED ? triggers: PAYFLOW:, SUBSCRIPTION:
  - `49-security.js` ? REMAINING ? triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `53-affiliate.js` ? REMAINING ? triggers: AFFILIATE PRODUCTS, PRODUCT LINKS:
  - `54-video-edit.js` ? REMAINING ? triggers: AUTO CAPTION:, EDIT VIDEO:
  - `58-ApptReminders.js` ? REMAINING ? triggers: REMINDER STATUS, SEND REMINDERS, TEST REMINDER:
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `71-digital-products.js` ? REMAINING ? triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
  - `72-affiliate-engine.js` ? REMAINING ? triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `76-knowledge-business.js` ? REMAINING ? triggers: COURSE PLAN:, KNOWLEDGE BUSINESS:, MEMBERSHIP MODEL:, NEWSLETTER BUSINESS:
  - `77-ecommerce-operations.js` ? REMAINING ? triggers: ECOMMERCE OPS:, PRODUCT OPS:, SHOP STRATEGY:, STORE PLAN:
  - `78-fullstack-builder.js` ? REMAINING ? triggers: APP PLAN:, FULLSTACK BUILD:, SAAS BUILD:, WEBSITE BUILD:
  - `79-uiux-architect.js` ? REMAINING ? triggers: APP UX:, DESIGN SYSTEM:, LANDING PAGE UX:, UIUX ARCHITECT:
  - `80-dependency-manager.js` ? REMAINING ? triggers: DEPENDENCY PLAN:, INSTALL REVIEW:, PACKAGE GAP:, STACK CHECK:
  - `81-project-scaffold.js` ? REMAINING ? triggers: PROJECT SCAFFOLD:, SCAFFOLD APP:, SCAFFOLD SITE:, STACK BLUEPRINT:
  - `82-app-launch-manager.js` ? REMAINING ? triggers: APP LAUNCH:, DEPLOYMENT PLAN:, GO LIVE:, LAUNCH CHECKLIST:
  - `84-github-orchestrator.js` ? REMAINING ? triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
  - `85-esignature.js` ? REMAINING ? triggers: ESIGN:, SIGN PDF:, SIGNATURE ARCHIVE:, SIGNATURE CANCEL:, SIGNATURE REMINDER:, SIGNATURE REQUEST:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### crm_patient_records

- Likely operator: `serena_crm_or_hub_later`
- Recommendation: Hold for Serena Hub / CRM / Business OS unless needed earlier. CRM should become multi-business patient/client/customer record layer.
- Files detected: 48
  - `01-crm.js` ? REMAINING ? triggers: ADD PATIENT:, GET PATIENT:, UPDATE PATIENT:
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `04-calendar.js` ? DONE/MERGED ? triggers: BOOK SLOT:, CANCEL APPOINTMENT:, CHECK AVAILABILITY:, TODAY SCHEDULE
  - `05-social.js` ? REMAINING ? triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
  - `06-notebook.js` ? REMAINING ? triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:
  - `08-google-docs.js` ? DONE/MERGED ? triggers: CREATE DOC:, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, UPDATE DOC:
  - `09-finance.js` ? DONE/MERGED ? triggers: GENERATE INVOICE:, INVOICE SUMMARY, PAID, PENDING, RECORD PAYMENT:
  - `10-payfast.js` ? DONE/MERGED ? triggers: PAYMENT LINK:, PAYMENT STATUS:
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `15-video-script.js` ? REMAINING ? triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
  - `16-ebook.js` ? REMAINING ? triggers: EBOOK CHAPTER:, EBOOK OUTLINE, EBOOK OUTLINE:, EBOOK:
  - `17-newsletter.js` ? REMAINING ? triggers: HEALTH NEWSLETTER:, NEWSLETTER:, WEEKLY NEWSLETTER
  - `19-email-marketing.js` ? REMAINING ? triggers: EMAIL CAMPAIGN:, EMAIL DRAFT:
  - `20-booking.js` ? REMAINING ? triggers: BOOK APPOINTMENT:, CANCEL BOOKING:, MY BOOKINGS, NEW BOOKING:
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `22-leadmagnet.js` ? REMAINING ? triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
  - `23-telehealth.js` ? REMAINING ? triggers: CONSULT PREP:, TELEHEALTH PREP:
  - `24-compliance-guard.js` ? DONE/MERGED ? triggers: QUICK CHECK:
  - `25-compliance.js` ? DONE/MERGED ? triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
  - `26-canva.js` ? REMAINING ? triggers: CANVA ASK, CANVA ASK:, CANVA COMMENT:, CANVA CONNECT, CANVA DESIGN:, CANVA EXPORT:
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `34-voice-out.js` ? REMAINING ? triggers: GOOGLE_TTS_API_KEY, READ ALOUD:, SPEAK:, TTS:
  - `36-voice-in.js` ? REMAINING ? triggers: TRANSCRIBE:, VOICE NOTE:, VOICE STATUS
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `44-hubspot.js` ? REMAINING ? triggers: GET, HUBSPOT CONTACT:, HUBSPOT DEAL:, HUBSPOT_API_KEY, POST
  - `46-database.js` ? REMAINING ? triggers: DB BACKUP:, DB QUERY:, PRAGMA, SELECT, WITH
  - `47-health-monitor.js` ? DONE/MERGED ? triggers: BOT STATUS, HEALTH CHECK, SELECT 1, STATUS, SYSTEM STATUS
  - `51-ai-teacher.js` ? REMAINING ? triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `56-CrmSync.js` ? REMAINING ? triggers: ADD PATIENT:, CLICKUP_SPACE_PATIENTS, CRM SYNC:, CU SETUP, CU TASK:, IMPORT CSV:
  - `57-LabResultsInterpreter.js` ? REMAINING ? triggers: INTERPRET LAB:, LAB RESULTS:, READ LAB:
  - `58-ApptReminders.js` ? REMAINING ? triggers: REMINDER STATUS, SEND REMINDERS, TEST REMINDER:
  - `59-ContentRepurposeEngine.js` ? REMAINING ? triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
  - `60-browser.js` ? REMAINING ? triggers: BROWSE:, BROWSER:, FILL FORM:, SCRAPE PAGE:, SCREENSHOT:
  - `62-memory.js` ? REMAINING ? triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
  - `63-files.js` ? DONE/MERGED ? triggers: MCP DIR:, MCP FILE READ:, MCP FILE SEARCH:, MCP FILE WRITE:
  - `64-github.js` ? DONE/MERGED ? triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
  - `65-location.js` ? REMAINING ? triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
  - `66-mcp-status.js` ? REMAINING ? triggers: MCP CALL:, MCP STATUS, MCP TOOLS:
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `74-freelance-services.js` ? REMAINING ? triggers: CLIENT SERVICE:, FREELANCE SERVICE:, REMOTE OFFER:, SERVICE PACKAGE:
  - `75-research-operator.js` ? REMAINING ? triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
  - `84-github-orchestrator.js` ? REMAINING ? triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
  - `85-esignature.js` ? REMAINING ? triggers: ESIGN:, SIGN PDF:, SIGNATURE ARCHIVE:, SIGNATURE CANCEL:, SIGNATURE REMINDER:, SIGNATURE REQUEST:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:

### marketing_communications

- Likely operator: `serena_marketing`
- Recommendation: Merge into Marketing / Communications Operator with Compliance guardrails. Keep email/newsletter/social together.
- Files detected: 61
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `03-gdrive.js` ? DONE/MERGED ? triggers: DRIVE FOLDER:, DRIVE LIST:, DRIVE SAVE:, DRIVE UPLOAD:
  - `05-social.js` ? REMAINING ? triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
  - `06-notebook.js` ? REMAINING ? triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:
  - `07-assets.js` ? REMAINING ? triggers: CREATE DECK:, GENERATE SLIDES:
  - `08-google-docs.js` ? DONE/MERGED ? triggers: CREATE DOC:, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, UPDATE DOC:
  - `11-whatsapp.js` ? REMAINING ? triggers: N/A, POST, WHATSAPP:
  - `14-podcast.js` ? REMAINING ? triggers: EPISODE SCRIPT:, PODCAST SCRIPT:
  - `15-video-script.js` ? REMAINING ? triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
  - `16-ebook.js` ? REMAINING ? triggers: EBOOK CHAPTER:, EBOOK OUTLINE, EBOOK OUTLINE:, EBOOK:
  - `17-newsletter.js` ? REMAINING ? triggers: HEALTH NEWSLETTER:, NEWSLETTER:, WEEKLY NEWSLETTER
  - `18-blog.js` ? REMAINING ? triggers: BLOG POST:, SEO ARTICLE:, WRITE BLOG:
  - `19-email-marketing.js` ? REMAINING ? triggers: EMAIL CAMPAIGN:, EMAIL DRAFT:
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `22-leadmagnet.js` ? REMAINING ? triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
  - `23-telehealth.js` ? REMAINING ? triggers: CONSULT PREP:, TELEHEALTH PREP:
  - `24-compliance-guard.js` ? DONE/MERGED ? triggers: QUICK CHECK:
  - `25-compliance.js` ? DONE/MERGED ? triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
  - `26-canva.js` ? REMAINING ? triggers: CANVA ASK, CANVA ASK:, CANVA COMMENT:, CANVA CONNECT, CANVA DESIGN:, CANVA EXPORT:
  - `27-gemini.js` ? REMAINING ? triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `30-seo-audit.js` ? REMAINING ? triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
  - `31-flux-image.js` ? REMAINING ? triggers: FLUX:, GENERATE IMAGE:, IMAGE:, POST
  - `32-video-generator.js` ? REMAINING ? triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:
  - `33-mistral.js` ? REMAINING ? triggers: ANALYSE IMAGE:, MISTRAL ANALYSE:, MISTRAL:, POST, READ DOCUMENT:
  - `35-translate.js` ? REMAINING ? triggers: AFRIKAANS:, TRANSLATE TO:, TRANSLATE:, VERTAAL:
  - `37-ocr.js` ? DONE/MERGED ? triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `39-remove-bg.js` ? REMAINING ? triggers: CLEAN IMAGE:, HUGGINGFACE_API_KEY, REMOVE BG:
  - `40-image-caption.js` ? REMAINING ? triggers: CAPTION IMAGE:, DESCRIBE IMAGE:
  - `41-vscode.js` ? DONE/MERGED ? triggers: FILE LIST:, FILE READ:, FILE WRITE:, GITHUB CLONE:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `44-hubspot.js` ? REMAINING ? triggers: GET, HUBSPOT CONTACT:, HUBSPOT DEAL:, HUBSPOT_API_KEY, POST
  - `49-security.js` ? REMAINING ? triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
  - `51-ai-teacher.js` ? REMAINING ? triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `54-video-edit.js` ? REMAINING ? triggers: AUTO CAPTION:, EDIT VIDEO:
  - `57-LabResultsInterpreter.js` ? REMAINING ? triggers: INTERPRET LAB:, LAB RESULTS:, READ LAB:
  - `59-ContentRepurposeEngine.js` ? REMAINING ? triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
  - `60-browser.js` ? REMAINING ? triggers: BROWSE:, BROWSER:, FILL FORM:, SCRAPE PAGE:, SCREENSHOT:
  - `62-memory.js` ? REMAINING ? triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
  - `63-files.js` ? DONE/MERGED ? triggers: MCP DIR:, MCP FILE READ:, MCP FILE SEARCH:, MCP FILE WRITE:
  - `64-github.js` ? DONE/MERGED ? triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
  - `65-location.js` ? REMAINING ? triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
  - `66-mcp-status.js` ? REMAINING ? triggers: MCP CALL:, MCP STATUS, MCP TOOLS:
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `71-digital-products.js` ? REMAINING ? triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
  - `72-affiliate-engine.js` ? REMAINING ? triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `74-freelance-services.js` ? REMAINING ? triggers: CLIENT SERVICE:, FREELANCE SERVICE:, REMOTE OFFER:, SERVICE PACKAGE:
  - `75-agency-offers.js` ? REMAINING ? triggers: AGENCY OFFER:, AGENCY PACKAGE:, CONSULTING OFFER:, SERVICE PROPOSAL:
  - `75-research-operator.js` ? REMAINING ? triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
  - `76-knowledge-business.js` ? REMAINING ? triggers: COURSE PLAN:, KNOWLEDGE BUSINESS:, MEMBERSHIP MODEL:, NEWSLETTER BUSINESS:
  - `78-fullstack-builder.js` ? REMAINING ? triggers: APP PLAN:, FULLSTACK BUILD:, SAAS BUILD:, WEBSITE BUILD:
  - `82-app-launch-manager.js` ? REMAINING ? triggers: APP LAUNCH:, DEPLOYMENT PLAN:, GO LIVE:, LAUNCH CHECKLIST:
  - `84-github-orchestrator.js` ? REMAINING ? triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### analytics_reporting

- Likely operator: `serena_analytics_or_serena_reporting`
- Recommendation: Already partly covered by Analytics and Reporting. Remaining files should be checked for gaps, then merged into existing operators instead of separate skills.
- Files detected: 23
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `25-compliance.js` ? DONE/MERGED ? triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `30-seo-audit.js` ? REMAINING ? triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
  - `37-ocr.js` ? DONE/MERGED ? triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `43-clickup.js` ? REMAINING ? triggers: CU ASK:, CU CREATE FOLDER:, CU CREATE LIST:, CU CREATE SPACE:, CU CREATE TASK:, CU DELETE FOLDER:
  - `45-payflow.js` ? DONE/MERGED ? triggers: PAYFLOW:, SUBSCRIPTION:
  - `49-security.js` ? REMAINING ? triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
  - `53-affiliate.js` ? REMAINING ? triggers: AFFILIATE PRODUCTS, PRODUCT LINKS:
  - `63-files.js` ? DONE/MERGED ? triggers: MCP DIR:, MCP FILE READ:, MCP FILE SEARCH:, MCP FILE WRITE:
  - `64-github.js` ? DONE/MERGED ? triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `68-autonomous-mode.js` ? REMAINING ? triggers: AUTO OFF, AUTO ON, AUTO REPORT, AUTO STATUS, CLEAR PENDING, PENDING
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `71-digital-products.js` ? REMAINING ? triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
  - `72-affiliate-engine.js` ? REMAINING ? triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `84-github-orchestrator.js` ? REMAINING ? triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### clinical_health_patient_ops

- Likely operator: `serena_clinical_patient_ops`
- Recommendation: Build as Clinical / Patient Ops operator or merge into Compliance/OCR/Docs depending on function. Keep strict medical-safety boundaries.
- Files detected: 71
  - `01-crm.js` ? REMAINING ? triggers: ADD PATIENT:, GET PATIENT:, UPDATE PATIENT:
  - `02-reporting.js` ? DONE/MERGED ? triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
  - `04-calendar.js` ? DONE/MERGED ? triggers: BOOK SLOT:, CANCEL APPOINTMENT:, CHECK AVAILABILITY:, TODAY SCHEDULE
  - `05-social.js` ? REMAINING ? triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
  - `06-notebook.js` ? REMAINING ? triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:
  - `09-finance.js` ? DONE/MERGED ? triggers: GENERATE INVOICE:, INVOICE SUMMARY, PAID, PENDING, RECORD PAYMENT:
  - `10-payfast.js` ? DONE/MERGED ? triggers: PAYMENT LINK:, PAYMENT STATUS:
  - `11-whatsapp.js` ? REMAINING ? triggers: N/A, POST, WHATSAPP:
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `14-podcast.js` ? REMAINING ? triggers: EPISODE SCRIPT:, PODCAST SCRIPT:
  - `15-video-script.js` ? REMAINING ? triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
  - `16-ebook.js` ? REMAINING ? triggers: EBOOK CHAPTER:, EBOOK OUTLINE, EBOOK OUTLINE:, EBOOK:
  - `17-newsletter.js` ? REMAINING ? triggers: HEALTH NEWSLETTER:, NEWSLETTER:, WEEKLY NEWSLETTER
  - `18-blog.js` ? REMAINING ? triggers: BLOG POST:, SEO ARTICLE:, WRITE BLOG:
  - `19-email-marketing.js` ? REMAINING ? triggers: EMAIL CAMPAIGN:, EMAIL DRAFT:
  - `20-booking.js` ? REMAINING ? triggers: BOOK APPOINTMENT:, CANCEL BOOKING:, MY BOOKINGS, NEW BOOKING:
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `22-leadmagnet.js` ? REMAINING ? triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
  - `23-telehealth.js` ? REMAINING ? triggers: CONSULT PREP:, TELEHEALTH PREP:
  - `24-compliance-guard.js` ? DONE/MERGED ? triggers: QUICK CHECK:
  - `25-compliance.js` ? DONE/MERGED ? triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
  - `26-canva.js` ? REMAINING ? triggers: CANVA ASK, CANVA ASK:, CANVA COMMENT:, CANVA CONNECT, CANVA DESIGN:, CANVA EXPORT:
  - `27-gemini.js` ? REMAINING ? triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `30-seo-audit.js` ? REMAINING ? triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
  - `31-flux-image.js` ? REMAINING ? triggers: FLUX:, GENERATE IMAGE:, IMAGE:, POST
  - `32-video-generator.js` ? REMAINING ? triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:
  - `33-mistral.js` ? REMAINING ? triggers: ANALYSE IMAGE:, MISTRAL ANALYSE:, MISTRAL:, POST, READ DOCUMENT:
  - `35-translate.js` ? REMAINING ? triggers: AFRIKAANS:, TRANSLATE TO:, TRANSLATE:, VERTAAL:
  - `37-ocr.js` ? DONE/MERGED ? triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `41-vscode.js` ? DONE/MERGED ? triggers: FILE LIST:, FILE READ:, FILE WRITE:, GITHUB CLONE:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `43-clickup.js` ? REMAINING ? triggers: CU ASK:, CU CREATE FOLDER:, CU CREATE LIST:, CU CREATE SPACE:, CU CREATE TASK:, CU DELETE FOLDER:
  - `46-database.js` ? REMAINING ? triggers: DB BACKUP:, DB QUERY:, PRAGMA, SELECT, WITH
  - `47-health-monitor.js` ? DONE/MERGED ? triggers: BOT STATUS, HEALTH CHECK, SELECT 1, STATUS, SYSTEM STATUS
  - `48-notifications.js` ? REMAINING ? triggers: ALERT:, NOTIFY LIST, NOTIFY:, SCHEDULE NOTIFY:
  - `51-ai-teacher.js` ? REMAINING ? triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `53-affiliate.js` ? REMAINING ? triggers: AFFILIATE PRODUCTS, PRODUCT LINKS:
  - `55-Research.js` ? REMAINING ? triggers: PUBMED, research-fetch, systematic-review-find
  - `56-CrmSync.js` ? REMAINING ? triggers: ADD PATIENT:, CLICKUP_SPACE_PATIENTS, CRM SYNC:, CU SETUP, CU TASK:, IMPORT CSV:
  - `57-LabResultsInterpreter.js` ? REMAINING ? triggers: INTERPRET LAB:, LAB RESULTS:, READ LAB:
  - `58-ApptReminders.js` ? REMAINING ? triggers: REMINDER STATUS, SEND REMINDERS, TEST REMINDER:
  - `59-ContentRepurposeEngine.js` ? REMAINING ? triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
  - `61-web-search.js` ? REMAINING ? triggers: COMPETITOR:, FIND NEWS:, RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:
  - `62-memory.js` ? REMAINING ? triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
  - `64-github.js` ? DONE/MERGED ? triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
  - `65-location.js` ? REMAINING ? triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
  - `66-mcp-status.js` ? REMAINING ? triggers: MCP CALL:, MCP STATUS, MCP TOOLS:
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `68-autonomous-mode.js` ? REMAINING ? triggers: AUTO OFF, AUTO ON, AUTO REPORT, AUTO STATUS, CLEAR PENDING, PENDING
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `71-digital-products.js` ? REMAINING ? triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
  - `72-affiliate-engine.js` ? REMAINING ? triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `74-freelance-services.js` ? REMAINING ? triggers: CLIENT SERVICE:, FREELANCE SERVICE:, REMOTE OFFER:, SERVICE PACKAGE:
  - `75-agency-offers.js` ? REMAINING ? triggers: AGENCY OFFER:, AGENCY PACKAGE:, CONSULTING OFFER:, SERVICE PROPOSAL:
  - `75-research-operator.js` ? REMAINING ? triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
  - `76-knowledge-business.js` ? REMAINING ? triggers: COURSE PLAN:, KNOWLEDGE BUSINESS:, MEMBERSHIP MODEL:, NEWSLETTER BUSINESS:
  - `77-ecommerce-operations.js` ? REMAINING ? triggers: ECOMMERCE OPS:, PRODUCT OPS:, SHOP STRATEGY:, STORE PLAN:
  - `78-fullstack-builder.js` ? REMAINING ? triggers: APP PLAN:, FULLSTACK BUILD:, SAAS BUILD:, WEBSITE BUILD:
  - `79-uiux-architect.js` ? REMAINING ? triggers: APP UX:, DESIGN SYSTEM:, LANDING PAGE UX:, UIUX ARCHITECT:
  - `80-dependency-manager.js` ? REMAINING ? triggers: DEPENDENCY PLAN:, INSTALL REVIEW:, PACKAGE GAP:, STACK CHECK:
  - `81-project-scaffold.js` ? REMAINING ? triggers: PROJECT SCAFFOLD:, SCAFFOLD APP:, SCAFFOLD SITE:, STACK BLUEPRINT:
  - `82-app-launch-manager.js` ? REMAINING ? triggers: APP LAUNCH:, DEPLOYMENT PLAN:, GO LIVE:, LAUNCH CHECKLIST:
  - `85-esignature.js` ? REMAINING ? triggers: ESIGN:, SIGN PDF:, SIGNATURE ARCHIVE:, SIGNATURE CANCEL:, SIGNATURE REMINDER:, SIGNATURE REQUEST:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### websites_wordpress_content

- Likely operator: `serena_websites_wordpress`
- Recommendation: Build as Websites / WordPress Operator, with Analytics, Marketing, Docs/Drive, and Compliance hooks.
- Files detected: 43
  - `05-social.js` ? REMAINING ? triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
  - `10-payfast.js` ? DONE/MERGED ? triggers: PAYMENT LINK:, PAYMENT STATUS:
  - `11-whatsapp.js` ? REMAINING ? triggers: N/A, POST, WHATSAPP:
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `14-podcast.js` ? REMAINING ? triggers: EPISODE SCRIPT:, PODCAST SCRIPT:
  - `15-video-script.js` ? REMAINING ? triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
  - `18-blog.js` ? REMAINING ? triggers: BLOG POST:, SEO ARTICLE:, WRITE BLOG:
  - `22-leadmagnet.js` ? REMAINING ? triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
  - `24-compliance-guard.js` ? DONE/MERGED ? triggers: QUICK CHECK:
  - `27-gemini.js` ? REMAINING ? triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `30-seo-audit.js` ? REMAINING ? triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
  - `31-flux-image.js` ? REMAINING ? triggers: FLUX:, GENERATE IMAGE:, IMAGE:, POST
  - `32-video-generator.js` ? REMAINING ? triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:
  - `33-mistral.js` ? REMAINING ? triggers: ANALYSE IMAGE:, MISTRAL ANALYSE:, MISTRAL:, POST, READ DOCUMENT:
  - `37-ocr.js` ? DONE/MERGED ? triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `39-remove-bg.js` ? REMAINING ? triggers: CLEAN IMAGE:, HUGGINGFACE_API_KEY, REMOVE BG:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `44-hubspot.js` ? REMAINING ? triggers: GET, HUBSPOT CONTACT:, HUBSPOT DEAL:, HUBSPOT_API_KEY, POST
  - `47-health-monitor.js` ? DONE/MERGED ? triggers: BOT STATUS, HEALTH CHECK, SELECT 1, STATUS, SYSTEM STATUS
  - `49-security.js` ? REMAINING ? triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
  - `51-ai-teacher.js` ? REMAINING ? triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `53-affiliate.js` ? REMAINING ? triggers: AFFILIATE PRODUCTS, PRODUCT LINKS:
  - `54-video-edit.js` ? REMAINING ? triggers: AUTO CAPTION:, EDIT VIDEO:
  - `59-ContentRepurposeEngine.js` ? REMAINING ? triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
  - `60-browser.js` ? REMAINING ? triggers: BROWSE:, BROWSER:, FILL FORM:, SCRAPE PAGE:, SCREENSHOT:
  - `61-web-search.js` ? REMAINING ? triggers: COMPETITOR:, FIND NEWS:, RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:
  - `65-location.js` ? REMAINING ? triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
  - `70-conversion-optimizer.js` ? REMAINING ? triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
  - `71-digital-products.js` ? REMAINING ? triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
  - `72-affiliate-engine.js` ? REMAINING ? triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
  - `73-website-revenue-audit.js` ? REMAINING ? triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
  - `75-research-operator.js` ? REMAINING ? triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
  - `78-fullstack-builder.js` ? REMAINING ? triggers: APP PLAN:, FULLSTACK BUILD:, SAAS BUILD:, WEBSITE BUILD:
  - `79-uiux-architect.js` ? REMAINING ? triggers: APP UX:, DESIGN SYSTEM:, LANDING PAGE UX:, UIUX ARCHITECT:
  - `81-project-scaffold.js` ? REMAINING ? triggers: PROJECT SCAFFOLD:, SCAFFOLD APP:, SCAFFOLD SITE:, STACK BLUEPRINT:
  - `82-app-launch-manager.js` ? REMAINING ? triggers: APP LAUNCH:, DEPLOYMENT PLAN:, GO LIVE:, LAUNCH CHECKLIST:
  - `84-github-orchestrator.js` ? REMAINING ? triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
  - `85-esignature.js` ? REMAINING ? triggers: ESIGN:, SIGN PDF:, SIGNATURE ARCHIVE:, SIGNATURE CANCEL:, SIGNATURE REMINDER:, SIGNATURE REQUEST:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:

### assistant_core_admin

- Likely operator: `serena_core_operator`
- Recommendation: Treat as Serena core/operator capability. Merge carefully into existing local operator/core systems.
- Files detected: 59
  - `01-crm.js` ? REMAINING ? triggers: ADD PATIENT:, GET PATIENT:, UPDATE PATIENT:
  - `05-social.js` ? REMAINING ? triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
  - `06-notebook.js` ? REMAINING ? triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:
  - `07-assets.js` ? REMAINING ? triggers: CREATE DECK:, GENERATE SLIDES:
  - `08-google-docs.js` ? DONE/MERGED ? triggers: CREATE DOC:, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, UPDATE DOC:
  - `09-finance.js` ? DONE/MERGED ? triggers: GENERATE INVOICE:, INVOICE SUMMARY, PAID, PENDING, RECORD PAYMENT:
  - `12-analytics.js` ? DONE/MERGED ? triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
  - `14-podcast.js` ? REMAINING ? triggers: EPISODE SCRIPT:, PODCAST SCRIPT:
  - `15-video-script.js` ? REMAINING ? triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
  - `16-ebook.js` ? REMAINING ? triggers: EBOOK CHAPTER:, EBOOK OUTLINE, EBOOK OUTLINE:, EBOOK:
  - `17-newsletter.js` ? REMAINING ? triggers: HEALTH NEWSLETTER:, NEWSLETTER:, WEEKLY NEWSLETTER
  - `18-blog.js` ? REMAINING ? triggers: BLOG POST:, SEO ARTICLE:, WRITE BLOG:
  - `19-email-marketing.js` ? REMAINING ? triggers: EMAIL CAMPAIGN:, EMAIL DRAFT:
  - `20-booking.js` ? REMAINING ? triggers: BOOK APPOINTMENT:, CANCEL BOOKING:, MY BOOKINGS, NEW BOOKING:
  - `21-membership.js` ? REMAINING ? triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
  - `22-leadmagnet.js` ? REMAINING ? triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
  - `23-telehealth.js` ? REMAINING ? triggers: CONSULT PREP:, TELEHEALTH PREP:
  - `24-compliance-guard.js` ? DONE/MERGED ? triggers: QUICK CHECK:
  - `25-compliance.js` ? DONE/MERGED ? triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
  - `26-canva.js` ? REMAINING ? triggers: CANVA ASK, CANVA ASK:, CANVA COMMENT:, CANVA CONNECT, CANVA DESIGN:, CANVA EXPORT:
  - `27-gemini.js` ? REMAINING ? triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
  - `28-email-funnel.js` ? REMAINING ? triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
  - `29-ecommerce.js` ? REMAINING ? triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
  - `30-seo-audit.js` ? REMAINING ? triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
  - `32-video-generator.js` ? REMAINING ? triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:
  - `33-mistral.js` ? REMAINING ? triggers: ANALYSE IMAGE:, MISTRAL ANALYSE:, MISTRAL:, POST, READ DOCUMENT:
  - `34-voice-out.js` ? REMAINING ? triggers: GOOGLE_TTS_API_KEY, READ ALOUD:, SPEAK:, TTS:
  - `35-translate.js` ? REMAINING ? triggers: AFRIKAANS:, TRANSLATE TO:, TRANSLATE:, VERTAAL:
  - `36-voice-in.js` ? REMAINING ? triggers: TRANSCRIBE:, VOICE NOTE:, VOICE STATUS
  - `37-ocr.js` ? DONE/MERGED ? triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST
  - `38-summarise.js` ? REMAINING ? triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
  - `40-image-caption.js` ? REMAINING ? triggers: CAPTION IMAGE:, DESCRIBE IMAGE:
  - `42-automation.js` ? REMAINING ? triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
  - `43-clickup.js` ? REMAINING ? triggers: CU ASK:, CU CREATE FOLDER:, CU CREATE LIST:, CU CREATE SPACE:, CU CREATE TASK:, CU DELETE FOLDER:
  - `45-payflow.js` ? DONE/MERGED ? triggers: PAYFLOW:, SUBSCRIPTION:
  - `47-health-monitor.js` ? DONE/MERGED ? triggers: BOT STATUS, HEALTH CHECK, SELECT 1, STATUS, SYSTEM STATUS
  - `48-notifications.js` ? REMAINING ? triggers: ALERT:, NOTIFY LIST, NOTIFY:, SCHEDULE NOTIFY:
  - `49-security.js` ? REMAINING ? triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
  - `51-ai-teacher.js` ? REMAINING ? triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
  - `52-corporate-wellness.js` ? REMAINING ? triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
  - `54-video-edit.js` ? REMAINING ? triggers: AUTO CAPTION:, EDIT VIDEO:
  - `55-Research.js` ? REMAINING ? triggers: PUBMED, research-fetch, systematic-review-find
  - `57-LabResultsInterpreter.js` ? REMAINING ? triggers: INTERPRET LAB:, LAB RESULTS:, READ LAB:
  - `58-ApptReminders.js` ? REMAINING ? triggers: REMINDER STATUS, SEND REMINDERS, TEST REMINDER:
  - `59-ContentRepurposeEngine.js` ? REMAINING ? triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
  - `60-browser.js` ? REMAINING ? triggers: BROWSE:, BROWSER:, FILL FORM:, SCRAPE PAGE:, SCREENSHOT:
  - `61-web-search.js` ? REMAINING ? triggers: COMPETITOR:, FIND NEWS:, RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:
  - `62-memory.js` ? REMAINING ? triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
  - `63-files.js` ? DONE/MERGED ? triggers: MCP DIR:, MCP FILE READ:, MCP FILE SEARCH:, MCP FILE WRITE:
  - `64-github.js` ? DONE/MERGED ? triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
  - `65-location.js` ? REMAINING ? triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
  - `66-mcp-status.js` ? REMAINING ? triggers: MCP CALL:, MCP STATUS, MCP TOOLS:
  - `67-documents.js` ? DONE/MERGED ? triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
  - `69-monetization-orchestrator.js` ? REMAINING ? triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
  - `75-agency-offers.js` ? REMAINING ? triggers: AGENCY OFFER:, AGENCY PACKAGE:, CONSULTING OFFER:, SERVICE PROPOSAL:
  - `75-research-operator.js` ? REMAINING ? triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
  - `79-uiux-architect.js` ? REMAINING ? triggers: APP UX:, DESIGN SYSTEM:, LANDING PAGE UX:, UIUX ARCHITECT:
  - `98-lead-funnel.js` ? REMAINING ? triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:
  - `99-self-evolve.js` ? REMAINING ? triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:

### uncategorized_review_required

- Likely operator: `review_required`
- Recommendation: Manual review before deciding whether to merge, skip, or build standalone.
- Files detected: 2
  - `50-deployment.js` ? REMAINING ? triggers: DEPLOY:, RESTART BOT
  - `83-vscode-builder.js` ? DONE/MERGED ? triggers: ANALYZE PROJECT:, BUILD AGENT:, BUILD AI APP:, BUILD APP:, BUILD BACKEND:, BUILD CLOUD APP:

## File-by-file detail

### `01-crm.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 205
- Characters: 7663
- Triggers: ADD PATIENT:, GET PATIENT:, UPDATE PATIENT:
- Functions: none
- Env mentions: CRM, PATIENT

### `02-reporting.js`

- Status: converted_or_merged
- Groups: analytics_reporting, membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, marketing_communications, clinical_health_patient_ops
- Lines: 105
- Characters: 3818
- Triggers: KPI REPORT, MORNING BRIEF, WEEKLY REPORT
- Functions: none
- Env mentions: none

### `03-gdrive.js`

- Status: converted_or_merged
- Groups: marketing_communications
- Lines: 96
- Characters: 3508
- Triggers: DRIVE FOLDER:, DRIVE LIST:, DRIVE SAVE:, DRIVE UPLOAD:
- Functions: none
- Env mentions: GDRIVE, GDRIVE_ROOT_FOLDER_ID

### `04-calendar.js`

- Status: converted_or_merged
- Groups: ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops
- Lines: 183
- Characters: 6910
- Triggers: BOOK SLOT:, CANCEL APPOINTMENT:, CHECK AVAILABILITY:, TODAY SCHEDULE
- Functions: getCalendarClient
- Env mentions: API, CALENDAR, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

### `05-social.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 101
- Characters: 4638
- Triggers: FACEBOOK POST:, INSTAGRAM POST:, LINKEDIN POST:, SOCIAL DRAFT:, SOCIAL POST:, TWITTER POST:
- Functions: platformParam
- Env mentions: API, FACEBOOK

### `06-notebook.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 409
- Characters: 13381
- Triggers: ASK KNOWLEDGE:, NOTEBOOK SETUP, VAULT AUTOMATION STATUS, VAULT CREATE ALL, VAULT INVENTORY, VAULT INVENTORY:, VAULT MAP, VAULT MISSING DOCS, VAULT MISSING DOCS:, VAULT QUERY:, VAULT SOURCE ADD:, VAULT STAGE:, VAULT STATUS, VAULT SYNC, VAULT SYNC STATUS
- Functions: formatCreateLayout, formatInventory, formatMissingDocs, formatSetup, formatStatus, formatSyncResult, formatSyncStatus, formatVaultMap, getValueLine, parseSourcePayload, parseStagePayload, parseVaultOnly, parts, raw, runBridge
- Env mentions: DOCS

### `07-assets.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, assistant_core_admin
- Lines: 77
- Characters: 2644
- Triggers: CREATE DECK:, GENERATE SLIDES:
- Functions: generateDeckOutline, parsePayload
- Env mentions: none

### `08-google-docs.js`

- Status: converted_or_merged
- Groups: crm_patient_records, marketing_communications, assistant_core_admin
- Lines: 100
- Characters: 3259
- Triggers: CREATE DOC:, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, UPDATE DOC:
- Functions: generateDocContent, parsePayload, replaceExisting
- Env mentions: DOCS, GOOGLE, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

### `09-finance.js`

- Status: converted_or_merged
- Groups: crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 171
- Characters: 6730
- Triggers: GENERATE INVOICE:, INVOICE SUMMARY, PAID, PENDING, RECORD PAYMENT:
- Functions: totalAmount, vatAmount
- Env mentions: PAYFAST_ENABLED

### `10-payfast.js`

- Status: converted_or_merged
- Groups: ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops, websites_wordpress_content
- Lines: 120
- Characters: 4830
- Triggers: PAYMENT LINK:, PAYMENT STATUS:
- Functions: buildPayfastUrl
- Env mentions: PAYFAST, PAYFAST_ENABLED, PAYFAST_MERCHANT_ID, PAYFAST_MERCHANT_KEY, PAYFAST_PASSPHRASE, PAYFAST_SANDBOX, WORDPRESS_URL

### `11-whatsapp.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops, websites_wordpress_content
- Lines: 96
- Characters: 3255
- Triggers: N/A, POST, WHATSAPP:
- Functions: sendViaMetaAPI
- Env mentions: API, META_ACCESS_TOKEN, META_API_VERSION, META_PHONE_NUMBER_ID

### `12-analytics.js`

- Status: converted_or_merged
- Groups: analytics_reporting, membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 134
- Characters: 5395
- Triggers: ANALYTICS REPORT, N/A, SITE ANALYTICS
- Functions: fetchTelemetrySummary, fetchWooMetrics
- Env mentions: WOOCOMMERCE_KEY, WOOCOMMERCE_SECRET, WORDPRESS_URL

### `14-podcast.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 69
- Characters: 2965
- Triggers: EPISODE SCRIPT:, PODCAST SCRIPT:
- Functions: none
- Env mentions: API

### `15-video-script.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 84
- Characters: 3748
- Triggers: REEL SCRIPT:, TIKTOK SCRIPT:, VIDEO SCRIPT:
- Functions: platform
- Env mentions: none

### `16-ebook.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 150
- Characters: 6467
- Triggers: EBOOK CHAPTER:, EBOOK OUTLINE, EBOOK OUTLINE:, EBOOK:
- Functions: none
- Env mentions: none

### `17-newsletter.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 120
- Characters: 5433
- Triggers: HEALTH NEWSLETTER:, NEWSLETTER:, WEEKLY NEWSLETTER
- Functions: shouldSend
- Env mentions: PATIENT

### `18-blog.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 96
- Characters: 3741
- Triggers: BLOG POST:, SEO ARTICLE:, WRITE BLOG:
- Functions: wantsPublish
- Env mentions: none

### `19-email-marketing.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 131
- Characters: 5140
- Triggers: EMAIL CAMPAIGN:, EMAIL DRAFT:
- Functions: none
- Env mentions: API

### `20-booking.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 284
- Characters: 10697
- Triggers: BOOK APPOINTMENT:, CANCEL BOOKING:, MY BOOKINGS, NEW BOOKING:
- Functions: getCalendarClient
- Env mentions: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

### `21-membership.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 204
- Characters: 7650
- Triggers: CREATE MEMBERSHIP:, ENROL MEMBER:, MEMBER STATUS:, MEMBERSHIP PLANS
- Functions: none
- Env mentions: MEMBER, MEMBERSHIP, PATIENT

### `22-leadmagnet.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 98
- Characters: 4478
- Triggers: CAPTURE PAGE:, FREEBIE:, LEAD MAGNET FULL:, LEAD PAGE:
- Functions: none
- Env mentions: none

### `23-telehealth.js`

- Status: remaining_or_unconfirmed
- Groups: clinical_health_patient_ops, crm_patient_records, marketing_communications, assistant_core_admin
- Lines: 59
- Characters: 2196
- Triggers: CONSULT PREP:, TELEHEALTH PREP:
- Functions: generatePrep, parsePayload
- Env mentions: none

### `24-compliance-guard.js`

- Status: converted_or_merged
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 113
- Characters: 4932
- Triggers: QUICK CHECK:
- Functions: none
- Env mentions: none

### `25-compliance.js`

- Status: converted_or_merged
- Groups: crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 98
- Characters: 4160
- Triggers: ANALYSE CONTENT:, COMPLIANCE CHECK:, FULL COMPLIANCE:, HPCSA CHECK:
- Functions: none
- Env mentions: META

### `26-canva.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 220
- Characters: 12828
- Triggers: CANVA ASK, CANVA ASK:, CANVA COMMENT:, CANVA CONNECT, CANVA DESIGN:, CANVA EXPORT:, CANVA FIND:, CANVA GET DESIGN:, CANVA LIST DESIGNS, CANVA LIST DESIGNS:, CANVA MCP, CANVA MCP SEARCH, CANVA MCP SEARCH:, CANVA STATUS, CANVA UPLOAD ASSET:, CANVA_CLIENT_ID, CANVA_CLIENT_SECRET, CANVA_REDIRECT_URI, CREATE DESIGN:
- Functions: buildConnectRoute, buildRestFallback, generateDesignBrief, inferIntent, maybeCallCanvaMcp, parseLegacyBrief, parseLooseFields, sanitizeLine
- Env mentions: API, CANVA_CLIENT_ID, CANVA_CLIENT_SECRET

### `27-gemini.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 97
- Characters: 3315
- Triggers: DEEP ANALYSIS:, GEMINI ANALYSE:, GEMINI:, POST, STRATEGY:
- Functions: callGemini, fetchWithTimeout
- Env mentions: API, GEMINI_API_KEY

### `28-email-funnel.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 86
- Characters: 3971
- Triggers: BUILD FUNNEL:, DRIP SEQUENCE:, EMAIL FUNNEL:, NURTURE:
- Functions: none
- Env mentions: API

### `29-ecommerce.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 152
- Characters: 6105
- Triggers: POST, WC ORDER:, WC ORDERS, WC PRODUCT:, WC PRODUCTS, WC REVENUE
- Functions: base, items, wcGet, wcPost, wcUrl
- Env mentions: API, WOOCOMMERCE_KEY, WOOCOMMERCE_SECRET, WORDPRESS_URL

### `30-seo-audit.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 132
- Characters: 5522
- Triggers: AUDIT SITE:, NONE, SEO AUDIT:, SEO CHECK:
- Functions: canonical, externalLinks, fetchPageForSEO, imgCount, imgNoAlt, internalLinks, metaDesc, robotsMeta, title
- Env mentions: API, META

### `31-flux-image.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, websites_wordpress_content
- Lines: 92
- Characters: 3374
- Triggers: FLUX:, GENERATE IMAGE:, IMAGE:, POST
- Functions: none
- Env mentions: API, HF_API, HUGGINGFACE_API_KEY

### `32-video-generator.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 279
- Characters: 9530
- Triggers: GENERATE VIDEO:, VEO:, VIDEO AD:, VIDEO CINEMATIC:, VIDEO EDUCATION:, VIDEO FAST:, VIDEO FROM IMAGE:, VIDEO HQ:, VIDEO PRODUCT:, VIDEO REEL:, VIDEO REMIX:, VIDEO TESTIMONIAL STYLE:, VIDEO:
- Functions: buildUsageHelp, downloadTelegramPhoto, estimateCostNote, execute, getServiceBaseUrl, modeFromTrigger, uploadVideoArchive, waitForJobCompletion
- Env mentions: GDRIVE_ROOT_FOLDER_ID, TELEGRAM_TOKEN

### `33-mistral.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 130
- Characters: 4538
- Triggers: ANALYSE IMAGE:, MISTRAL ANALYSE:, MISTRAL:, POST, READ DOCUMENT:
- Functions: callMistral
- Env mentions: API, MISTRAL, MISTRAL_API_KEY, MISTRAL_URL, TELEGRAM_TOKEN

### `34-voice-out.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, assistant_core_admin
- Lines: 50
- Characters: 1708
- Triggers: GOOGLE_TTS_API_KEY, READ ALOUD:, SPEAK:, TTS:
- Functions: none
- Env mentions: GOOGLE_TTS_API_KEY

### `35-translate.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 84
- Characters: 3137
- Triggers: AFRIKAANS:, TRANSLATE TO:, TRANSLATE:, VERTAAL:
- Functions: none
- Env mentions: API, HUGGINGFACE_API_KEY

### `36-voice-in.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, assistant_core_admin
- Lines: 66
- Characters: 2733
- Triggers: TRANSCRIBE:, VOICE NOTE:, VOICE STATUS
- Functions: none
- Env mentions: HUGGINGFACE_API_KEY

### `37-ocr.js`

- Status: converted_or_merged
- Groups: marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 148
- Characters: 5369
- Triggers: EXTRACT TEXT:, HUGGINGFACE_API_KEY, MISTRAL_API_KEY, MODEL_LOADING, OCR:, POST, SCAN DOC:
- Functions: ocrViaHuggingFace, ocrViaMistral
- Env mentions: HUGGINGFACE_API_KEY, MISTRAL_API_KEY, TELEGRAM_TOKEN

### `38-summarise.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 115
- Characters: 4779
- Triggers: READ URL:, SUMMARISE URL:, SUMMARISE:, SUMMARIZE URL:, SUMMARIZE:
- Functions: fetchPageText
- Env mentions: KEY

### `39-remove-bg.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, websites_wordpress_content
- Lines: 71
- Characters: 2643
- Triggers: CLEAN IMAGE:, HUGGINGFACE_API_KEY, REMOVE BG:
- Functions: none
- Env mentions: HUGGINGFACE_API_KEY

### `40-image-caption.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, assistant_core_admin
- Lines: 60
- Characters: 2142
- Triggers: CAPTION IMAGE:, DESCRIBE IMAGE:
- Functions: describeImage
- Env mentions: none

### `41-vscode.js`

- Status: converted_or_merged
- Groups: marketing_communications, clinical_health_patient_ops
- Lines: 197
- Characters: 7262
- Triggers: FILE LIST:, FILE READ:, FILE WRITE:, GITHUB CLONE:
- Functions: cleanup
- Env mentions: GITHUB_TOKEN

### `42-automation.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 209
- Characters: 8896
- Triggers: CONTENT CALENDAR, MONTHLY CALENDAR:, SCHEDULE CONTENT:, TBD, WEEKLY PLAN
- Functions: parts, typeKey
- Env mentions: CALENDAR, FACEBOOK, KEY

### `43-clickup.js`

- Status: remaining_or_unconfirmed
- Groups: analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 840
- Characters: 35816
- Triggers: CU ASK:, CU CREATE FOLDER:, CU CREATE LIST:, CU CREATE SPACE:, CU CREATE TASK:, CU DELETE FOLDER:, CU DELETE LIST:, CU DELETE SPACE:, CU DELETE TASK:, CU FOLDERS, CU FOLDERS:, CU LIST, CU LIST SPACES, CU LIST SPACES:, CU LIST TASKS, CU LIST TASKS:, CU LIST:, CU LISTS, CU LISTS:, CU MCP COMMENT:, CU MCP REPORT:, CU MCP SEARCH:, CU MCP TIME:, CU SETUP, CU SPACES:, CU STRUCTURE, CU STRUCTURE:, CU SUBTASK:, CU TASK:, CU UPDATE FOLDER:, CU UPDATE LIST:, CU UPDATE SPACE:, CU UPDATE:, CU WORKSPACES, CU WORKSPACES:, TASK:
- Functions: buildRestFallback, configMessage, formatMcpResultForTelegram, formatRestFallback, formatSingleMcpItem, formatSpaces, formatTimestamp, formatTree, formatWorkspaces, humanizeHierarchy, inferMcpIntent, isConfigured, maybeCallClickUpMcp, mergeRequest, normalizeTriggerPayload, parseLooseFields, parseOperationRequest, resolveFolder, resolveList, resolveSpace
- Env mentions: API, CLICKUP_API_KEY

### `44-hubspot.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, websites_wordpress_content
- Lines: 98
- Characters: 2910
- Triggers: GET, HUBSPOT CONTACT:, HUBSPOT DEAL:, HUBSPOT_API_KEY, POST
- Functions: getHubSpotHeaders, hubspotRequest
- Env mentions: API, CRM, HUBSPOT_API_KEY

### `45-payflow.js`

- Status: converted_or_merged
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, analytics_reporting, assistant_core_admin
- Lines: 77
- Characters: 2706
- Triggers: PAYFLOW:, SUBSCRIPTION:
- Functions: parsePayload
- Env mentions: PAYFLOW, SUBSCRIPTION

### `46-database.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, clinical_health_patient_ops
- Lines: 61
- Characters: 2176
- Triggers: DB BACKUP:, DB QUERY:, PRAGMA, SELECT, WITH
- Functions: isSafeQuery
- Env mentions: none

### `47-health-monitor.js`

- Status: converted_or_merged
- Groups: crm_patient_records, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 101
- Characters: 4133
- Triggers: BOT STATUS, HEALTH CHECK, SELECT 1, STATUS, SYSTEM STATUS
- Functions: freeMem, heapTotMB, heapUsedMB, rssMB, totalMem
- Env mentions: API, CLICKUP_API_KEY, GEMINI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GROQ_API_KEY, HUGGINGFACE_API_KEY, PAYFAST_ENABLED, WORDPRESS_APP_PASSWORD, WORDPRESS_URL

### `48-notifications.js`

- Status: remaining_or_unconfirmed
- Groups: clinical_health_patient_ops, assistant_core_admin
- Lines: 145
- Characters: 6042
- Triggers: ALERT:, NOTIFY LIST, NOTIFY:, SCHEDULE NOTIFY:
- Functions: ownerIds
- Env mentions: none

### `49-security.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, analytics_reporting, websites_wordpress_content, assistant_core_admin
- Lines: 96
- Characters: 3966
- Triggers: ACCESS LOG, AUDIT BOT, SECURITY AUDIT, SECURITY STATUS
- Functions: ownerIds
- Env mentions: JWT_SECRET, PAYFAST_ENABLED, PAYFAST_SANDBOX, WORDPRESS_URL

### `50-deployment.js`

- Status: remaining_or_unconfirmed
- Groups: uncategorized_review_required
- Lines: 136
- Characters: 4103
- Triggers: DEPLOY:, RESTART BOT
- Functions: execFileAsync, isOwner, parseDeployIntent
- Env mentions: none

### `51-ai-teacher.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 186
- Characters: 8064
- Triggers: CREATE LESSON:, HEALTH QUIZ:, PATIENT EDUCATION:, QUIZ:, TEACH TOPIC:
- Functions: none
- Env mentions: PATIENT

### `52-corporate-wellness.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 196
- Characters: 8198
- Triggers: B2B LEAD:, CORPORATE PROPOSAL:, WELLNESS PROGRAM:, WELLNESS TALK:
- Functions: none
- Env mentions: CRM

### `53-affiliate.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content
- Lines: 60
- Characters: 2029
- Triggers: AFFILIATE PRODUCTS, PRODUCT LINKS:
- Functions: none
- Env mentions: none

### `54-video-edit.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, websites_wordpress_content, assistant_core_admin
- Lines: 84
- Characters: 2816
- Triggers: AUTO CAPTION:, EDIT VIDEO:
- Functions: ensureOutputDir, stamp, toSrt
- Env mentions: none

### `55-Research.js`

- Status: remaining_or_unconfirmed
- Groups: clinical_health_patient_ops, assistant_core_admin
- Lines: 54
- Characters: 2270
- Triggers: PUBMED, research-fetch, systematic-review-find
- Functions: none
- Env mentions: API

### `56-CrmSync.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, clinical_health_patient_ops
- Lines: 57
- Characters: 2319
- Triggers: ADD PATIENT:, CLICKUP_SPACE_PATIENTS, CRM SYNC:, CU SETUP, CU TASK:, IMPORT CSV:, SYNC PATIENTS
- Functions: none
- Env mentions: API, CLICKUP_API_KEY, CLICKUP_SPACE_PATIENTS, CRM, CRMSYNC, PATIENT, PATIENTS

### `57-LabResultsInterpreter.js`

- Status: remaining_or_unconfirmed
- Groups: clinical_health_patient_ops, crm_patient_records, marketing_communications, assistant_core_admin
- Lines: 66
- Characters: 2852
- Triggers: INTERPRET LAB:, LAB RESULTS:, READ LAB:
- Functions: none
- Env mentions: none

### `58-ApptReminders.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops, assistant_core_admin
- Lines: 168
- Characters: 6303
- Triggers: REMINDER STATUS, SEND REMINDERS, TEST REMINDER:
- Functions: buildReminderMessage, getCalendarClient, listUpcomingAppointments, upcoming
- Env mentions: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

### `59-ContentRepurposeEngine.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 72
- Characters: 3258
- Triggers: CONTENT VARIANTS:, REPURPOSE CONTENT:, REPURPOSE:
- Functions: none
- Env mentions: API

### `60-browser.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, websites_wordpress_content, assistant_core_admin
- Lines: 136
- Characters: 5225
- Triggers: BROWSE:, BROWSER:, FILL FORM:, SCRAPE PAGE:, SCREENSHOT:
- Functions: none
- Env mentions: API

### `61-web-search.js`

- Status: remaining_or_unconfirmed
- Groups: clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 102
- Characters: 3418
- Triggers: COMPETITOR:, FIND NEWS:, RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARCH:, SEARXNG STATUS, WEB SEARCH:
- Functions: cleanText, formatResearchErrorResponse, getResearchApi, getResearchSkill
- Env mentions: none

### `62-memory.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 402
- Characters: 12575
- Triggers: FORGET:, MEMORY LIST, RECALL:, REMEMBER:
- Functions: buildNaturalFactsFromSentence, cleanText, deriveFallbackKey, formatMcpMemoryText, formatResultsByType, mirrorFactToMcpMemory, normalizeText, searchMcpMemory, section, titleCaseWords, trimAtEmbeddedCommand
- Env mentions: REMEMBER

### `63-files.js`

- Status: converted_or_merged
- Groups: crm_patient_records, marketing_communications, analytics_reporting, assistant_core_admin
- Lines: 99
- Characters: 3900
- Triggers: MCP DIR:, MCP FILE READ:, MCP FILE SEARCH:, MCP FILE WRITE:
- Functions: none
- Env mentions: API

### `64-github.js`

- Status: converted_or_merged
- Groups: crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 133
- Characters: 5032
- Triggers: BUG REPORT:, CODE REQUEST:, GITHUB ISSUE:, GITHUB READ:, GITHUB STATUS
- Functions: none
- Env mentions: GITHUB_TOKEN

### `65-location.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 101
- Characters: 3854
- Triggers: DIRECTIONS:, FIND NEARBY:, LOCATE:, MAP SEARCH:
- Functions: none
- Env mentions: GOOGLE_MAPS_API_KEY

### `66-mcp-status.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 131
- Characters: 4921
- Triggers: MCP CALL:, MCP STATUS, MCP TOOLS:
- Functions: getAllTools, serverLines
- Env mentions: API

### `67-documents.js`

- Status: converted_or_merged
- Groups: ecommerce_woocommerce_store, crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 145
- Characters: 5333
- Triggers: CREATE DOCX:, CREATE EXCEL:, CREATE PDF:, CREATE WORD:, CREATE XLSX:, EXPORT PDF:
- Functions: deriveTitleAndBrief, extractJsonBlock, generateNarrative, generateWorkbookData
- Env mentions: DOCS

### `68-autonomous-mode.js`

- Status: remaining_or_unconfirmed
- Groups: analytics_reporting, clinical_health_patient_ops
- Lines: 53
- Characters: 1870
- Triggers: AUTO OFF, AUTO ON, AUTO REPORT, AUTO STATUS, CLEAR PENDING, PENDING
- Functions: none
- Env mentions: none

### `69-monetization-orchestrator.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, marketing_communications, analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 156
- Characters: 5593
- Triggers: MONETIZATION PLAN:, MONETIZATION STATUS, REVENUE ACTIONS, REVENUE PLAN:
- Functions: formatOutputSync, formatPlan
- Env mentions: none

### `70-conversion-optimizer.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content
- Lines: 124
- Characters: 4244
- Triggers: CONVERSION FIX:, CRO AUDIT:, CTA PLAN:, FUNNEL FIX:
- Functions: formatCroAudit, formatOutputSync
- Env mentions: none

### `71-digital-products.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content
- Lines: 119
- Characters: 4510
- Triggers: DIGITAL PRODUCT:, PRODUCT CATALOG, PRODUCT LAUNCH:, PRODUCT PAGE:
- Functions: cleanPayload, formatOutputSync, formatProductPlan, shouldPublish
- Env mentions: WORDPRESS_DEFAULT_PAGE_STATUS

### `72-affiliate-engine.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content
- Lines: 131
- Characters: 5075
- Triggers: AFFILIATE ENGINE:, AFFILIATE PAGE:, AFFILIATE PLAN:, PARTNER OFFERS:
- Functions: formatAffiliatePlan, formatOutputSync, stripPublish, wantsPublish
- Env mentions: WORDPRESS_AFFILIATE_PAGE_SLUG, WORDPRESS_AFFILIATE_PAGE_TITLE, WORDPRESS_DEFAULT_PAGE_STATUS

### `73-website-revenue-audit.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, crm_patient_records, marketing_communications, analytics_reporting, clinical_health_patient_ops, websites_wordpress_content
- Lines: 108
- Characters: 3956
- Triggers: MONETIZATION AUDIT:, REVENUE AUDIT:, SITE MONETIZATION:, WEBSITE REVENUE AUDIT
- Functions: formatAudit, formatOutputSync
- Env mentions: WORDPRESS_URL

### `74-freelance-services.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops
- Lines: 108
- Characters: 4010
- Triggers: CLIENT SERVICE:, FREELANCE SERVICE:, REMOTE OFFER:, SERVICE PACKAGE:
- Functions: formatOutputSync, formatServicePack
- Env mentions: CLIENT

### `75-agency-offers.js`

- Status: remaining_or_unconfirmed
- Groups: marketing_communications, clinical_health_patient_ops, assistant_core_admin
- Lines: 106
- Characters: 3890
- Triggers: AGENCY OFFER:, AGENCY PACKAGE:, CONSULTING OFFER:, SERVICE PROPOSAL:
- Functions: formatAgencyOffer, formatOutputSync
- Env mentions: none

### `75-research-operator.js`

- Status: remaining_or_unconfirmed
- Groups: crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 85
- Characters: 2725
- Triggers: RESEARCH COMPARE:, RESEARCH PAGE:, RESEARCH STATUS, RESEARCH:, SEARCH STATUS, SEARXNG STATUS
- Functions: cleanText, formatResearchErrorResponse, getOperator
- Env mentions: none

### `76-knowledge-business.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops
- Lines: 94
- Characters: 3601
- Triggers: COURSE PLAN:, KNOWLEDGE BUSINESS:, MEMBERSHIP MODEL:, NEWSLETTER BUSINESS:
- Functions: formatKnowledgeBusiness, formatOutputSync
- Env mentions: MEMBERSHIP

### `77-ecommerce-operations.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, clinical_health_patient_ops
- Lines: 81
- Characters: 3060
- Triggers: ECOMMERCE OPS:, PRODUCT OPS:, SHOP STRATEGY:, STORE PLAN:
- Functions: formatEcommerceOps
- Env mentions: none

### `78-fullstack-builder.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops, websites_wordpress_content
- Lines: 131
- Characters: 5207
- Triggers: APP PLAN:, FULLSTACK BUILD:, SAAS BUILD:, WEBSITE BUILD:
- Functions: formatBuildPlan, formatSection
- Env mentions: API

### `79-uiux-architect.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 82
- Characters: 3130
- Triggers: APP UX:, DESIGN SYSTEM:, LANDING PAGE UX:, UIUX ARCHITECT:
- Functions: formatUiUx
- Env mentions: none

### `80-dependency-manager.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, clinical_health_patient_ops
- Lines: 95
- Characters: 3533
- Triggers: DEPENDENCY PLAN:, INSTALL REVIEW:, PACKAGE GAP:, STACK CHECK:
- Functions: formatDependencyPlan
- Env mentions: none

### `81-project-scaffold.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, clinical_health_patient_ops, websites_wordpress_content
- Lines: 111
- Characters: 4044
- Triggers: PROJECT SCAFFOLD:, SCAFFOLD APP:, SCAFFOLD SITE:, STACK BLUEPRINT:
- Functions: cleanPayload, formatScaffold, wantsWrite
- Env mentions: none

### `82-app-launch-manager.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, marketing_communications, clinical_health_patient_ops, websites_wordpress_content
- Lines: 107
- Characters: 4146
- Triggers: APP LAUNCH:, DEPLOYMENT PLAN:, GO LIVE:, LAUNCH CHECKLIST:
- Functions: fmt, formatLaunchPlan
- Env mentions: none

### `83-vscode-builder.js`

- Status: converted_or_merged
- Groups: uncategorized_review_required
- Lines: 93
- Characters: 3185
- Triggers: ANALYZE PROJECT:, BUILD AGENT:, BUILD AI APP:, BUILD APP:, BUILD BACKEND:, BUILD CLOUD APP:, BUILD DESKTOP APP:, BUILD MOBILE APP:, CREATE TEMPLATE:, PATCH WORKSPACE:, RUN WORKSPACE:, VSCODE BUILDER STATUS
- Functions: none
- Env mentions: none

### `84-github-orchestrator.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, marketing_communications, analytics_reporting, websites_wordpress_content
- Lines: 93
- Characters: 3147
- Triggers: GITHUB PLATFORM STATUS, GITHUB REPO MAP, GITHUB SAVE ARTIFACT:
- Functions: repoDefaults
- Env mentions: GITHUB_TOKEN

### `85-esignature.js`

- Status: remaining_or_unconfirmed
- Groups: ecommerce_woocommerce_store, crm_patient_records, clinical_health_patient_ops, websites_wordpress_content
- Lines: 932
- Characters: 33280
- Triggers: ESIGN:, SIGN PDF:, SIGNATURE ARCHIVE:, SIGNATURE CANCEL:, SIGNATURE REMINDER:, SIGNATURE REQUEST:, SIGNATURE STATUS:
- Functions: archiveCompletedSubmission, buildDocusealFailureMessage, buildOwnerOnlyMessage, ensureRecordForRequest, executeLiveCancel, executeLiveCreate, fetchStatusFromProvider, getDocusealClient, getDocusealConfig, handleArchiveRequest, handleCancelRequest, handleCreateRequest, handleDirectApprovalExecution, handleReminderRequest, handleStatusRequest, hasDocuSealConfig, install, isApprovalQueueAvailable, isDocusealReady, isLiveModeEnabled
- Env mentions: DOCUSEAL_API_KEY, DOCUSEAL_API_URL, GOOGLE_DRIVE_TIMEOUT_MS

### `98-lead-funnel.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, crm_patient_records, marketing_communications, clinical_health_patient_ops, websites_wordpress_content, assistant_core_admin
- Lines: 98
- Characters: 6446
- Triggers: ABANDONED BOOKING:, LEAD MAGNET:, PATIENT FUNNEL:, RE-ENGAGE:, WELCOME SEQUENCE:
- Functions: safe
- Env mentions: PATIENT

### `99-self-evolve.js`

- Status: remaining_or_unconfirmed
- Groups: membership_programmes_subscriptions, ecommerce_woocommerce_store, marketing_communications, analytics_reporting, clinical_health_patient_ops, assistant_core_admin
- Lines: 524
- Characters: 16536
- Triggers: ACTIVATE SKILL:, EVOLVE:, GAP ANALYSIS, ROLLBACK SKILL:, SKILL STATUS, TEST SKILL:
- Functions: activateSkill, backupExistingSkill, buildMockContext, ensureState, evolveSkill, extractCodeBlock, findRequiredPackages, generateSkillCode, getOwnerIds, handleSkillStatus, incrementVersion, inferSkillFileName, isOwner, listAvailablePackages, normaliseFileName, readManifest, readState, rollbackSkill, runGapAnalysis, scanRecentLogs
- Env mentions: none
