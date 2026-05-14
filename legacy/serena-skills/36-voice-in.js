
const logger = require('../helpers/logger');
const fs = require('fs');
const voiceOrchestrator = require('../voice/voice-orchestrator');

module.exports = {
  id: '36-voice-in',
  name: 'Voice Transcription',
  description: 'Transcribe voice notes through Serena’s shared speech-to-text runtime. Auto-transcription remains active for Telegram voice notes.',
  triggers: ['TRANSCRIBE:', 'VOICE NOTE:', 'VOICE STATUS'],

  execute: async function (payload, context) {
    try {
      logger.info(`[VOICE-IN] Triggered: ${context.triggerUsed}`);
      const status = voiceOrchestrator.getStatus();

      if (context.triggerUsed === 'VOICE STATUS') {
        return {
          response:
            '🎤 *Voice Runtime Status*\n\n' +
            `STT configured: ${status.stt?.configured ? '✅ Yes' : '⚠️ No'}\n` +
            `TTS configured: ${status.tts?.configured ? '✅ Yes' : '⚠️ No'}\n` +
            `Voice profile: ${status.profile?.id || 'serena-default'}\n` +
            `Language: ${status.profile?.languageCode || 'en-ZA'}\n` +
            `Microphone attached: ${status.audioInput?.attached ? '✅ Yes' : '⚠️ Not yet'}\n` +
            `Speakers attached: ${status.audioOutput?.attached ? '✅ Yes' : '⚠️ Not yet'}\n` +
            `Voice runtime ready: ${status.runtimeReady ? '✅ Yes' : '⚠️ No'}\n` +
            `Active sessions: ${status.sessions?.activeSessions || 0}\n\n` +
            'Telegram voice-note transcription remains active. Hardware microphone/speaker mode can be attached later without changing Serena’s cognition layer.'
        };
      }

      if (!status.stt?.configured) {
        return {
          response:
            '⚠️ *Voice transcription not configured*\n\n' +
            'Add `HUGGINGFACE_API_KEY=hf_...` to your .env file.\n\n' +
            'Telegram auto-transcription and future microphone mode both use this shared STT adapter.'
        };
      }

      if (payload && payload.trim().length > 3) {
        const filePath = payload.trim();
        if (!fs.existsSync(filePath)) {
          return { response: `❌ File not found: ${filePath}` };
        }

        const result = await voiceOrchestrator.transcribeFile(filePath, { mimeType: 'audio/ogg' });
        return {
          response:
            '🎤 *Manual transcription complete*\n\n' +
            `"${String(result.text || '').trim()}"`
        };
      }

      return {
        response:
          '🎤 Serena is ready to transcribe Telegram voice notes now.\n\n' +
          'Later, the same shared STT runtime will be used for live microphone mode.'
      };
    } catch (err) {
      logger.error('[VOICE-IN] Error: ' + err.message);
      return { response: `❌ Voice transcription failed: ${err.message}` };
    }
  }
};
