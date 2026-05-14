const fs = require('fs');
const path = require('path');
const axios = require('axios');
const logger = require('../helpers/logger');
const { directVideoRequest } = require('../helpers/video-director');
const {
  saveVideoMemory,
  updateVideoMemory,
  getLastVideoMemory
} = require('../helpers/video-memory');
const { ensureDriveFolderPath, uploadLocalFileToDrive } = require('../helpers/google-drive');

const DEFAULT_TIMEOUT_MS = 12 * 60 * 1000;
const DEFAULT_POLL_INTERVAL_MS = 5000;
const TEMP_DIR = path.join(__dirname, '../../temp');

function getServiceBaseUrl(engine) {
  if (engine === 'veo') {
    const port = Number(process.env.VEO_PORT || 3051);
    return process.env.VEO_SERVICE_URL || `http://127.0.0.1:${port}`;
  }

  const port = Number(process.env.SORA_PORT || 3052);
  return process.env.SORA_SERVICE_URL || `http://127.0.0.1:${port}`;
}

function modeFromTrigger(trigger) {
  const mapping = {
    'VIDEO FAST:': 'fast',
    'VIDEO HQ:': 'hq',
    'VIDEO CINEMATIC:': 'cinematic',
    'VIDEO AD:': 'ad',
    'VIDEO REEL:': 'reel',
    'VIDEO EDUCATION:': 'education',
    'VIDEO TESTIMONIAL STYLE:': 'testimonial',
    'VIDEO PRODUCT:': 'product',
    'VIDEO FROM IMAGE:': 'from_image',
    'VIDEO REMIX:': 'remix',
    'VIDEO:': 'auto',
    'GENERATE VIDEO:': 'auto',
    'VEO:': 'cinematic'
  };

  return mapping[trigger] || 'auto';
}

async function waitForJobCompletion(baseUrl, jobId, timeoutMs) {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const { data } = await axios.get(`${baseUrl}/jobs/${jobId}`, { timeout: 10000 });

    if (data.status === 'completed') {
      return data;
    }

    if (data.status === 'failed') {
      throw new Error(data.error || 'Video microservice job failed');
    }

    await new Promise((resolve) => setTimeout(resolve, DEFAULT_POLL_INTERVAL_MS));
  }

  throw new Error('Timed out waiting for video generation to complete');
}

async function downloadTelegramPhoto(context) {
  if (!context.photoFileId || !context.bot) return null;
  if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
  }

  const fileInfo = await context.bot.getFile(context.photoFileId);
  const fileUrl = `https://api.telegram.org/file/bot${process.env.TELEGRAM_TOKEN}/${fileInfo.file_path}`;
  const outputPath = path.join(TEMP_DIR, `video_ref_${Date.now()}.jpg`);
  const response = await axios.get(fileUrl, { responseType: 'arraybuffer', timeout: 30000 });
  fs.writeFileSync(outputPath, Buffer.from(response.data));
  return outputPath;
}

async function uploadVideoArchive(localPath, engine) {
  if (!process.env.GDRIVE_ROOT_FOLDER_ID) return null;
  const parentId = await ensureDriveFolderPath(
    ['Serena Generated Videos', engine.toUpperCase()],
    process.env.GDRIVE_ROOT_FOLDER_ID
  );
  return uploadLocalFileToDrive(localPath, { parentId });
}

function estimateCostNote(engine, durationSeconds) {
  if (engine === 'veo') {
    return `Estimated premium generation budget used for ${durationSeconds}s on Veo.`;
  }

  return `Estimated Sora budget used for ${durationSeconds}s on ${engine}.`;
}

function buildUsageHelp() {
  return (
    'Examples:\n' +
    '`VIDEO FAST: luxury clinic lobby, warm light, smooth motion`\n' +
    '`VIDEO HQ: cinematic drone shot of Johannesburg skyline at sunset`\n' +
    '`VIDEO CINEMATIC: premium medical commercial, slow camera push, golden light`\n' +
    '`VIDEO FROM IMAGE: turn this clinic reception photo into a cinematic 8-second walkthrough`\n' +
    '`VIDEO REMIX: make the previous video warmer, slower, and more premium`'
  );
}

module.exports = {
  id: '32-video-generator',
  name: 'Hybrid Video Orchestrator',
  description: 'Route video requests through GPT-5-mini direction plus Veo or Sora generation.',
  triggers: [
    'VIDEO FAST:',
    'VIDEO HQ:',
    'VIDEO CINEMATIC:',
    'VIDEO AD:',
    'VIDEO REEL:',
    'VIDEO EDUCATION:',
    'VIDEO TESTIMONIAL STYLE:',
    'VIDEO PRODUCT:',
    'VIDEO FROM IMAGE:',
    'VIDEO REMIX:',
    'VIDEO:',
    'GENERATE VIDEO:',
    'VEO:'
  ],

  execute: async function execute(payload, context) {
    const rawPrompt = String(payload || '').trim();
    const trigger = context.triggerUsed;
    const mode = modeFromTrigger(trigger);

    if (!rawPrompt && mode !== 'remix') {
      return {
        response:
          'Usage: start with one of Serena’s video triggers and then describe the scene.\n\n' +
          buildUsageHelp()
      };
    }

    let inputReferencePath = null;

    try {
      if (mode === 'from_image') {
        inputReferencePath = await downloadTelegramPhoto(context);
        if (!inputReferencePath) {
          return {
            response:
              'VIDEO FROM IMAGE requires a photo with the caption trigger.\n\n' +
              'Send the image to Serena with a caption like:\n' +
              '`VIDEO FROM IMAGE: turn this clinic reception photo into a cinematic walkthrough`'
          };
        }
      }

      const remixSource = mode === 'remix' ? getLastVideoMemory({ userId: context.userId }) : null;
      if (mode === 'remix' && !remixSource) {
        return {
          response: 'No previous Serena video was found to remix yet. Generate a video first, then use `VIDEO REMIX:`.'
        };
      }
      const remixVideoId = remixSource && String(remixSource.engine || '').startsWith('sora')
        ? (remixSource.remoteVideoId || remixSource.providerVideoId || null)
        : null;

      const spec = await directVideoRequest({
        aiEngine: context.aiEngine,
        soulFile: context.soulFile,
        rawPrompt: rawPrompt || remixSource?.originalPrompt || '',
        mode,
        hasReferenceImage: Boolean(inputReferencePath),
        remixSource
      });

      const forcedEngine = trigger === 'VEO:' ? 'veo' : null;
      const engine = forcedEngine || spec.recommended_engine || 'veo';
      const baseUrl = getServiceBaseUrl(engine);
      const timeoutMs = Number(process.env.VIDEO_JOB_TIMEOUT_MS || DEFAULT_TIMEOUT_MS);

      const memory = saveVideoMemory({
        id: `video-run-${Date.now()}`,
        userId: context.userId,
        mode,
        engine,
        status: 'queued',
        originalPrompt: rawPrompt,
        rewrittenPrompt: spec.final_prompt,
        aspectRatio: spec.aspect_ratio,
        durationSeconds: spec.duration_seconds,
        platformTarget: spec.platform_target,
        negativeConstraints: spec.negative_constraints,
        qaNotes: spec.qa_notes,
        remixOf: remixVideoId || remixSource?.id || null,
        referenceImagePath: inputReferencePath || null
      });

      logger.info(`[VIDEO] mode=${mode} engine=${engine} prompt=${rawPrompt.slice(0, 80)}`);

      const requestBody = engine === 'veo'
        ? {
            prompt: spec.final_prompt,
            duration: Number(spec.duration_seconds),
            resolution: spec.size === '1792x1024' ? '1080p' : '720p',
            aspectRatio: spec.aspect_ratio
          }
        : {
            prompt: spec.final_prompt,
            model: engine,
            seconds: Number(spec.duration_seconds),
            size: spec.size,
            aspectRatio: spec.aspect_ratio,
            inputReferencePath,
            remixVideoId: mode === 'remix' ? remixVideoId : null
          };

      const { data } = await axios.post(`${baseUrl}/generate`, requestBody, { timeout: 20000 });
      updateVideoMemory(memory.id, {
        status: 'processing',
        localJobId: data.jobId
      });

      const job = await waitForJobCompletion(baseUrl, data.jobId, timeoutMs);
      const filePath = job.outputFile || job.result?.outputFile;
      const remoteVideoId = job.providerVideoId || job.result?.id || job.result?.operationName || null;
      const driveUpload = await uploadVideoArchive(filePath, engine).catch(() => null);

      updateVideoMemory(memory.id, {
        status: 'completed',
        outputFile: filePath,
        remoteVideoId,
        driveFileId: driveUpload?.id || null,
        driveLink: driveUpload?.webViewLink || null
      });

      const responseLines = [
        'Video generated successfully.',
        '',
        `Mode: ${mode}`,
        `Engine: ${engine}`,
        `Prompt: ${rawPrompt || remixSource?.originalPrompt || ''}`,
        `Directed Prompt: ${spec.final_prompt}`,
        `Duration: ${spec.duration_seconds}s`,
        `Aspect Ratio: ${spec.aspect_ratio}`,
        `Job ID: ${job.id}`
      ];

      if (spec.qa_notes?.length) {
        responseLines.push(`QA Notes: ${spec.qa_notes.join(' | ')}`);
      }

      if (mode === 'remix' && !remixVideoId) {
        responseLines.push('Remix Note: previous video was not a Sora clip, so Serena generated a fresh upgraded version instead of a true Sora remix.');
      }

      responseLines.push(`Budget Note: ${spec.estimated_cost_note || estimateCostNote(engine, spec.duration_seconds)}`);

      if (driveUpload?.id) {
        responseLines.push(`Drive Archive: ${driveUpload.id}`);
      }

      return {
        response: responseLines.join('\n'),
        videoFile: filePath,
        cleanupMedia: false
      };
    } catch (error) {
      const message = error.response?.data?.error || error.message;
      logger.error(`[VIDEO] ${message}`);
      return {
        response: `Video generation failed: ${message}\n\n${buildUsageHelp()}`
      };
    } finally {
      if (inputReferencePath && fs.existsSync(inputReferencePath)) {
        try { fs.unlinkSync(inputReferencePath); } catch (_) {}
      }
    }
  }
};
