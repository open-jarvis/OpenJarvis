const fs = require('fs');
const path = require('path');
const logger = require('../helpers/logger');

const OUTPUT_DIR = path.join(__dirname, '../../outputs/video-edit');

function ensureOutputDir() {
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }
}

function toSrt(text) {
  const lines = String(text || '').split(/\n+/).map((line) => line.trim()).filter(Boolean);
  return lines.map((line, index) => {
    const start = index * 4;
    const end = start + 4;
    const stamp = (seconds) => {
      const hrs = String(Math.floor(seconds / 3600)).padStart(2, '0');
      const mins = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
      const secs = String(seconds % 60).padStart(2, '0');
      return `${hrs}:${mins}:${secs},000`;
    };
    return `${index + 1}\n${stamp(start)} --> ${stamp(end)}\n${line}\n`;
  }).join('\n');
}

module.exports = {
  id: '54-video-edit',
  name: 'Video Editor',
  description: 'Create edit briefs and caption files for videos so Serena can support a real post-production workflow.',
  triggers: ['EDIT VIDEO:', 'AUTO CAPTION:'],

  execute: async function (payload, context) {
    try {
      ensureOutputDir();
      const brief = String(payload || '').trim();
      if (!brief) {
        return {
          response:
            '⚠️ Usage:\n' +
            '`EDIT VIDEO: describe the edits needed`\n' +
            '`AUTO CAPTION: paste the transcript text to convert into captions`'
        };
      }

      if (context.triggerUsed === 'AUTO CAPTION:') {
        const srt = toSrt(brief);
        const filePath = path.join(OUTPUT_DIR, `captions-${Date.now()}.srt`);
        fs.writeFileSync(filePath, srt, 'utf8');
        return {
          response: '✅ *Caption file created*',
          documentFile: filePath,
          documentMimeType: 'application/x-subrip'
        };
      }

      const result = await context.aiEngine.chat(
        [{ role: 'user', content: brief }],
        {
          systemPrompt:
            `${context.soulFile}\n\n` +
            'You are Serena\'s video post-production assistant. ' +
            'Create a practical edit brief with timeline guidance, shot order, pacing, captions, and delivery notes.',
          temperature: 0.4,
          maxTokens: 1400,
          task: 'video-edit-brief'
        }
      );

      const filePath = path.join(OUTPUT_DIR, `edit-brief-${Date.now()}.md`);
      fs.writeFileSync(filePath, String(result.content || '').trim(), 'utf8');

      return {
        response: '✅ *Video edit brief created*',
        documentFile: filePath,
        documentMimeType: 'text/markdown'
      };
    } catch (error) {
      logger.error('[VIDEO-EDIT] Error: ' + error.message);
      return { response: `❌ Video editor error: ${error.message}` };
    }
  }
};
