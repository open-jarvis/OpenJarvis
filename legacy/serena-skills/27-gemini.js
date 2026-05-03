// 27-gemini.js — Google Gemini Deep Analyser (Stable Production Version)

const logger = require('../helpers/logger');

let fetchFn;
try {
  fetchFn = global.fetch ? global.fetch : require('node-fetch');
} catch (err) {
  logger.error('[GEMINI] Failed to load fetch:', err);
}

// Stable endpoint - using v1beta and reliable model
const GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent';

const ENABLE_FALLBACK = true;   // Keep fallback enabled

async function fetchWithTimeout(url, options = {}, timeout = 45000) {
  return Promise.race([
    fetchFn(url, options),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('Gemini request timed out')), timeout)
    )
  ]);
}

async function callGemini(prompt, systemPrompt = '') {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error('GEMINI_API_KEY is missing from .env');

  const body = {
    contents: [{ role: 'user', parts: [{ text: `${systemPrompt}\n\n${prompt}` }] }],
    generationConfig: { temperature: 0.4, topP: 0.9, maxOutputTokens: 8192 }
  };

  const res = await fetchWithTimeout(`${GEMINI_URL}?key=${apiKey}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, 45000);

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Gemini API error ${res.status}: ${errorText}`);
  }

  const data = await res.json();
  const output = data?.candidates?.[0]?.content?.parts?.[0]?.text ||
                 data?.candidates?.[0]?.content?.parts?.map(p => p.text).join(' ');

  if (!output) throw new Error('Gemini returned empty response');
  return output.trim();
}

module.exports = {
  id: '27-gemini',
  name: 'Gemini Deep Analyser',
  description: 'Advanced AI analysis using Google Gemini for strategic and medical reasoning.',

  triggers: ['DEEP ANALYSIS:', 'GEMINI ANALYSE:', 'GEMINI:', 'STRATEGY:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[GEMINI] Triggered: ${context.triggerUsed}`);

      if (!payload || payload.trim().length < 5) {
        return { response: '🧠 Use `DEEP ANALYSIS: your question` for detailed strategic/medical insights.' };
      }

      const systemContext = `You are a high-level strategic and medical analyst for Dr Piet Muller, a South African GP. Provide structured, actionable insights aligned with SA healthcare and HPCSA rules.`;

      const answer = await callGemini(payload.trim().slice(0, 12000), systemContext);

      return {
        response: `🧠 *Gemini Deep Analysis*\n\n${answer}\n\n_Powered by Google Gemini_`
      };

    } catch (err) {
      logger.error('[GEMINI] Error:', err.message);

      if (context.aiEngine && ENABLE_FALLBACK) {
        try {
          const fallback = await context.aiEngine.chat(
            [{ role: 'user', content: payload }],
            { systemPrompt: context.soulFile || '', temperature: 0.4 }
          );
          return {
            response: `⚠️ Gemini unavailable — using primary AI (Groq):\n\n${fallback.content}`
          };
        } catch (fbErr) {
          logger.error('[GEMINI] Fallback failed:', fbErr);
        }
      }

      return { response: `❌ Gemini unavailable: ${err.message}\n\nGroq fallback also failed.` };
    }
  }
};