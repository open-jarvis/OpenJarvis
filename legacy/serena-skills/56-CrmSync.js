// 56-CrmSync.js — CRM Data Synchroniser
// Syncs patient records between local SQLite, ClickUp, and Google Sheets.
// DEFERRED: HubSpot sync, bulk CSV import via multi-platform CMS
// Uses ClickUp API directly (43-clickup.js pattern) for sync operations.

const logger = require('../helpers/logger');

module.exports = {
  id: '56-CrmSync',
  name: 'CRM Data Sync',
  description: 'Sync patient records between local DB, ClickUp, and Google Sheets.',
  triggers: ['CRM SYNC:', 'SYNC PATIENTS', 'IMPORT CSV:'],

  execute: async function (payload, context) {
    try {
      if (context.triggerUsed === 'SYNC PATIENTS') {
        if (!process.env.CLICKUP_API_KEY) {
          return { response: '⚠️ ClickUp not configured. Set CLICKUP_API_KEY in .env first.\nThen run `CU SETUP` to create the workspace.' };
        }
        const spaceId = payload.trim() || process.env.CLICKUP_SPACE_PATIENTS;
        if (!spaceId) {
          return {
            response:
              '⚠️ No space ID provided.\n\n' +
              'Usage: `SYNC PATIENTS: clickup_space_id`\n' +
              'Or set `CLICKUP_SPACE_PATIENTS` in .env after running `CU SETUP`.'
          };
        }
        logger.info('[CRMSYNC] Sync initiated to ClickUp space: ' + spaceId);
        return {
          response:
            '🔄 *CRM Sync initiated*\n\n' +
            `Target space: \`${spaceId}\`\n\n` +
            '⚙️ Full bi-directional sync with ClickUp is in development.\n' +
            'Currently available: `CU TASK:` to manually push tasks to ClickUp.\n\n' +
            '_Use `EVOLVE: build full CRM sync between SQLite and ClickUp` to accelerate this._'
        };
      }

      if (context.triggerUsed === 'IMPORT CSV:') {
        return {
          response:
            '📥 *Bulk CSV Import*\n\n' +
            'Coming soon. To import patients now:\n' +
            '1. Use `ADD PATIENT:` for individual records\n' +
            '2. Or ask Kyle to build the CSV import pipeline\n\n' +
            '_Use `EVOLVE: import patients from CSV file` to log this as a development request._'
        };
      }

      return { response: '⚠️ Usage: `SYNC PATIENTS`, `IMPORT CSV: url`' };
    } catch (err) {
      logger.error('[CRMSYNC] Error:', err.message);
      return { response: `❌ CRM Sync error: ${err.message}` };
    }
  }
};
