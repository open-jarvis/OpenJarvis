// 05-social.js — Social Media Content Engine
// Generates platform-specific social content via AI.
// Posting APIs (Buffer/Hootsuite) deferred — content generation is fully live.

const logger = require('../helpers/logger');

module.exports = {
  id: '05-social',
  name: 'Social Media Content Engine',
  description: 'Generate platform-specific social media posts for Dr Piet — Instagram, LinkedIn, Facebook, Twitter/X.',
  triggers: ['SOCIAL POST:', 'SOCIAL DRAFT:', 'INSTAGRAM POST:', 'LINKEDIN POST:', 'FACEBOOK POST:', 'TWITTER POST:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[SOCIAL] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '📱 *Social Media Content Engine*\n\n' +
            'Usage: `SOCIAL POST: topic | platform | tone`\n\n' +
            '*Platform shortcuts:*\n' +
            '• `INSTAGRAM POST: topic` — Reel caption + hashtags\n' +
            '• `LINKEDIN POST: topic` — Professional thought leadership\n' +
            '• `FACEBOOK POST: topic` — Community-focused post\n' +
            '• `TWITTER POST: topic` — 280-char thread\n' +
            '• `SOCIAL POST: topic | all` — All 4 platforms at once\n\n' +
            'Example: `SOCIAL POST: 5 signs of high blood pressure | instagram | educational`'
        };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      const parts   = payload.split('|').map(p => p.trim());
      const topic   = parts[0];
      const tone    = parts[2] || 'educational and warm';

      // Determine which platforms from trigger or explicit param
      let platforms = [];
      const platformParam = (parts[1] || '').toLowerCase();

      if (context.triggerUsed === 'INSTAGRAM POST:') platforms = ['instagram'];
      else if (context.triggerUsed === 'LINKEDIN POST:')  platforms = ['linkedin'];
      else if (context.triggerUsed === 'FACEBOOK POST:')  platforms = ['facebook'];
      else if (context.triggerUsed === 'TWITTER POST:')   platforms = ['twitter'];
      else if (platformParam === 'all' || platformParam === '')
        platforms = ['instagram', 'linkedin', 'facebook', 'twitter'];
      else platforms = [platformParam];

      const platformInstructions = {
        instagram:
          'Instagram caption (max 2,200 chars). Hook line, 3-4 sentences of value, CTA to bio link. ' +
          '30 relevant hashtags on a new line. Include 3 emoji. Suggest reel concept in [brackets].',
        linkedin:
          'LinkedIn post (max 1,300 chars). Professional hook, insight sharing, thought leadership angle. ' +
          'No hashtag spam — max 5 relevant hashtags. End with a question to drive comments.',
        facebook:
          'Facebook post (max 500 chars). Community-focused, shareable, warm tone. ' +
          'Include a question or poll suggestion. 5-10 relevant hashtags.',
        twitter:
          'Twitter/X thread. Tweet 1 (hook, 280 chars max), Tweets 2-4 (key points, 280 chars each), ' +
          'Tweet 5 (CTA). Each tweet on a new line prefixed with 1/, 2/, etc.'
      };

      const allContent = [];

      for (const platform of platforms) {
        const instruction = platformInstructions[platform] || platformInstructions.instagram;

        const result = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Create a ${platform} post for Dr Piet Muller, South African GP and wellness doctor at drpiet.co.za.\n\n` +
              `Topic: "${topic}"\n` +
              `Tone: ${tone}\n\n` +
              `Format requirements: ${instruction}\n\n` +
              `Important: South African context, HPCSA-compliant (no cure claims, include health disclaimer if medical advice), warm and educational.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.7 }
        );

        allContent.push(`*${platform.charAt(0).toUpperCase() + platform.slice(1)}:*\n${result.content}`);
      }

      logger.info(`[SOCIAL] Generated ${platforms.length} post(s) for: ${topic.substring(0,50)}`);
      return {
        response:
          `📱 *Social Media Content*\n📌 _${topic}_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          allContent.join('\n\n━━━━━━━━━━━━━━━━━━\n\n') +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Tip: `VIDEO SCRIPT: ' + topic + '` to create matching video content'
      };

    } catch (err) {
      logger.error('[SOCIAL] Error:', err.message);
      return { response: `❌ Social content error: ${err.message}` };
    }
  }
};
