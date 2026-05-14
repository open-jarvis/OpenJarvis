// 51-ai-teacher.js — AI Teacher & Patient Educator
// Creates structured lessons, quizzes, and educational content.
// Perfect for patient education, corporate wellness talks, and staff training.

const logger = require('../helpers/logger');

module.exports = {
  id: '51-ai-teacher',
  name: 'AI Teacher & Patient Educator',
  description: 'Create lessons, quizzes, and educational content for patients and corporate wellness.',
  triggers: ['CREATE LESSON:', 'QUIZ:', 'PATIENT EDUCATION:', 'TEACH TOPIC:', 'HEALTH QUIZ:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[AI-TEACHER] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🎓 *AI Teacher & Patient Educator*\n\n' +
            'Commands:\n' +
            '• `CREATE LESSON: topic | audience | duration` — structured lesson plan\n' +
            '• `PATIENT EDUCATION: condition` — patient-friendly condition explainer\n' +
            '• `QUIZ: topic | 5 questions` — multiple choice quiz\n' +
            '• `HEALTH QUIZ: topic` — 5-question patient health assessment\n' +
            '• `TEACH TOPIC: topic | level` — deep educational explainer\n\n' +
            'Audience levels: patient, corporate, medical-student, child, elderly\n\n' +
            'Examples:\n' +
            '• `PATIENT EDUCATION: type 2 diabetes`\n' +
            '• `QUIZ: hypertension | 5 questions`\n' +
            '• `CREATE LESSON: stress management | corporate | 45 minutes`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts    = payload.split('|').map(p => p.trim());
      const topic    = parts[0];
      const audience = parts[1] || 'patient';
      const param3   = parts[2] || '';

      // ── QUIZ ──────────────────────────────────────────────────────
      if (context.triggerUsed === 'QUIZ:' || context.triggerUsed === 'HEALTH QUIZ:') {
        const questionCount = parseInt(audience) || 5;
        const quizAudience  = isNaN(parseInt(audience)) ? audience : 'patient';

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a ${questionCount}-question multiple choice quiz on "${topic}" for ${quizAudience}s.\n\n` +
              `For each question:\n` +
              `Q[N]: [Question text]\n` +
              `A) [Option]\nB) [Option]\nC) [Option]\nD) [Option]\n` +
              `✅ Correct: [Letter] — [Brief explanation]\n\n` +
              `Make questions practical and relevant to South African health context.\n` +
              `Include a health disclaimer at the end.\n` +
              `Difficulty: appropriate for ${quizAudience} level.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.5 }
        );

        logger.info(`[AI-TEACHER] Quiz created: ${topic}`);
        return {
          response:
            `🧠 *Health Quiz — ${topic}*\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            '_Disclaimer: This quiz is for educational purposes only._'
        };
      }

      // ── PATIENT EDUCATION ─────────────────────────────────────────
      if (context.triggerUsed === 'PATIENT EDUCATION:') {
        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a comprehensive patient education resource about "${topic}" for Dr Piet Muller's patients.\n\n` +
              `Structure:\n` +
              `🔍 WHAT IS IT? Simple explanation (no jargon)\n` +
              `📊 HOW COMMON IS IT IN SOUTH AFRICA? Relevant statistics\n` +
              `⚠️ WARNING SIGNS: When to see a doctor immediately\n` +
              `🩺 HOW IS IT DIAGNOSED? What to expect at the doctor\n` +
              `💊 HOW IS IT TREATED? Overview of treatment options\n` +
              `🥗 LIFESTYLE CHANGES: What the patient can do NOW\n` +
              `❓ COMMON QUESTIONS: Top 3 questions patients ask\n` +
              `📞 WHEN TO CALL DR PIET: Specific red flags for this condition\n` +
              `⚕️ DISCLAIMER: Standard health disclaimer\n\n` +
              `Language: Simple, warm, jargon-free. South African context.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.4 }
        );

        logger.info(`[AI-TEACHER] Patient education: ${topic}`);
        return {
          response:
            `📚 *Patient Education — ${topic}*\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Save as lead magnet: \`FREEBIE: Understanding ${topic} | patients | guide\``
        };
      }

      // ── CREATE LESSON ─────────────────────────────────────────────
      if (context.triggerUsed === 'CREATE LESSON:') {
        const duration = param3 || '60 minutes';

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a detailed lesson plan for Dr Piet Muller to teach.\n\n` +
              `Topic: "${topic}"\n` +
              `Audience: ${audience}\n` +
              `Duration: ${duration}\n\n` +
              `Lesson structure:\n` +
              `🎯 LEARNING OBJECTIVES: 3 specific outcomes\n` +
              `📋 MATERIALS NEEDED: List of resources\n` +
              `🕐 TIMING BREAKDOWN:\n` +
              `   [0-5min] Warm-up / icebreaker\n` +
              `   [5-20min] Core concept introduction\n` +
              `   [20-40min] Interactive section / case study\n` +
              `   [40-55min] Practical application / Q&A\n` +
              `   [55-60min] Summary + action steps\n\n` +
              `📝 SPEAKER NOTES: Key talking points per section\n` +
              `🎤 DISCUSSION QUESTIONS: 3 questions for group engagement\n` +
              `📊 ASSESSMENT: How to check if learning occurred\n` +
              `📚 TAKEAWAY RESOURCE: One-page summary for participants\n\n` +
              `South African context. Practical and actionable.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.55 }
        );

        logger.info(`[AI-TEACHER] Lesson plan: ${topic} for ${audience}`);
        return {
          response:
            `🎓 *Lesson Plan — ${topic}*\n` +
            `👥 _Audience: ${audience} | Duration: ${duration}_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━\n' +
            `💡 Create quiz: \`QUIZ: ${topic} | 5 questions\``
        };
      }

      // ── TEACH TOPIC ───────────────────────────────────────────────
      if (context.triggerUsed === 'TEACH TOPIC:') {
        const level  = audience || 'patient';
        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Explain "${topic}" clearly for a ${level}-level audience in South Africa.\n\n` +
              `Include:\n` +
              `- Core concept in simple terms\n` +
              `- Why it matters for health\n` +
              `- 3 key facts\n` +
              `- Common myths and truth\n` +
              `- Practical steps the reader can take\n` +
              `- Health disclaimer\n\n` +
              `Use analogies, examples, and South African cultural context.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.5 }
        );

        logger.info(`[AI-TEACHER] Topic explained: ${topic}`);
        return {
          response:
            `🎓 *${topic}*\n_For: ${level} level_\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            result.content +
            '\n\n━━━━━━━━━━━━━━━━━━'
        };
      }

      return { response: '⚠️ Usage: `CREATE LESSON:`, `PATIENT EDUCATION:`, `QUIZ:`, `TEACH TOPIC:`' };

    } catch (err) {
      logger.error('[AI-TEACHER] Error:', err.message);
      return { response: `❌ AI Teacher error: ${err.message}` };
    }
  }
};
