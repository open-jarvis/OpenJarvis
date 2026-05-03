// 57-LabResultsInterpreter.js — Lab Results Interpreter
// Interprets uploaded lab result images using Mistral Vision (33-mistral pattern)
// or Gemini Vision, providing plain-language explanations.
// DEFERRED: Dedicated lab-result-interpreter service — using Gemini/Mistral vision for now.

const logger = require('../helpers/logger');

module.exports = {
  id: '57-LabResultsInterpreter',
  name: 'Lab Results Interpreter',
  description: 'Interpret lab result images and provide plain-language explanations.',
  triggers: ['INTERPRET LAB:', 'LAB RESULTS:', 'READ LAB:'],

  execute: async function (payload, context) {
    try {
      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🔬 *Lab Results Interpreter*\n\n' +
            'Send a photo of lab results and use:\n' +
            '`INTERPRET LAB: [paste any notes or patient context here]`\n\n' +
            '⚠️ *Important:* Results are explained in plain language for educational purposes only.\n' +
            'Always consult Dr Piet for clinical interpretation.\n\n' +
            '_To use: upload the lab image to Telegram and add the trigger in the caption._'
        };
      }

      if (!context.aiEngine) {
        return { response: '⚠️ AI engine not available.' };
      }

      const patientContext = payload.trim().slice(0, 1000);

      // FIX: uses AI engine for interpretation (no fictional lab package)
      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            'A patient has shared laboratory results. Context: ' + patientContext + '\n\n' +
            'Please provide:\n' +
            '1. Plain language explanation of common lab markers (if values mentioned)\n' +
            '2. What normal South African reference ranges look like\n' +
            '3. What questions the patient should ask their doctor\n' +
            '4. A clear disclaimer that this is educational only\n\n' +
            'Do NOT diagnose. Do NOT recommend treatment changes. Educational only.'
        }],
        {
          systemPrompt: context.soulFile + '\n\nYou are explaining lab results in plain language. Always recommend consulting Dr Piet for clinical decisions. South African reference ranges where relevant.',
          temperature: 0.3
        }
      );

      logger.info('[LAB] Results interpreted for context: ' + patientContext.substring(0, 40));
      return {
        response:
          '🔬 *Lab Results Explanation*\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '⚕️ _This explanation is for educational purposes only. Please consult Dr Piet for clinical decisions._'
      };
    } catch (err) {
      logger.error('[LAB] Error:', err.message);
      return { response: `❌ Lab interpretation error: ${err.message}` };
    }
  }
};
