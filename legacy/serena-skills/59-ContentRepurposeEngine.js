// 59-ContentRepurposeEngine.js — Content Repurpose Engine
// Transforms a single piece of content into multiple derivative formats.
// Uses AI engine directly — no external rewrite API needed.
// DEFERRED: Direct posting to platforms (use 13-wordpress + 05-social for distribution)

const logger = require('../helpers/logger');

module.exports = {
  id: '59-ContentRepurposeEngine',
  name: 'Content Repurpose Engine',
  description: 'Transform one piece of content into blog posts, social captions, newsletter sections, and more.',
  triggers: ['REPURPOSE:', 'CONTENT VARIANTS:', 'REPURPOSE CONTENT:'],

  execute: async function (payload, context) {
    try {
      if (!payload || payload.trim().length < 10) {
        return {
          response:
            '♻️ *Content Repurpose Engine*\n\n' +
            'Usage: `REPURPOSE: [your source content or topic]`\n\n' +
            'Example: `REPURPOSE: Dr Piet\'s podcast episode on managing diabetes through diet`\n\n' +
            'Generates: blog post, 5 social captions, newsletter section, email subject lines.'
        };
      }

      if (!context.aiEngine) {
        return { response: '⚠️ AI engine not available.' };
      }

      // FIX: sourceContent and targetPlatforms now from payload, not undeclared vars
      const sourceContent = payload.trim().slice(0, 3000);

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            'Repurpose this content for multiple formats. Source:\n\n"' + sourceContent + '"\n\n' +
            'Generate ALL of the following:\n\n' +
            '1. BLOG POST (600-800 words, SEO-optimised, HTML headings, health disclaimer)\n\n' +
            '2. SOCIAL MEDIA CAPTIONS (5 captions for different angles)\n' +
            '   - LinkedIn: Professional, thought-leadership\n' +
            '   - Instagram: Warm, visual storytelling\n' +
            '   - Facebook: Community-focused, shareable\n' +
            '   - Twitter/X: Concise insight + hook\n' +
            '   - General: Evergreen\n\n' +
            '3. NEWSLETTER SECTION (150 words, fits into a weekly health digest)\n\n' +
            '4. EMAIL SUBJECT LINES (5 variations for split testing)\n\n' +
            '5. PODCAST INTRO HOOK (30 seconds spoken, attention-grabbing)\n\n' +
            'All content: South African context, warm professional medical tone, compliance-safe.'
        }],
        {
          systemPrompt: context.soulFile + '\n\nContent repurposing expert for a South African medical practice. All content must be HPCSA compliant and educational.',
          temperature: 0.65
        }
      );

      logger.info('[REPURPOSE] Content variants generated for: ' + sourceContent.substring(0, 50));
      return {
        response:
          '♻️ *Content Variants Generated*\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Next steps:\n' +
          '• `WP DRAFT: [title] | [blog content]` — publish to WordPress\n' +
          '• `EMAIL DRAFT: [subject] | [audience] | [newsletter content]` — send via email'
      };
    } catch (err) {
      logger.error('[REPURPOSE] Error:', err.message);
      return { response: `❌ Content repurpose error: ${err.message}` };
    }
  }
};
