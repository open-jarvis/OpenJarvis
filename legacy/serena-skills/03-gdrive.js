// 03-gdrive.js - Google Drive Manager

const logger = require('../helpers/logger');
const {
  listDriveFolder,
  createDriveFolder,
  saveTextToDrive,
  uploadLocalFileToDrive
} = require('../helpers/google-drive');

module.exports = {
  id: '03-gdrive',
  name: 'Google Drive Manager',
  description: 'Save files to Drive, list folder contents, create folders, and upload generated documents.',
  triggers: ['DRIVE SAVE:', 'DRIVE LIST:', 'DRIVE FOLDER:', 'DRIVE UPLOAD:'],

  execute: async function (payload, context) {
    try {
      const rootFolder = process.env.GDRIVE_ROOT_FOLDER_ID;

      if (context.triggerUsed === 'DRIVE LIST:') {
        const folderId = payload.trim() || rootFolder;
        const files = await listDriveFolder(folderId, 20);

        if (files.length === 0) {
          return { response: '📂 Folder is empty.' };
        }

        const list = files.map((file) => {
          const icon = file.mimeType === 'application/vnd.google-apps.folder' ? '📁' : '📄';
          return `${icon} ${file.name}`;
        }).join('\n');

        logger.info(`[GDRIVE] Listed ${files.length} files`);
        return { response: `📂 *Drive contents (${files.length} items):*\n\n${list}` };
      }

      if (context.triggerUsed === 'DRIVE FOLDER:') {
        if (!payload || payload.trim().length < 2) {
          return { response: '⚠️ Usage: `DRIVE FOLDER: Folder Name`' };
        }

        const folder = await createDriveFolder(payload.trim(), rootFolder);
        logger.info(`[GDRIVE] Folder created: ${folder.name} (${folder.id})`);
        return {
          response:
            `✅ *Folder created:* ${folder.name}\n` +
            `📁 ID: \`${folder.id}\``
        };
      }

      if (context.triggerUsed === 'DRIVE SAVE:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `DRIVE SAVE: filename.txt | Content here...`' };
        }

        const separatorIndex = payload.indexOf('|');
        if (separatorIndex === -1) {
          return { response: '⚠️ Separate filename and content with `|`\nExample: `DRIVE SAVE: notes.txt | Your content here`' };
        }

        const fileName = payload.substring(0, separatorIndex).trim();
        const content = payload.substring(separatorIndex + 1).trim();
        const file = await saveTextToDrive(fileName, content, rootFolder);

        logger.info(`[GDRIVE] File saved: ${file.name} (${file.id})`);
        return {
          response:
            `✅ *Saved to Google Drive*\n\n` +
            `📄 *File:* ${file.name}\n` +
            `🔗 ID: \`${file.id}\``
        };
      }

      if (context.triggerUsed === 'DRIVE UPLOAD:') {
        if (!payload || payload.trim().length < 3) {
          return { response: '⚠️ Usage: `DRIVE UPLOAD: C:\\path\\to\\file.pdf`' };
        }

        const file = await uploadLocalFileToDrive(payload.trim(), { parentId: rootFolder });
        logger.info(`[GDRIVE] Local file uploaded: ${file.name} (${file.id})`);
        return {
          response:
            `✅ *Uploaded to Google Drive*\n\n` +
            `📄 *File:* ${file.name}\n` +
            `🔗 ID: \`${file.id}\``
        };
      }

      return { response: '⚠️ Unknown Drive command. Try: `DRIVE LIST:`, `DRIVE FOLDER:`, `DRIVE SAVE:`, or `DRIVE UPLOAD:`' };
    } catch (error) {
      logger.error('[GDRIVE] Error: ' + error.message);
      return { response: `❌ Google Drive error: ${error.message}\n\n_Check that your Google credentials in .env are valid._` };
    }
  }
};
