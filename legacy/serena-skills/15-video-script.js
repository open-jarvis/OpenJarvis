// 15-video-script.js — Video Script Generator
// Generates platform-specific short-form video scripts via AI.
// Supports: Instagram Reels, YouTube Shorts, TikTok, LinkedIn Video

const logger = require('../helpers/logger');

module.exports = {
  id: '15-video-script',
  name: 'Video Script Generator',
  description: 'Generate Instagram Reel, YouTube Short, and TikTok scripts for Dr Piet.',
  triggers: ['VIDEO SCRIPT:', 'REEL SCRIPT:', 'TIKTOK SCRIPT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[VIDEO-SCRIPT] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🎬 *Video Script Generator*\n\n' +
            'Usage: `VIDEO SCRIPT: topic | platform | duration`\n\n' +
            '*Platforms:* reel, short, tiktok, linkedin\n' +
            '*Durations:* 15s, 30s, 60s, 90s\n\n' +
            'Example: `VIDEO SCRIPT: Managing diabetes through diet | reel | 60s`\n\n' +
            'Or simply: `VIDEO SCRIPT: 5 signs your blood pressure is too high`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts    = payload.split('|').map(p => p.trim());
      const topic    = parts[0];
      const platform = (parts[1] || 'reel').toLowerCase();
      const duration = parts[2] || '60s';

      const platformGuide = {
        reel:     'Instagram Reel — hook in first 2 seconds, trending audio cue, text overlay notes, CTA to bio link',
        short:    'YouTube Short — searchable title, strong hook, value delivery, subscribe CTA',
        tiktok:   'TikTok — hook question, storytelling arc, trend reference, Stitch/Duet friendly ending',
        linkedin: 'LinkedIn Video — professional insight, credibility statement, thought-leadership angle, connection CTA'
      };

      const guide = platformGuide[platform] || platformGuide.reel;

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Write a complete ${duration} ${platform} video script for Dr Piet Muller, South African medical doctor.\n\n` +
            `Topic: "${topic}"\n\n` +
            `Platform requirements: ${guide}\n\n` +
            `Script format:\n` +
            `[HOOK — 0-3s]: Opening line spoken to camera\n` +
            `[SETUP — 3-10s]: Context / why this matters\n` +
            `[BODY — 10-45s]: Main content (3 key points with B-roll notes in brackets)\n` +
            `[CTA — last 5s]: Call to action\n\n` +
            `Also provide:\n` +
            `CAPTION: Ready-to-paste social media caption with hashtags\n` +
            `THUMBNAIL TEXT: 5-word on-screen text for thumbnail\n` +
            `AUDIO SUGGESTION: Trending sound style or music mood\n\n` +
            `Tone: Warm, educational, South African. Include a health disclaimer note at the end.\n` +
            `Duration target: ${duration}`
        }],
        { systemPrompt: context.soulFile, temperature: 0.65 }
      );

      logger.info(`[VIDEO-SCRIPT] Script generated for: ${topic.substring(0, 50)}`);
      return {
        response:
          `🎬 *${platform.charAt(0).toUpperCase() + platform.slice(1)} Script — ${duration}*\n` +
          `📌 _${topic}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Next: `VIDEO: [scene description]` to generate a preview visual\n' +
          '📝 Or: `REPURPOSE: [paste script]` to create blog + social variants'
      };

    } catch (err) {
      logger.error('[VIDEO-SCRIPT] Error:', err.message);
      return { response: `❌ Video script error: ${err.message}` };
    }
  }
};
