
const logger = require('../helpers/logger');
const wordpress = require('../helpers/wordpress');
const { syncContentArtifact } = require('../helpers/github-content-sync');

function wantsPublish(parts) {
  return parts.some((p) => String(p || '').trim().toLowerCase() === 'publish');
}

module.exports = {
  id: '18-blog',
  name: 'SEO Blog Writer',
  description: 'Write long-form SEO-optimised articles for drpiet.co.za and optionally publish as draft.',
  triggers: ['BLOG POST:', 'SEO ARTICLE:', 'WRITE BLOG:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[BLOG] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,50)}`);

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            'SEO Blog Writer\n\n' +
            'Usage: `BLOG POST: topic | keyword | word count`\n\n' +
            'Examples:\n' +
            '• `BLOG POST: Managing hypertension in South Africa`\n' +
            '• `BLOG POST: diabetes diet tips | blood sugar management | 1000`\n\n' +
            'Add `| publish` at the end to auto-save as WordPress draft.'
        };
      }

      if (!context.aiEngine) return { response: 'AI engine unavailable.' };

      const parts = payload.split('|').map(p => p.trim()).filter(Boolean);
      const topic = parts[0];
      const keyword = parts[1] || topic;
      const wordCount = parseInt(parts[2], 10) || 800;
      const publish = wantsPublish(parts);

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `Write a complete, full-length SEO-optimised blog post for drpiet.co.za.\n\n` +
            `Topic: "${topic}"\n` +
            `Primary keyword: "${keyword}"\n` +
            `Target length: ~${wordCount} words. Write the entire article in one go.\n\n` +
            `Must include:\n` +
            `- SEO Title\n- Meta Description\n- Engaging introduction\n- 5-7 detailed H2 sections\n- FAQ section\n- Strong conclusion with CTA\n- Health disclaimer\n\n` +
            `Output format: Clean HTML only.`
        }],
        { systemPrompt: context.soulFile, temperature: 0.65, maxTokens: 2200, task: 'blog-post' }
      );

      const content = String(result.content || '').trim();
      const titleMatch = content.match(/SEO[- ]?[Tt]itle[:\s]*(.+?)(?=\n|$)/i);
      const wpTitle = titleMatch ? titleMatch[1].trim() : topic;

      const sync = await syncContentArtifact(context, {
        skillId: '18-blog',
        title: wpTitle,
        type: 'blog-post',
        summary: topic,
        content,
        tags: [keyword]
      }).catch(() => null);

      if (publish && typeof wordpress.isWordPressConfigured === 'function' && wordpress.isWordPressConfigured()) {
        const created = await wordpress.createWordPressContent('posts', {
          title: wpTitle,
          content,
          status: 'draft',
          slug: wpTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
        }, {});
        return {
          response:
            `Blog post written and saved as WordPress draft\n\nTitle: ${wpTitle}\nID: ${created.id}` +
            (created.link ? `\nLink: ${created.link}` : '') +
            (sync ? `\nGitHub artifact folder: ${sync.paths.folder}` : '')
        };
      }

      return {
        response:
          `SEO Blog Post\n${topic}\n\n` +
          content +
          (sync ? `\n\nGitHub artifact folder: ${sync.paths.folder}` : '') +
          `\n\nTo save as WordPress draft: \`BLOG POST: ${topic} | ${keyword} | ${wordCount} | publish\``
      };

    } catch (err) {
      logger.error('[BLOG] Error: ' + err.message);
      return { response: `Blog writer error: ${err.message}` };
    }
  }
};
