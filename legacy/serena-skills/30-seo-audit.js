// 30-seo-audit.js — SEO Audit Tool
// Fetches a URL, extracts on-page signals, and runs an AI-powered SEO audit.
// No paid SEO API needed — uses native fetch + AI analysis.

const logger = require('../helpers/logger');

async function fetchPageForSEO(url) {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Serena-SEO/1.0)' },
    signal:  AbortSignal.timeout(15000)
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const html = await res.text();

  // Extract key SEO signals
  const title       = (html.match(/<title[^>]*>(.*?)<\/title>/si) || [])[1] || '';
  const metaDesc    = (html.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)/si) || [])[1] || '';
  const h1Tags      = [...html.matchAll(/<h1[^>]*>(.*?)<\/h1>/gsi)].map(m => m[1].replace(/<[^>]+>/g, '').trim());
  const h2Tags      = [...html.matchAll(/<h2[^>]*>(.*?)<\/h2>/gsi)].map(m => m[1].replace(/<[^>]+>/g, '').trim()).slice(0, 8);
  const imgCount    = (html.match(/<img/gi) || []).length;
  const imgNoAlt    = (html.match(/<img(?![^>]*alt=)[^>]*>/gi) || []).length;
  const wordCount   = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().split(' ').length;
  const canonical   = (html.match(/<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)/si) || [])[1] || '';
  const robotsMeta  = (html.match(/<meta[^>]+name=["']robots["'][^>]+content=["']([^"']+)/si) || [])[1] || 'not set';
  const schemaTypes = [...html.matchAll(/"@type"\s*:\s*"([^"]+)"/g)].map(m => m[1]);
  const internalLinks = (html.match(/href=["']\/[^"']+["']/gi) || []).length;
  const externalLinks = (html.match(/href=["']https?:\/\/[^"']+["']/gi) || []).length;

  return {
    url, title, metaDesc, h1Tags, h2Tags, imgCount, imgNoAlt,
    wordCount, canonical, robotsMeta, schemaTypes, internalLinks, externalLinks
  };
}

module.exports = {
  id: '30-seo-audit',
  name: 'SEO Audit Tool',
  description: 'Audit any URL for on-page SEO signals and get an AI-powered improvement plan.',
  triggers: ['SEO AUDIT:', 'SEO CHECK:', 'AUDIT SITE:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[SEO] Triggered: ${context.triggerUsed} | ${(payload||'').substring(0,60)}`);

      if (!payload || payload.trim().length < 5) {
        return {
          response:
            '🔍 *SEO Audit Tool*\n\n' +
            'Usage: `SEO AUDIT: https://drpiet.co.za/your-page`\n\n' +
            'Analyses:\n' +
            '• Title tag & meta description\n' +
            '• H1/H2 heading structure\n' +
            '• Image alt text coverage\n' +
            '• Word count & content depth\n' +
            '• Schema markup\n' +
            '• Internal/external link count\n' +
            '• Canonical & robots directives\n\n' +
            'Example: `SEO AUDIT: https://drpiet.co.za`'
        };
      }

      const parts    = payload.split('|').map(p => p.trim());
      const url      = parts[0];
      const keyword  = parts[1] || '';

      if (!url.startsWith('http')) {
        return { response: '⚠️ Please provide a full URL starting with https://' };
      }

      if (!context.aiEngine) return { response: '⚠️ AI engine unavailable.' };

      await context.bot?.sendChatAction?.(context.chatId, 'typing');

      let seoData;
      try {
        seoData = await fetchPageForSEO(url);
      } catch (fetchErr) {
        return { response: `❌ Could not fetch URL: ${fetchErr.message}` };
      }

      const dataString = `
URL: ${seoData.url}
Title (${seoData.title.length} chars): "${seoData.title}"
Meta Description (${seoData.metaDesc.length} chars): "${seoData.metaDesc}"
H1 Tags: ${seoData.h1Tags.join(' | ') || 'NONE'}
H2 Tags (first 8): ${seoData.h2Tags.join(' | ') || 'NONE'}
Word Count: ~${seoData.wordCount}
Images: ${seoData.imgCount} total, ${seoData.imgNoAlt} missing alt text
Canonical: ${seoData.canonical || 'not set'}
Robots: ${seoData.robotsMeta}
Schema Types: ${seoData.schemaTypes.join(', ') || 'none found'}
Internal Links: ${seoData.internalLinks}
External Links: ${seoData.externalLinks}
${keyword ? `Target Keyword: "${keyword}"` : ''}
`.trim();

      const result = await context.aiEngine.chat(
        [{
          role: 'user',
          content:
            `You are an expert SEO consultant for South African medical websites. ` +
            `Audit the following on-page SEO data and provide a detailed, actionable report.\n\n` +
            `PAGE DATA:\n${dataString}\n\n` +
            `Provide:\n` +
            `📊 OVERALL SEO SCORE: X/100\n\n` +
            `🔴 CRITICAL ISSUES (fix immediately):\n` +
            `🟡 IMPROVEMENTS NEEDED:\n` +
            `🟢 WHAT'S WORKING:\n\n` +
            `📝 OPTIMISED TITLE TAG: (max 60 chars)\n` +
            `📝 OPTIMISED META DESCRIPTION: (max 155 chars)\n\n` +
            `🚀 TOP 5 QUICK WINS:\n\n` +
            `Consider South African medical SEO, HPCSA compliance, and local search intent.`
        }],
        { systemPrompt: 'Expert SEO consultant for South African healthcare websites.', temperature: 0.3 }
      );

      logger.info(`[SEO] Audit complete for: ${url}`);
      return {
        response:
          `🔍 *SEO Audit — ${url}*\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          result.content +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Next: `BLOG POST: [keyword from audit]` to create optimised content'
      };

    } catch (err) {
      logger.error('[SEO] Error:', err.message);
      return { response: `❌ SEO audit error: ${err.message}` };
    }
  }
};
