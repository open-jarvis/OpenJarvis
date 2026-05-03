const logger = require('../helpers/logger');
const { resolveImageInput } = require('../helpers/media-utils');

async function describeImage(context, prompt, imageInput) {
  const content = imageInput.type === 'url'
    ? [
        { type: 'text', text: prompt },
        { type: 'image_url', image_url: { url: imageInput.value } }
      ]
    : [
        { type: 'text', text: `${prompt}\n\nLocal image path: ${imageInput.value}` }
      ];

  const result = await context.aiEngine.chat(
    [{ role: 'user', content }],
    {
      systemPrompt:
        `${context.soulFile}\n\n` +
        'You are Serena\'s image description and caption engine. ' +
        'If asked for a caption, return a polished caption. If asked for a description, describe the image clearly.',
      temperature: 0.4,
      maxTokens: 900,
      task: 'image-caption'
    }
  );

  return String(result.content || '').trim();
}

module.exports = {
  id: '40-image-caption',
  name: 'Image Caption Generator',
  description: 'Generate polished captions and image descriptions from Telegram photos, URLs, or local image paths.',
  triggers: ['CAPTION IMAGE:', 'DESCRIBE IMAGE:'],

  execute: async function (payload, context) {
    try {
      const imageInput = await resolveImageInput(payload, context);
      if (!imageInput) {
        return {
          response:
            '⚠️ Send a photo with the caption trigger, or use `CAPTION IMAGE: https://...` / `DESCRIBE IMAGE: C:\\path\\image.jpg`.'
        };
      }

      const prompt = context.triggerUsed === 'CAPTION IMAGE:'
        ? 'Write one strong caption plus two alternates for this image.'
        : 'Describe this image clearly, including the main subject, setting, and any notable visual details.';
      const result = await describeImage(context, prompt, imageInput);

      return {
        response:
          `${context.triggerUsed === 'CAPTION IMAGE:' ? '🖼️ *Image Caption*' : '🖼️ *Image Description*'}\n\n${result}`
      };
    } catch (error) {
      logger.error('[IMAGE-CAPTION] Error: ' + error.message);
      return { response: `❌ Image caption error: ${error.message}` };
    }
  }
};
