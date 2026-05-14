
const logger = require('../helpers/logger');
const voiceOrchestrator = require('../voice/voice-orchestrator');

module.exports = {
  id: '34-voice-out',
  name: 'Voice Output (Google TTS)',
  description: 'Convert text to speech using Serena’s fixed voice identity and send as audio.',
  triggers: ['SPEAK:', 'TTS:', 'READ ALOUD:'],

  execute: async function (payload, context) {
    try {
      const status = voiceOrchestrator.getStatus();

      if (!payload || payload.trim().length < 2) {
        return {
          response:
            '⚠️ Usage: `SPEAK: Your text here`\n\n' +
            'Example: `SPEAK: Good morning Piet. You have three appointments today.`'
        };
      }

      if (!status.tts?.configured) {
        return { response: '⚠️ Google TTS is not configured yet. Add `GOOGLE_TTS_API_KEY` to .env.' };
      }

      const text = payload.trim();
      logger.info(`[VOICE-OUT] Synthesising Serena voice for ${text.substring(0, 60)}...`);

      const result = await voiceOrchestrator.synthesizeReply(text, {
        channel: context?.channel || 'telegram_voice',
        userId: context?.userId || null
      });

      return {
        response:
          '🔊 *Serena voice audio ready*\n\n' +
          `Voice profile: \`${status.profile?.id || 'serena-default'}\`\n` +
          `Language: ${status.profile?.languageCode || 'en-ZA'}\n` +
          `Tone: ${status.profile?.tone || 'calm, confident, warm'}\n\n` +
          `"${result.text}"`,
        audioFile: result.audioFile,
        cleanupMedia: true
      };
    } catch (err) {
      logger.error('[VOICE-OUT] Error: ' + err.message);
      return { response: `❌ Text-to-speech error: ${err.message}` };
    }
  }
};
