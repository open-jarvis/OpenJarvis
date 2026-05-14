const fs = require('fs');
const path = require('path');
const logger = require('../helpers/logger');

function isSafeQuery(sql) {
  const normalized = String(sql || '').trim().toLowerCase();
  return normalized.startsWith('select ') || normalized.startsWith('pragma ') || normalized.startsWith('with ');
}

module.exports = {
  id: '46-database',
  name: 'Database Operations',
  description: 'Run safe read-only SQLite queries and create database backups.',
  triggers: ['DB QUERY:', 'DB BACKUP:'],

  execute: async function (payload, context) {
    try {
      if (!context.db) {
        return { response: '⚠️ Database is not available right now.' };
      }

      if (context.triggerUsed === 'DB QUERY:') {
        const sql = String(payload || '').trim();
        if (!sql) {
          return { response: '⚠️ Usage: `DB QUERY: SELECT * FROM patients LIMIT 10`' };
        }
        if (!isSafeQuery(sql)) {
          return { response: '🔒 Only read-only queries are allowed through Serena. Use `SELECT`, `WITH`, or `PRAGMA`.' };
        }

        const rows = await context.db.all(sql);
        return {
          response:
            `🗄️ *DB Query Result*\n\n` +
            '```json\n' +
            `${JSON.stringify(rows.slice(0, 25), null, 2)}\n` +
            '```' +
            (rows.length > 25 ? '\n\n_(truncated to first 25 rows)_' : '')
        };
      }

      const dbPath = path.resolve(process.env.DB_STORAGE || path.join(__dirname, '../../database.sqlite'));
      if (!fs.existsSync(dbPath)) {
        return { response: `❌ Database file not found: ${dbPath}` };
      }

      const backupDir = path.join(path.dirname(dbPath), 'backups');
      fs.mkdirSync(backupDir, { recursive: true });
      const backupPath = path.join(backupDir, `database-backup-${Date.now()}.sqlite`);
      fs.copyFileSync(dbPath, backupPath);

      logger.info(`[DATABASE] Backup created: ${backupPath}`);
      return {
        response: `✅ *Database backup created*\n\n\`${backupPath}\``
      };
    } catch (error) {
      logger.error('[DATABASE] Error: ' + error.message);
      return { response: `❌ Database operations error: ${error.message}` };
    }
  }
};
