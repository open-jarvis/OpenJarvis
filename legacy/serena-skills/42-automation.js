// 42-automation.js — Content Calendar Automation
// Generates full weekly/monthly content calendars and schedules.
// Direct posting deferred (Buffer/Hootsuite) — planning + content generation is live.

const logger = require('../helpers/logger');
const { generateStructuredOutput } = require('../helpers/structured-output');

const CONTENT_TYPES = ['Blog Post', 'Instagram Reel', 'LinkedIn Article', 'Newsletter Section', 'Podcast Episode', 'YouTube Short', 'Facebook Post', 'Patient Education Email'];

module.exports = {
  id: '42-automation',
  name: 'Content Calendar Automation',
  description: 'Generate weekly and monthly content calendars with full content plans for Dr Piet.',
  triggers: ['CONTENT CALENDAR', 'SCHEDULE CONTENT:', 'WEEKLY PLAN', 'MONTHLY CALENDAR:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_42_automation',
      description: 'Generate content calendars and schedule content tracking items.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['CONTENT CALENDAR', 'SCHEDULE CONTENT:', 'WEEKLY PLAN', 'MONTHLY CALENDAR:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      logger.info(`[AUTOMATION] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      // ── WEEKLY PLAN ──────────────────────────────────────────────
      if (context.triggerUsed === 'WEEKLY PLAN' || context.triggerUsed === 'CONTENT CALENDAR') {
        const theme = payload && payload.trim().length > 2
          ? payload.trim()
          : 'general health and wellness for South Africans';

        const now       = new Date();
        const weekStart = new Date(now);
        weekStart.setDate(now.getDate() - now.getDay() + 1);
        const weekLabel = weekStart.toLocaleDateString('en-ZA', { month: 'long', day: 'numeric' });

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a detailed 7-day content calendar for Dr Piet Muller's medical practice.\n\n` +
              `Week starting: ${weekLabel}\n` +
              `Weekly theme: "${theme}"\n\n` +
              `For each day (Monday through Sunday) provide:\n` +
              `📅 DAY + DATE\n` +
              `📋 Content type (from: ${CONTENT_TYPES.join(', ')})\n` +
              `📌 Topic + Angle\n` +
              `🎯 Key message (1 sentence)\n` +
              `🔑 Serena command to generate it\n\n` +
              `Rules:\n` +
              `- Mix platforms: don't repeat same type on consecutive days\n` +
              `- Align with the weekly theme\n` +
              `- Wednesday = patient education focus\n` +
              `- Friday = engagement/lighter content\n` +
              `- Sunday = rest or evergreen repurpose\n` +
              `- All HPCSA-compliant topics\n` +
              `- South African seasonal/cultural relevance where possible\n\n` +
              `End with: WEEKLY GOALS and TOP 3 PRIORITY PIECES to create first.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[AUTOMATION] Weekly calendar generated for theme: ${theme.substring(0,40)}`);
        return {
          response:
            `📅 *Weekly Content Calendar*\n` +
            `📌 Theme: _${theme}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            '💡 Generate any piece: use the Serena command shown for each day\n' +
            '💡 Full month: `MONTHLY CALENDAR: [theme]`'
        };
      }

      // ── MONTHLY CALENDAR ─────────────────────────────────────────
      if (context.triggerUsed === 'MONTHLY CALENDAR:') {
        const parts   = (payload || '').split('|').map(p => p.trim());
        const month   = parts[0] || new Date().toLocaleString('en-ZA', { month: 'long', year: 'numeric' });
        const focus   = parts[1] || 'holistic health and patient education';

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a strategic monthly content plan for Dr Piet Muller.\n\n` +
              `Month: ${month}\n` +
              `Strategic focus: "${focus}"\n\n` +
              `Provide:\n\n` +
              `1. MONTHLY THEME & CAMPAIGN ANGLE\n\n` +
              `2. WEEK-BY-WEEK BREAKDOWN:\n` +
              `   Week 1: Launch/Awareness angle + 5 content pieces\n` +
              `   Week 2: Education/Value angle + 5 content pieces\n` +
              `   Week 3: Social proof/Engagement angle + 5 content pieces\n` +
              `   Week 4: CTA/Conversion angle + 5 content pieces\n\n` +
              `For each content piece: type | topic | platform | Serena command\n\n` +
              `3. KEY DATES to leverage (SA public holidays, health awareness days)\n\n` +
              `4. LEAD MAGNET OPPORTUNITY for the month\n\n` +
              `5. EMAIL NEWSLETTER TOPICS (4 editions)\n\n` +
              `6. METRICS TO TRACK\n\n` +
              `Make it actionable and HPCSA-compliant.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );

        logger.info(`[AUTOMATION] Monthly calendar: ${month}`);
        return {
          response:
            `📅 *Monthly Content Plan — ${month}*\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content.substring(0, 3800) +
            (result.content.length > 3800 ? '\n\n_[Plan continues — save to Drive for full version]_' : '') +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Save: \`DRIVE SAVE: content-plan-${month.replace(/\s/g,'-')}.txt | [paste plan]\``
        };
      }

      // ── SCHEDULE CONTENT ─────────────────────────────────────────
      if (context.triggerUsed === 'SCHEDULE CONTENT:') {
        if (!payload || payload.trim().length < 3) {
          return {
            response:
              '📋 *Schedule Content*\n\n' +
              'Usage: `SCHEDULE CONTENT: content type | topic | date`\n\n' +
              'Example: `SCHEDULE CONTENT: Instagram Reel | 5 signs of high blood pressure | 2026-05-15`\n\n' +
              'This logs the content item for tracking. Generate it with the relevant skill command.'
          };
        }

        const parsed = await generateStructuredOutput(context, {
          logLabel: 'automation-schedule-content',
          reasoningEffort: 'medium',
          systemPrompt: 'Extract a content scheduling request.',
          userPrompt: `User request: ${payload}\n\nReturn JSON with type, topic, date.`,
          schema: {
            type: 'object',
            required: ['type', 'topic'],
            properties: {
              type: { type: 'string' },
              topic: { type: 'string' },
              date: { type: 'string' }
            }
          }
        });
        const type = parsed.type;
        const topic = parsed.topic;
        const date = parsed.date || '';

        if (context.db) {
          await context.db.run(
            `INSERT INTO tasks (task_id, name, description, status, skill_name, createdAt, updatedAt)
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
            [
              `CONTENT-${Date.now()}`,
              `${type}: ${topic}`,
              `Scheduled for ${date || 'TBD'}`,
              'pending',
              '42-automation',
              new Date().toISOString(),
              new Date().toISOString()
            ]
          );
        }

        const commandMap = {
          'instagram reel': `VIDEO SCRIPT: ${topic} | reel | 60s`,
          'linkedin':       `LINKEDIN POST: ${topic}`,
          'blog post':      `BLOG POST: ${topic}`,
          'newsletter':     `NEWSLETTER: ${topic}`,
          'podcast':        `PODCAST SCRIPT: ${topic}`,
          'facebook':       `FACEBOOK POST: ${topic}`
        };

        const typeKey = (type || '').toLowerCase();
        const command = Object.entries(commandMap).find(([k]) => typeKey.includes(k))?.[1] || `SOCIAL POST: ${topic}`;

        logger.info(`[AUTOMATION] Content scheduled: ${type} — ${topic}`);
        return {
          response:
            `✅ *Content Scheduled*\n\n` +
            `📋 *Type:* ${type}\n` +
            `📌 *Topic:* ${topic}\n` +
            `📅 *Date:* ${date || 'TBD'}\n\n` +
            `💡 Generate now:\n\`${command}\``
        };
      }

      return { response: '⚠️ Usage: `CONTENT CALENDAR`, `WEEKLY PLAN`, `MONTHLY CALENDAR: month`, `SCHEDULE CONTENT: type | topic | date`' };

    } catch (err) {
      logger.error('[AUTOMATION] Error:', err.message);
      return { response: `❌ Content calendar error: ${err.message}` };
    }
  }
};
