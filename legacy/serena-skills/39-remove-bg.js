const fs = require('fs');
const path = require('path');
const axios = require('axios');
const logger = require('../helpers/logger');
const { cleanupTempFile, downloadTelegramMedia, resolveImageInput } = require('../helpers/media-utils');

const HF_REMOVE_BG_URL = 'https://router.huggingface.co/hf-inference/models/briaai/RMBG-1.4';

module.exports = {
  id: '39-remove-bg',
  name: 'Background Remover',
  description: 'Remove image backgrounds using the Hugging Face RMBG model from Telegram photos, URLs, or local files.',
  triggers: ['REMOVE BG:', 'CLEAN IMAGE:'],

  execute: async function (payload, context) {
    let localInputPath = null;
    let localOutputPath = null;

    try {
      if (!process.env.HUGGINGFACE_API_KEY) {
        return { response: '⚠️ Background removal requires `HUGGINGFACE_API_KEY` in `.env`.' };
      }

      let imageInput = await resolveImageInput(payload, context);
      if (!imageInput && context.photoFileId && context.bot) {
        const downloaded = await downloadTelegramMedia(context.bot, context.photoFileId, 'jpg');
        imageInput = { type: 'file', value: downloaded.localPath };
        localInputPath = downloaded.localPath;
      }

      if (!imageInput) {
        return {
          response:
            '⚠️ Send a photo with `REMOVE BG:` as the caption, or provide a local image path/URL after the trigger.'
        };
      }

      let imageBuffer;
      if (imageInput.type === 'url') {
        const response = await axios.get(imageInput.value, { responseType: 'arraybuffer', timeout: 30000 });
        imageBuffer = Buffer.from(response.data);
      } else {
        imageBuffer = fs.readFileSync(imageInput.value);
      }

      const result = await axios.post(HF_REMOVE_BG_URL, imageBuffer, {
        headers: {
          Authorization: `Bearer ${process.env.HUGGINGFACE_API_KEY}`,
          'Content-Type': 'application/octet-stream'
        },
        responseType: 'arraybuffer',
        timeout: 120000
      });

      localOutputPath = path.join(path.join(__dirname, '../../temp'), `remove_bg_${Date.now()}.png`);
      fs.writeFileSync(localOutputPath, Buffer.from(result.data));

      return {
        response: '✅ *Background removed successfully*',
        imageFile: localOutputPath,
        cleanupMedia: true
      };
    } catch (error) {
      const message = error.response?.data ? Buffer.from(error.response.data).toString('utf8').slice(0, 200) : error.message;
      logger.error('[REMOVE-BG] Error: ' + message);
      return { response: `❌ Background removal failed: ${message}` };
    } finally {
      cleanupTempFile(localInputPath);
    }
  }
};
