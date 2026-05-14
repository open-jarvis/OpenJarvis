// 37-ocr.js — Document Scanner (OCR)
// Extracts text from uploaded images using:
// 1. Mistral Pixtral vision model (if MISTRAL_API_KEY set)
// 2. HuggingFace TrOCR (if HUGGINGFACE_API_KEY set)
// Usage: Upload a photo to Telegram with caption OCR: or SCAN DOC:

const logger = require('../helpers/logger');
const fs     = require('fs');
const path   = require('path');

async function ocrViaMistral(imageUrl, prompt = 'Extract all text from this image exactly as written.') {
  const res = await fetch('https://api.mistral.ai/v1/chat/completions', {
    method:  'POST',
    headers: {
      'Authorization': `Bearer ${process.env.MISTRAL_API_KEY}`,
      'Content-Type':  'application/json'
    },
    body: JSON.stringify({
      model:    'pixtral-12b-2409',
      messages: [{
        role:    'user',
        content: [
          { type: 'image_url', image_url: imageUrl },
          { type: 'text',      text: prompt }
        ]
      }],
      max_tokens:  4096,
      temperature: 0
    })
  });
  if (!res.ok) throw new Error(`Mistral OCR error ${res.status}`);
  const data = await res.json();
  return data.choices?.[0]?.message?.content || '';
}

async function ocrViaHuggingFace(imageBuffer) {
  const res = await fetch(
    'https://api-inference.huggingface.co/models/microsoft/trocr-large-printed',
    {
      method:  'POST',
      headers: { 'Authorization': `Bearer ${process.env.HUGGINGFACE_API_KEY}` },
      body:    imageBuffer
    }
  );
  if (!res.ok) {
    const errText = await res.text();
    if (errText.includes('loading')) throw new Error('MODEL_LOADING');
    throw new Error(`HF OCR error ${res.status}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data[0]?.generated_text || '' : data.generated_text || '';
}

module.exports = {
  id: '37-ocr',
  name: 'Document Scanner (OCR)',
  description: 'Extract text from uploaded images. Send photo with caption OCR: to activate.',
  triggers: ['SCAN DOC:', 'OCR:', 'EXTRACT TEXT:'],

  execute: async function (payload, context) {
    try {
      logger.info(`[OCR] Triggered: ${context.triggerUsed} | photo: ${!!context.photoFileId}`);

      const hasAnyKey = !!(process.env.MISTRAL_API_KEY || process.env.HUGGINGFACE_API_KEY);

      if (!context.photoFileId) {
        return {
          response:
            '📄 *Document Scanner (OCR)*\n\n' +
            'To scan a document:\n' +
            '1. Upload a photo to this chat\n' +
            '2. Add caption: `OCR:` or `SCAN DOC:`\n\n' +
            'Optionally add instructions in the caption:\n' +
            '`OCR: extract only the lab values`\n' +
            '`SCAN DOC: summarise this medical report`\n\n' +
            (hasAnyKey ? '✅ OCR is configured and ready' : '⚠️ Add MISTRAL_API_KEY or HUGGINGFACE_API_KEY to .env')
        };
      }

      if (!hasAnyKey) {
        return {
          response:
            '⚠️ *OCR not configured*\n\n' +
            'Add one of:\n' +
            '• `MISTRAL_API_KEY` (best quality, vision-capable)\n' +
            '• `HUGGINGFACE_API_KEY` (free tier)\n\n' +
            'to your .env file.'
        };
      }

      const instruction = payload && payload.trim().length > 2
        ? payload.trim()
        : 'Extract all text from this image exactly as written. Preserve formatting.';

      let extractedText = '';
      let method        = '';

      // Get image URL from Telegram
      const fileInfoRes = await fetch(
        `https://api.telegram.org/bot${process.env.TELEGRAM_TOKEN}/getFile?file_id=${context.photoFileId}`
      );
      const fileInfo = await fileInfoRes.json();
      const imageUrl = `https://api.telegram.org/file/bot${process.env.TELEGRAM_TOKEN}/${fileInfo.result.file_path}`;

      if (process.env.MISTRAL_API_KEY) {
        try {
          extractedText = await ocrViaMistral(imageUrl, instruction);
          method        = 'Mistral Pixtral';
        } catch (mistralErr) {
          logger.warn('[OCR] Mistral failed, trying HuggingFace: ' + mistralErr.message);
        }
      }

      if (!extractedText && process.env.HUGGINGFACE_API_KEY) {
        try {
          const imgRes    = await fetch(imageUrl);
          const imgBuffer = Buffer.from(await imgRes.arrayBuffer());
          extractedText   = await ocrViaHuggingFace(imgBuffer);
          method          = 'HuggingFace TrOCR';
        } catch (hfErr) {
          if (hfErr.message === 'MODEL_LOADING') {
            return { response: '⏳ OCR model is loading. Please try again in 20-30 seconds.' };
          }
          throw hfErr;
        }
      }

      if (!extractedText || extractedText.trim().length < 2) {
        return { response: '⚠️ No text could be extracted. Try a clearer image with better lighting and contrast.' };
      }

      logger.info(`[OCR] Extracted ${extractedText.length} chars via ${method}`);
      return {
        response:
          `📄 *Text Extracted* _(via ${method})_\n\n` +
          '━━━━━━━━━━━━━━━━━━\n\n' +
          extractedText.substring(0, 3500) +
          (extractedText.length > 3500 ? '\n\n_[Text truncated]_' : '') +
          '\n\n━━━━━━━━━━━━━━━━━━\n' +
          '💡 Next: `SUMMARISE: [paste extracted text]` or `INTERPRET LAB: [paste lab values]`'
      };

    } catch (err) {
      logger.error('[OCR] Error:', err.message);
      return { response: `❌ OCR error: ${err.message}` };
    }
  }
};
