// 38-summarise.js — Research & URL Summariser
// Fetches URLs and summarises content via AI.
// Also summarises pasted text directly.

const logger = require('../helpers/logger');

async function fetchPageText(url) {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Serena-Agent/1.0)' },
    signal:  AbortSignal.timeout(15000)
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  const html = await res.text();

  // Strip HTML tags and collapse whitespace
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 8000);
}

module.exports = {
  id: '38-summarise',
  name: 'Research Summariser',
  description: 'Summarise URLs, research articles, or pasted text. Extracts key insights.',
  triggers: ['SUMMARISE:', 'SUMMARIZE:', 'SUMMARIZE URL:', 'SUMMARISE URL:', 'READ URL:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[SUMMARISE] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,60)}`);

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '📖 *Research Summariser*\n\n' +
            'Usage:\n' +
            '• `SUMMARISE: https://pubmed.ncbi.nlm.nih.gov/...` — summarise a URL\n' +
            '• `SUMMARISE: [paste long text here]` — summarise pasted content\n' +
            '• `SUMMARISE: https://example.com | clinical` — clinical-angle summary\n\n' +
            'Summary styles: general, clinical, business, patient-friendly, social'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts  = payload.split('|').map(p => p.trim());
      const input  = parts[0];
      const style  = parts[1] || 'general';

      let contentToSummarise = input;
      let sourceLabel        = 'Pasted text';
      let isUrl              = false;

      // Detect URL
      if (input.startsWith('http://') || input.startsWith('https://')) {
        isUrl = true;
        sourceLabel = input;
        try {
          await context.bot?.sendChatAction?.(context.chatId, 'typing');
          contentToSummarise = await fetchPageText(input);
          if (contentToSummarise.length < 100) {
            return { response: '⚠️ Page content too short or could not be fetched. Try pasting the text directly.' };
          }
        } catch (fetchErr) {
          return { response: `❌ Could not fetch URL: ${fetchErr.message}\n\nTry pasting the article text directly.` };
        }
      }

      const styleInstructions = {
        general:          'Provide a clear, balanced summary with key points.',
        clinical:         'Focus on clinical implications, study design, patient population, outcomes, and limitations.',
        business:         'Focus on business implications, market insights, revenue impact, and strategic opportunities.',
        'patient-friendly': 'Explain in simple language a patient can understand. Avoid jargon. Include what it means for their health.',
        social:           'Create a 3-sentence social media summary with a hook and a key insight. End with a question for engagement.'
      };

      const instruction = styleInstructions[style] || styleInstructions.general;

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Summarise the following content for a South African medical practice context.\n\n` +
            `Style: ${style.toUpperCase()} — ${instruction}\n\n` +
            `CONTENT:\n${contentToSummarise}\n\n` +
            `Format:\n` +
            `🎯 MAIN POINT: One sentence\n` +
            `📋 KEY INSIGHTS: 4-6 bullet points\n` +
            `💡 RELEVANCE TO DR PIET: Why this matters for the practice\n` +
            `⚕️ DISCLAIMER: Any health/data caveats\n\n` +
            `Be concise and South African context-aware.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.3 }
      );

      logger.info(`[SUMMARISE] Summary complete (${style}) for: ${sourceLabel.substring(0, 50)}`);
      return {
        response:
          `📖 *Summary — ${style.charAt(0).toUpperCase() + style.slice(1)}*\n` +
          (isUrl ? `🔗 _Source: ${input.substring(0, 80)}_\n` : '') +
          '\n━━━━━━━━━━━━━━━━━━\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Other styles: `SUMMARISE: [content] | clinical` / `| patient-friendly` / `| social`'
      };

    } catch (err) {
      logger.error('[SUMMARISE] Error:', err.message);
      return { response: `❌ Summariser error: ${err.message}` };
    }
  }
};
