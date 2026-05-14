/**
 * Skill 98: Lead Funnel
 * FIXES: var→const, try/catch on all aiEngine calls, payload length guard
 */

const logger = require('../helpers/logger');

module.exports = {
  name: 'Lead Funnel',
  description: 'Lead magnets, email sequences, patient acquisition funnels',
  triggers: ['LEAD MAGNET:', 'WELCOME SEQUENCE:', 'ABANDONED BOOKING:', 'PATIENT FUNNEL:', 'RE-ENGAGE:'],

  execute: async function(payload, context) {

    if (context.triggerUsed === 'LEAD MAGNET:') {
      if (!payload || payload.trim().length < 3) {
        return { response: '⚠️ Usage: `LEAD MAGNET: [health topic]`\nExample: `LEAD MAGNET: blood pressure management for South Africans`' };
      }
      try {
        const safe = payload.trim().slice(0, 2000);
        const result = await context.aiEngine.chat(
          [{ role: 'user', content: 'Create a complete lead magnet package for a South African medical doctor\'s website. Topic: ' + safe + '\n\n1. LEAD MAGNET TITLE — 3 compelling options\n2. SUBTITLE — one sentence benefit\n3. WHAT\'S INSIDE — 5-7 specific bullet points\n4. FULL CONTENT — 800-1200 words, educational, evidence-informed, health disclaimer included\n5. LANDING PAGE COPY — headline, subheadline, 3 benefit bullets, CTA, trust statement\n6. THANK YOU PAGE — immediate value delivery, warm welcome from Dr Piet, next step' }],
          { systemPrompt: context.soulFile + '\n\nHealthcare lead magnet for South African medical doctor. Educational, compliant, warm and professional.', temperature: 0.6 }
        );
        logger.info('[FUNNEL] Lead magnet created: ' + safe.substring(0, 50));
        return { response: '🎁 *Lead Magnet Package:*\n\n' + result.content + '\n\n━━━━━━━━━━━━━━━━━━\n💡 Next: `WELCOME SEQUENCE: [topic]`' };
      } catch (err) {
        logger.error('[FUNNEL] Lead magnet error:', err.message);
        return { response: `❌ Lead magnet failed: ${err.message}. Please try again.` };
      }
    }

    if (context.triggerUsed === 'WELCOME SEQUENCE:') {
      if (!payload || payload.trim().length < 3) {
        return { response: '⚠️ Usage: `WELCOME SEQUENCE: [what they subscribed for]`' };
      }
      try {
        const safe = payload.trim().slice(0, 500);
        const result = await context.aiEngine.chat(
          [{ role: 'user', content: 'Create a 5-email welcome sequence for new subscribers who downloaded: ' + safe + '\n\nFor EACH email: timing, subject line (<50 chars), preview text, full body (150-250 words), CTA, goal.\n\nEmail 1 (immediate): welcome + deliver content\nEmail 2 (day 2): quick win tip\nEmail 3 (day 4): education + Dr Piet story\nEmail 4 (day 7): social proof + soft offer\nEmail 5 (day 10): consultation/membership invitation\n\nTone: warm, professional, South African. Health disclaimer on health emails.' }],
          { systemPrompt: context.soulFile + '\n\nPatient-nurturing email sequence. Value-first. Never pushy.', temperature: 0.6 }
        );
        logger.info('[FUNNEL] Welcome sequence created');
        return { response: '✉️ *Welcome Email Sequence (5 emails):*\n\n' + result.content };
      } catch (err) {
        logger.error('[FUNNEL] Welcome sequence error:', err.message);
        return { response: `❌ Welcome sequence failed: ${err.message}` };
      }
    }

    if (context.triggerUsed === 'ABANDONED BOOKING:') {
      try {
        const safe = (payload || 'General consultation booking').slice(0, 500);
        const result = await context.aiEngine.chat(
          [{ role: 'user', content: 'Create a 3-message abandoned booking recovery for drpiet.co.za. Context: ' + safe + '\n\nMsg 1 (1hr): short, helpful, address barriers, simple CTA\nMsg 2 (24hr): different angle, add value tip, gentle reminder\nMsg 3 (3 days): final reach-out, no pressure, warm door open\n\nAll under 120 words. South African context.' }],
          { systemPrompt: context.soulFile + '\n\nWarm and helpful — never pushy. Patient wellbeing first.', temperature: 0.5 }
        );
        return { response: '📱 *Abandoned Booking Recovery:*\n\n' + result.content };
      } catch (err) {
        logger.error('[FUNNEL] Abandoned booking error:', err.message);
        return { response: `❌ Abandoned booking sequence failed: ${err.message}` };
      }
    }

    if (context.triggerUsed === 'PATIENT FUNNEL:') {
      try {
        const safe = (payload || 'drpiet.co.za health and wellness platform').slice(0, 500);
        const result = await context.aiEngine.chat(
          [{ role: 'user', content: 'Design a complete patient acquisition funnel for: ' + safe + '\n\nMap: 1) AWARENESS — discovery channels, content\n2) INTEREST — lead magnet, email nurture\n3) CONSIDERATION — social proof, objections\n4) DECISION — offer, risk reversal\n5) RETENTION — membership, referrals\n\nFor each stage: specific content, offers, and Serena tasks. South African context.' }],
          { systemPrompt: context.soulFile + '\n\nHealthcare patient acquisition funnel. Balance commercial goals with genuine care.', temperature: 0.5 }
        );
        return { response: '🔄 *Patient Funnel Strategy:*\n\n' + result.content };
      } catch (err) {
        logger.error('[FUNNEL] Patient funnel error:', err.message);
        return { response: `❌ Patient funnel failed: ${err.message}` };
      }
    }

    if (context.triggerUsed === 'RE-ENGAGE:') {
      if (!payload || payload.trim().length < 3) {
        return { response: '⚠️ Usage: `RE-ENGAGE: [audience description]`\nExample: `RE-ENGAGE: Patients who haven\'t booked in 6 months`' };
      }
      try {
        const safe = payload.trim().slice(0, 500);
        const result = await context.aiEngine.chat(
          [{ role: 'user', content: 'Create a re-engagement campaign for: ' + safe + '\n\n1. Email subject line\n2. Re-engagement email (under 150 words)\n3. Telegram message (under 80 words)\n4. Offer/value to include\n5. Sunset plan if no response' }],
          { systemPrompt: context.soulFile, temperature: 0.6 }
        );
        return { response: '📲 *Re-Engagement Campaign:*\n\n' + result.content };
      } catch (err) {
        logger.error('[FUNNEL] Re-engage error:', err.message);
        return { response: `❌ Re-engagement failed: ${err.message}` };
      }
    }

    return { response: '⚠️ Available commands:\n• `LEAD MAGNET: [topic]`\n• `WELCOME SEQUENCE: [subscription topic]`\n• `ABANDONED BOOKING: [context]`\n• `PATIENT FUNNEL: [platform]`\n• `RE-ENGAGE: [audience]`' };
  }
};
