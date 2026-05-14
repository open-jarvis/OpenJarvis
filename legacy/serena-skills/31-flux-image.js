// 31-flux-image.js — Flux Image Generation
// Uses Hugging Face Inference API directly (no extra package).
// Model: black-forest-labs/FLUX.1-schnell (free tier available)
// Requires: HUGGINGFACE_API_KEY in .env

const logger = require('../helpers/logger');
const fs = require('fs');
const path = require('path');

// FIXED: Updated to the new Hugging Face router endpoint (2026)
const HF_API = 'https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell';

module.exports = {
  id: '31-flux-image',
  name: 'Flux Image Generator',
  description: 'Generate images using Flux.1-schnell via Hugging Face API.',
  triggers: ['IMAGE:', 'FLUX:', 'GENERATE IMAGE:'],

  execute: async function (payload, context) {
    try {
      if (!payload || payload.trim().length < 3) {
        return {
          response:
            '⚠️ Usage: `IMAGE: your image description here`\n\n' +
            'Example: `IMAGE: Professional South African doctor in a modern clinic, warm lighting, photorealistic`'
        };
      }

      if (!process.env.HUGGINGFACE_API_KEY) {
        return { response: '⚠️ HUGGINGFACE_API_KEY not set in .env' };
      }

      const prompt = payload.trim();
      logger.info(`[FLUX] Generating image: ${prompt.substring(0, 60)}...`);

      // Call HF Inference API — returns binary image
      const response = await fetch(HF_API, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.HUGGINGFACE_API_KEY}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          inputs: prompt,
          parameters: {
            width: 1024,
            height: 1024,
            num_inference_steps: 4,
            guidance_scale: 0
          }
        })
      });

      if (!response.ok) {
        const errText = await response.text();
        // Model loading — common on free tier cold starts
        if (response.status === 503 || errText.includes('loading') || response.status === 429) {
          return {
            response:
              `⏳ *Image model is loading*\n\n` +
              `The Flux model is warming up on Hugging Face (this happens after periods of inactivity).\n` +
              `Please try again in 20–40 seconds.\n\n` +
              `_Prompt saved: "${prompt.substring(0, 100)}"_`
          };
        }
        throw new Error(`HF API error ${response.status}: ${errText.substring(0, 300)}`);
      }

      // Save image to temp file and send via Telegram
      const imageBuffer = Buffer.from(await response.arrayBuffer());
      const outputDir = path.join(__dirname, '../../temp');
      if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

      const fileName = `flux_${Date.now()}.png`;
      const filePath = path.join(outputDir, fileName);
      fs.writeFileSync(filePath, imageBuffer);

      logger.info(`[FLUX] Image generated: ${fileName} (${imageBuffer.length} bytes)`);

      // Return file path for the Telegram dispatcher to send as photo
      return {
        response: `🎨 *Image generated!*\n\n📝 _Prompt:_ ${prompt}`,
        imageFile: filePath,
        cleanup: true
      };

    } catch (err) {
      logger.error('[FLUX] Error:', err.message);
      return { response: `❌ Image generation failed: ${err.message}\n\nCheck your HUGGINGFACE_API_KEY and try again.` };
    }
  }
};