// 60-browser.js — Browser Automation (MCP Playwright)
// Gives Serena a full headless browser via the Playwright MCP server.
// Use cases: book SA appointments, screenshot websites, scrape content,
// fill forms, interact with portals that have no API.
//
// REQUIRES: MCP_PLAYWRIGHT_ENABLED=true in .env
// The playwright MCP server is connected at startup via mcp-manager.js

const logger = require('../helpers/logger');

module.exports = {
  id: '60-browser',
  name: 'Browser Automation',
  description: 'Headless browser — screenshot, scrape, and interact with any website.',
  triggers: ['SCREENSHOT:', 'BROWSE:', 'SCRAPE PAGE:', 'FILL FORM:', 'BROWSER:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[BROWSER] Triggered: ${context.triggerUsed} | ${(payload || '').substring(0, 60)}`);

      const mcpClient = context.mcpClient;

      if (!mcpClient) {
        return { response: '⚠️ MCP layer not initialised. Restart the bot with MCP enabled.' };
      }

      const puppeteerTools = mcpClient.getToolsForServer('puppeteer');
      const playwrightTools = mcpClient.getToolsForServer('playwright');
      const tools = puppeteerTools && puppeteerTools.length ? puppeteerTools : playwrightTools;
      const prefix = puppeteerTools && puppeteerTools.length ? 'puppeteer' : 'playwright';

      if (!tools || tools.length === 0) {
        return {
          response:
            '⚠️ *Browser MCP server not connected*\n\n' +
            'Add to .env:\n' +
            '`MCP_PUPPETEER_ENABLED=true`\n\n' +
            'Then restart Serena.'
        };
      }

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '🌐 *Browser Automation*\n\n' +
            'Commands:\n' +
            '• `SCREENSHOT: https://drpiet.co.za` — capture full-page screenshot\n' +
            '• `SCRAPE PAGE: https://url.com | extract all pricing info` — scrape + summarise\n' +
            '• `BROWSE: https://url.com` — navigate and return page content\n\n' +
            '⚡ Powered by Serena browser MCP'
        };
      }

      const parts = payload.split('|').map(p => p.trim());
      const url   = parts[0];
      const task  = parts[1] || '';

      if (!url.startsWith('http')) {
        return { response: '⚠️ Please provide a full URL starting with https://' };
      }

      // ── SCREENSHOT ───────────────────────────────────────────
      if (context.triggerUsed === 'SCREENSHOT:') {
        // Navigate + screenshot
        await mcpClient.callTool(`${prefix}_navigate`, { url });
        const screenshotResult = await mcpClient.callToolRaw(`${prefix}_screenshot`, {
          name:     `screenshot_${Date.now()}`,
          fullPage: true,
          encoded: false
        });

        const imageContent = screenshotResult.content && screenshotResult.content.find(c => c.type === 'image');
        if (imageContent) {
          // Save to temp as PNG and send via Telegram
          const fs   = require('fs');
          const path = require('path');
          const buf  = Buffer.from(imageContent.data, 'base64');
          const fp   = path.join('./temp', `screenshot_${Date.now()}.png`);
          fs.writeFileSync(fp, buf);

          logger.info(`[BROWSER] Screenshot saved: ${fp}`);
          return {
            response:  `📸 *Screenshot — ${url}*`,
            imageFile: fp,
            cleanup:   true
          };
        }

        return { response: '⚠️ Screenshot captured but no image data returned.' };
      }

      // ── SCRAPE PAGE ──────────────────────────────────────────
      if (context.triggerUsed === 'SCRAPE PAGE:' || context.triggerUsed === 'BROWSE:') {
        await mcpClient.callTool(`${prefix}_navigate`, { url });

        const contentResult = await mcpClient.callTool(`${prefix}_evaluate`, {
          script: 'document.body ? document.body.innerText : ""'
        });
        const rawText = String(contentResult || '').substring(0, 6000);

        if (!rawText || rawText.length < 50) {
          return { response: `⚠️ Page content too short or blocked. URL: ${url}` };
        }

        if (!task && !context.aiEngine) {
          return { response: `📄 *Page Content (${url})*\n\n${rawText.substring(0, 3000)}` };
        }

        // AI summarise with specific task
        const prompt = task
          ? `${task}\n\nPage content from ${url}:\n\n${rawText}`
          : `Summarise the key content from ${url}. Extract main points, pricing, and actionable info:\n\n${rawText}`;

        const aiResult = await context.aiEngine.chat(
          [{ role: 'user', content: prompt }],
          { systemPrompt: context.soulFile, temperature: 0.3 }
        );

        logger.info(`[BROWSER] Scraped and summarised: ${url}`);
        return {
          response:
            `🌐 *Web Scrape — ${url}*\n\n` +
            '━━━━━━━━━━━━━━━━━━\n\n' +
            aiResult.content +
            '\n\n━━━━━━━━━━━━━━━━━━'
        };
      }

      return { response: '⚠️ Usage: `SCREENSHOT: url`, `SCRAPE PAGE: url | task`, `BROWSE: url`' };

    } catch (err) {
      logger.error('[BROWSER] Error:', err.message);
      return { response: `❌ Browser automation error: ${err.message}` };
    }
  }
};
