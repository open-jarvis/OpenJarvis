// 65-location.js — Location Intelligence (MCP Google Maps)
// SA-specific: find nearby pharmacies, clinics, specialists, distances.
// Supports patient referrals, corporate wellness site visits, competitor mapping.
//
// REQUIRES: GOOGLE_MAPS_API_KEY in .env

const logger = require('../helpers/logger');

module.exports = {
  id: '65-location',
  name: 'Location Intelligence',
  description: 'Find SA clinics, pharmacies, specialists, and calculate distances via Google Maps MCP.',
  triggers: ['FIND NEARBY:', 'DIRECTIONS:', 'LOCATE:', 'MAP SEARCH:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[LOCATION] Triggered: ${context.triggerUsed} | ${(payload || '').substring(0, 60)}`);

      const mcpClient = context.mcpClient;

      if (!mcpClient) return { response: '⚠️ MCP layer not initialised.' };

      const tools = mcpClient.getToolsForServer('google-maps');
      if (!tools || tools.length === 0) {
        return {
          response:
            '⚠️ *Google Maps MCP not connected*\n\n' +
            'Add to .env: `GOOGLE_MAPS_API_KEY=your-key`'
        };
      }

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '📍 *Location Intelligence*\n\n' +
            'Commands:\n' +
            '• `FIND NEARBY: pharmacy near Cape Town CBD` — find places nearby\n' +
            '• `LOCATE: 100 Long Street, Cape Town` — geocode an address\n' +
            '• `DIRECTIONS: Cape Town CBD | Stellenbosch` — get route info\n' +
            '• `MAP SEARCH: cardiologist in Johannesburg` — specialist search\n\n' +
            '🇿🇦 Optimised for South Africa'
        };
      }

      // ── FIND NEARBY ───────────────────────────────────────────
      if (context.triggerUsed === 'FIND NEARBY:' || context.triggerUsed === 'MAP SEARCH:') {
        const result = await mcpClient.callTool('maps_search_places', {
          query: payload.trim()
        });
        const text = result.map(c => c.text || '').join('\n');

        if (!context.aiEngine) return { response: `📍 *Results*\n\n${text}` };

        const aiResult = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              `Format these location results clearly for a South African medical practice.\n\n` +
              `Search: "${payload.trim()}"\n\nResults:\n${text}\n\n` +
              `Present as: name, address, rating (if available), distance. Keep it brief.`
          }],
          { systemPrompt: context.soulFile, temperature: 0.2 }
        );

        return { response: `📍 *${payload.trim()}*\n\n${aiResult.content}` };
      }

      // ── GEOCODE ───────────────────────────────────────────────
      if (context.triggerUsed === 'LOCATE:') {
        const result = await mcpClient.callTool('maps_geocode', {
          address: payload.trim()
        });
        const text = result.map(c => c.text || '').join('\n');
        return { response: `📍 *Location*\n\n${text}` };
      }

      // ── DIRECTIONS ────────────────────────────────────────────
      if (context.triggerUsed === 'DIRECTIONS:') {
        const parts  = payload.split('|').map(p => p.trim());
        const origin = parts[0];
        const dest   = parts[1];

        if (!dest) return { response: '⚠️ Usage: `DIRECTIONS: origin | destination`' };

        const result = await mcpClient.callTool('maps_directions', {
          origin,
          destination: dest,
          mode:        'driving'
        });
        const text = result.map(c => c.text || '').join('\n');
        return { response: `🗺️ *Directions*\n${origin} → ${dest}\n\n${text}` };
      }

      return { response: '⚠️ Unknown location command.' };

    } catch (err) {
      logger.error('[LOCATION] Error:', err.message);
      return { response: `❌ Location error: ${err.message}` };
    }
  }
};
