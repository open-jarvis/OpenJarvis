const fs = require('fs');
const path = require('path');
const logger = require('../helpers/logger');
const { withTimeout } = require('../helpers/async-utils');
const {
  archiveCompletedPdfToDrive,
  buildLiveModeBlockedMessage,
  buildPreviewMessage,
  buildSetupMessage,
  createDocusealClient,
  buildSignatureFieldPlan,
  ensureSignatureTable,
  findSignatureRecord,
  insertSignatureRecord,
  isOwner,
  looksLikeSelfSigningRequest,
  normalizeText,
  parseSignatureRequest,
  resolveDocumentSource,
  updateSignatureRecord,
  validateSignatureRequest,
  fileToBase64,
  downloadUrlToTemp,
  inspectPdfDocument
} = require('../helpers/docuseal-service');
const { downloadDriveFileToTemp } = require('../helpers/google-drive');

function parseBool(value) {
  return /^(true|1|yes|on)$/i.test(String(value || '').trim());
}

function getDocusealConfig() {
  return {
    apiUrl: String(process.env.DOCUSEAL_API_URL || '').trim().replace(/\/+$/, ''),
    apiKey: String(process.env.DOCUSEAL_API_KEY || '').trim(),
    defaultFromName: String(process.env.DOCUSEAL_DEFAULT_FROM_NAME || 'Serena').trim(),
    archiveDriveFolderId: String(process.env.DOCUSEAL_ARCHIVE_DRIVE_FOLDER_ID || '').trim(),
    liveMode: parseBool(process.env.DOCUSEAL_LIVE_MODE)
  };
}

function logDocusealConfig(config) {
  logger.info(`[85-esignature] DocuSeal config ${JSON.stringify({
    apiUrlPresent: Boolean(config.apiUrl),
    apiKeyPresent: Boolean(config.apiKey),
    archiveFolderPresent: Boolean(config.archiveDriveFolderId),
    liveModeRaw: process.env.DOCUSEAL_LIVE_MODE ?? null,
    liveModeParsed: Boolean(config.liveMode)
  })}`);
}

function isLiveModeEnabled(config = getDocusealConfig()) {
  return Boolean(config.liveMode);
}

function hasDocuSealConfig(config = getDocusealConfig()) {
  return Boolean(config.apiUrl && config.apiKey);
}

function isDocusealReady(config = getDocusealConfig()) {
  return Boolean(isLiveModeEnabled(config) && hasDocuSealConfig(config));
}

function isApprovalQueueAvailable(context) {
  return Boolean(context?.autonomousEngine && typeof context.autonomousEngine.queueApproval === 'function');
}

function getDocusealClient(config = getDocusealConfig()) {
  return createDocusealClient({
    apiUrl: config.apiUrl,
    apiKey: config.apiKey,
    fetchImpl: global.fetch
  });
}

function buildDocusealFailureMessage(config = getDocusealConfig()) {
  if (!isLiveModeEnabled(config)) {
    return buildLiveModeBlockedMessage();
  }

  if (!hasDocuSealConfig(config)) {
    return buildSetupMessage();
  }

  return buildLiveModeBlockedMessage();
}

function buildOwnerOnlyMessage() {
  return 'Owner only. DocuSeal signature actions are restricted to approved owners.';
}

function normalizeStatusText(record, submission, submitters) {
  const lines = [
    'DocuSeal signature status',
    '',
    `Document: ${record?.document_name || submission?.name || 'Unknown'}`,
    `Provider: ${record?.provider || 'docuseal'}`,
    `Submission ID: ${submission?.id || record?.submission_id || 'unknown'}`,
    `Status: ${submission?.status || record?.status || 'unknown'}`,
    `Created: ${submission?.created_at || record?.created_at || 'unknown'}`,
    `Updated: ${submission?.updated_at || record?.updated_at || 'unknown'}`
  ];

  if (Array.isArray(submitters) && submitters.length) {
    lines.push('', 'Signers:');
    submitters.forEach((submitter, index) => {
      lines.push(
        `${index + 1}. ${submitter.name || submitter.email || submitter.phone || 'Signer'} - ${submitter.status || 'unknown'}`
      );
    });
  }

  if (submission?.combined_document_url) {
    lines.push('', `Completed PDF: ${submission.combined_document_url}`);
  }

  if (submission?.audit_log_url) {
    lines.push(`Audit log: ${submission.audit_log_url}`);
  }

  return lines.join('\n');
}

async function ensureRecordForRequest(db, request, context, providerResponse = null) {
  if (!db) return null;
  const createdAt = new Date().toISOString();
  const recordId = await insertSignatureRecord(db, {
    provider: 'docuseal',
    submission_id: providerResponse?.id || providerResponse?.submission_id || null,
    document_name: request.documentReference || request.documentName || 'Untitled document',
    document_path: request.documentPath || request.documentReference || null,
    signers_json: request.signers || [],
    status: providerResponse ? 'sent' : 'awaiting_approval',
    created_by: String(context.userId || ''),
    created_at: createdAt,
    updated_at: createdAt,
    completed_at: providerResponse?.completed_at || null,
    archive_path: providerResponse?.archive_path || null,
    drive_file_id: providerResponse?.drive_file_id || null,
    raw_provider_response_json: providerResponse || null
  });
  return recordId;
}

async function loadRecord(context, identifier) {
  if (!context?.db) return null;
  return findSignatureRecord(context.db, identifier);
}

async function resolveDocusealArtifacts(request) {
  const source = await resolveDocumentSource(request);
  if (source?.type === 'error') {
    return {
      ok: false,
      message: source.message || `I could not locate the document file for "${request.documentReference}".`
    };
  }
  if (!source || source.type === 'name') {
    return {
      ok: false,
      message: `I could not locate the document file for "${request.documentReference}". Please provide a valid PDF or DOCX path accessible to Serena.`
    };
  }

  let effectiveSource = source;
  let file = await fileToBase64(source);
  if (source.type === 'drive') {
    const downloaded = await withTimeout(() => downloadDriveFileToTemp({
      fileId: source.fileId || source.value,
      fileName: source.name || request.documentReference,
      mimeType: source.mimeType,
      tempDir: path.join(__dirname, '../../temp/docuseal')
    }), parseInt(process.env.GOOGLE_DRIVE_TIMEOUT_MS || '15000', 10), 'Google Drive download for DocuSeal');
    effectiveSource = { type: 'path', value: downloaded, name: path.basename(downloaded) };
    file = await fileToBase64(effectiveSource);
  }

  if (!file) {
    return { ok: false, message: `I could not read the document file for "${request.documentReference}".` };
  }

  const pdfInfo = effectiveSource.type === 'path'
    ? await inspectPdfDocument(effectiveSource.value)
    : null;
  const fieldPlan = await buildSignatureFieldPlan({ request, pdfInfo, filePath: effectiveSource.value });

  if (!fieldPlan.fields.length && !fieldPlan.usesEmbeddedTags) {
    if (fieldPlan.confidence === 'low' && fieldPlan.detection?.placements?.length) {
      return {
        ok: false,
        message: [
          'I found multiple possible signature areas and cannot safely choose one.',
          'Please specify placement manually or confirm which page/section to use.'
        ].join(' ')
      };
    }
    return { ok: false, message: 'Cannot send: no signature field defined.' };
  }

  return {
    ok: true,
    source,
    effectiveSource,
    file,
    pdfInfo,
    fieldPlan
  };
}

async function prepareLiveSubmission(request) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const client = getDocusealClient(config);
  if (!client) {
    return { ok: false, message: buildSetupMessage() };
  }

  const artifacts = await resolveDocusealArtifacts(request);
  if (!artifacts.ok) return artifacts;
  const { effectiveSource, file, fieldPlan } = artifacts;

  if (fieldPlan.placement) {
    logger.info(`[85-esignature] Field plan ${JSON.stringify({
      document: path.basename(effectiveSource.value || effectiveSource.name || request.documentReference),
      signerRoles: request.signers.map((signer, index) => normalizeText(signer.role || signer.name || `Signer ${index + 1}`) || `Signer ${index + 1}`),
      page: fieldPlan.placement.page,
      x: fieldPlan.placement.x,
      y: fieldPlan.placement.y,
      w: fieldPlan.placement.w,
      h: fieldPlan.placement.h,
      confidence: fieldPlan.confidence,
      method: fieldPlan.method
    })}`);
  }

  const submission = await withTimeout(() => client.createSubmissionFromPdf({
    name: path.basename(effectiveSource.value || effectiveSource.name || request.documentReference),
    documents: [{
      name: path.basename(effectiveSource.value || effectiveSource.name || request.documentReference),
      file,
      fields: fieldPlan.fields
    }],
    submitters: request.signers.map((signer, index) => ({
      name: signer.name,
      email: signer.email || undefined,
      phone: signer.phone || undefined,
      role: signer.role || signer.name || `Signer ${index + 1}`,
      external_id: signer.external_id || `${sanitizeNameForExternalId(signer.name, index)}-${index + 1}`
    })),
    order: request.order,
    send_email: true,
    send_sms: Boolean(request.signers.some((signer) => signer.phone && !signer.email))
  }), parseInt(process.env.DOCUSEAL_REQUEST_TIMEOUT_MS || '15000', 10), 'DocuSeal create submission');

  return {
    ok: true,
    submission,
    documentSource: effectiveSource,
    fieldPlan
  };
}

function sanitizeNameForExternalId(name, index) {
  const base = normalizeText(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return base || `signer-${index + 1}`;
}

async function executeLiveCreate(request, context, recordId = null) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const result = await prepareLiveSubmission(request);
  if (!result.ok) {
    return result;
  }

  if (context.db) {
    if (recordId) {
      await updateSignatureRecord(context.db, recordId, {
        submission_id: result.submission.id || null,
        document_name: request.documentReference,
        document_path: result.documentSource.value,
        signers_json: request.signers,
        status: 'sent',
        completed_at: result.submission.completed_at || null,
        raw_provider_response_json: {
          submission: result.submission,
          field_plan: result.fieldPlan
        }
      });
    } else {
      recordId = await ensureRecordForRequest(context.db, request, context, {
        ...result.submission,
        field_plan: result.fieldPlan
      });
    }
  }

  return {
    ok: true,
    message: [
      'DocuSeal signature request sent.',
      '',
      `Document: ${request.documentReference}`,
      `Submission ID: ${result.submission.id || 'unknown'}`,
      `Order: ${request.order}`,
      `Signers: ${request.signers.map((signer) => signer.name).join(', ')}`,
      `Placement: ${result.fieldPlan?.method === 'manual' ? 'manual' : 'auto-detected'}`,
      `Confidence: ${result.fieldPlan?.confidence || 'medium'}`,
      result.fieldPlan?.placement ? `Signature field: page ${result.fieldPlan.placement.page} @ x=${result.fieldPlan.placement.x}, y=${result.fieldPlan.placement.y}, w=${result.fieldPlan.placement.w}, h=${result.fieldPlan.placement.h}` : null,
      result.fieldPlan?.fields?.find((field) => field.type === 'date')
        ? `Date field: page ${result.fieldPlan.fields.find((field) => field.type === 'date').areas[0].page} @ x=${result.fieldPlan.fields.find((field) => field.type === 'date').areas[0].x}, y=${result.fieldPlan.fields.find((field) => field.type === 'date').areas[0].y}, w=${result.fieldPlan.fields.find((field) => field.type === 'date').areas[0].w}, h=${result.fieldPlan.fields.find((field) => field.type === 'date').areas[0].h}`
        : 'Date field: disabled',
      result.submission.slug ? `Submission slug: ${result.submission.slug}` : null,
      recordId ? `Local record ID: ${recordId}` : null
    ].filter(Boolean).join('\n')
  };
}

async function executeLiveCancel(request, context, record = null) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const client = getDocusealClient(config);
  if (!client) {
    return { ok: false, message: buildSetupMessage() };
  }

  const submissionId = record?.submission_id || request.submissionId || request.identifier;
  if (!submissionId) {
    return { ok: false, message: `I could not find a submission ID for "${request.documentReference || request.source}".` };
  }

  const cancelled = await withTimeout(() => client.archiveSubmission(submissionId), parseInt(process.env.DOCUSEAL_REQUEST_TIMEOUT_MS || '15000', 10), 'DocuSeal cancel submission');
  if (context.db && record?.id) {
    await updateSignatureRecord(context.db, record.id, {
      status: 'cancelled',
      raw_provider_response_json: cancelled
    });
  }

  return {
    ok: true,
    message: [
      'DocuSeal signature request cancelled.',
      '',
      `Document: ${record?.document_name || request.documentReference || 'unknown'}`,
      `Submission ID: ${submissionId}`,
      `Archived at: ${cancelled.archived_at || new Date().toISOString()}`
    ].join('\n')
  };
}

async function fetchStatusFromProvider(record, context) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const client = getDocusealClient(config);
  if (!client) {
    return { ok: false, message: buildSetupMessage() };
  }

  const submissionId = record?.submission_id;
  if (!submissionId) {
    return { ok: false, message: `No live submission ID is stored for ${record?.document_name || 'this request'}.` };
  }

  const submission = await withTimeout(() => client.getSubmission(submissionId), parseInt(process.env.DOCUSEAL_REQUEST_TIMEOUT_MS || '15000', 10), 'DocuSeal get submission');
  const submitters = await withTimeout(() => client.listSubmitters({ submission_id: submissionId }), parseInt(process.env.DOCUSEAL_REQUEST_TIMEOUT_MS || '15000', 10), 'DocuSeal list submitters');
  if (record?.id && context?.db) {
    await updateSignatureRecord(context.db, record.id, {
      status: submission.status || record.status || 'unknown',
      completed_at: submission.completed_at || record.completed_at || null,
      raw_provider_response_json: submission
    });
  }

  return {
    ok: true,
    submission,
    submitters: submitters?.data || submitters || []
  };
}

async function remindPendingSigners(record) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const client = getDocusealClient(config);
  if (!client) {
    return { ok: false, message: buildSetupMessage() };
  }

  const submissionId = record?.submission_id;
  if (!submissionId) {
    return { ok: false, message: `No live submission ID is stored for ${record?.document_name || 'this request'}.` };
  }

  const submission = await withTimeout(() => client.getSubmission(submissionId), parseInt(process.env.DOCUSEAL_REQUEST_TIMEOUT_MS || '15000', 10), 'DocuSeal get submission');
  const submitters = Array.isArray(submission?.submitters) ? submission.submitters : [];
  const pending = submitters.filter((submitter) => !['completed', 'declined'].includes(String(submitter.status || '').toLowerCase()));
  if (!pending.length) {
    return {
      ok: true,
      message: `No pending signers remain for ${record?.document_name || 'this request'}.`
    };
  }

  for (const submitter of pending) {
    if (!submitter.id) continue;
    await client.updateSubmitter(submitter.id, {
      send_email: true,
      send_sms: Boolean(submitter.phone && !submitter.email)
    });
  }

  return {
    ok: true,
    message: [
      'DocuSeal reminder sent.',
      '',
      `Document: ${record?.document_name || submission?.name || 'unknown'}`,
      `Reminded signers: ${pending.map((submitter) => submitter.name || submitter.email || submitter.phone || 'Signer').join(', ')}`
    ].join('\n')
  };
}

async function archiveCompletedSubmission(record, context) {
  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return { ok: false, message: buildDocusealFailureMessage(config) };
  }

  const client = getDocusealClient(config);
  if (!client) {
    return { ok: false, message: buildSetupMessage() };
  }

  const submissionId = record?.submission_id;
  if (!submissionId) {
    return { ok: false, message: `No live submission ID is stored for ${record?.document_name || 'this request'}.` };
  }

  const submission = await client.getSubmission(submissionId);
  const docs = await client.getSubmissionDocuments(submissionId, true);
  const documents = Array.isArray(docs?.documents) ? docs.documents : [];
  let archivePath = null;
  let driveFile = null;

  if (submission?.combined_document_url || documents.length) {
    const first = submission?.combined_document_url
      ? { url: submission.combined_document_url, filename: `${record?.document_name || submission?.name || 'signed-document'}.pdf` }
      : documents[0];
    archivePath = await withTimeout(() => downloadUrlToTemp(first.url, path.join(__dirname, '../../temp/docuseal'), first.filename || `${record?.document_name || 'signed-document'}.pdf`), parseInt(process.env.DOCUSEAL_DOWNLOAD_TIMEOUT_MS || '15000', 10), 'DocuSeal download signed PDF');
    const driveFolderId = String(process.env.DOCUSEAL_ARCHIVE_DRIVE_FOLDER_ID || '').trim();
    if (driveFolderId) {
      driveFile = await withTimeout(() => archiveCompletedPdfToDrive({
        localPath: archivePath,
        folderId: driveFolderId,
        documentName: first.filename || record?.document_name || 'signed-document'
      }), parseInt(process.env.GOOGLE_DRIVE_TIMEOUT_MS || '15000', 10), 'DocuSeal archive to Google Drive');
    }
  }

  if (context?.db && record?.id) {
    await updateSignatureRecord(context.db, record.id, {
      status: 'archived',
      completed_at: submission.completed_at || record.completed_at || null,
      archive_path: archivePath || record.archive_path || null,
      drive_file_id: driveFile?.id || record.drive_file_id || null,
      raw_provider_response_json: submission
    });
  }

  return {
    ok: true,
    message: [
      'DocuSeal archive complete.',
      '',
      `Document: ${record?.document_name || submission?.name || 'unknown'}`,
      `Submission ID: ${submissionId}`,
      archivePath ? `Local archive: ${archivePath}` : 'Local archive: not available',
      driveFile?.id ? `Google Drive file ID: ${driveFile.id}` : 'Google Drive archive: skipped or unavailable'
    ].join('\n')
  };
}

async function queueApprovalForLiveAction(context, actionType, request, extra = {}) {
  if (!context?.autonomousEngine || typeof context.autonomousEngine.queueApproval !== 'function') {
    return null;
  }

  return context.autonomousEngine.queueApproval(actionType, {
    request,
    ...extra
  }, {
    reason: extra.reason || 'Owner approval required before sending a live DocuSeal action.',
    summary: extra.summary || `Review DocuSeal request for ${request.documentReference || 'unknown document'}.`
  });
}

async function handleCreateRequest(request, context) {
  const config = getDocusealConfig();
  const validation = validateSignatureRequest(request);
  if (!validation.ok) {
    if (isLiveModeEnabled(config)) {
      return {
        response: [
          'DocuSeal request validation failed.',
          '',
          ...(validation.errors.length ? validation.errors.map((error) => `- ${error}`) : ['- Please supply a document and at least one signer.']),
          ...(validation.missing.length ? [`Missing: ${validation.missing.join(', ')}`] : [])
        ].join('\n')
      };
    }

    return {
      response: buildPreviewMessage(request, {
        liveMode: false,
        missing: validation.missing,
        errors: validation.errors
      })
    };
  }

  if (!isLiveModeEnabled(config)) {
    return {
      response: buildPreviewMessage(request, {
        liveMode: false,
        operationLabel: 'dry-run',
        missing: [],
        errors: validation.errors
      }) + '\n\n' + buildSetupMessage()
    };
  }

  if (!hasDocuSealConfig(config)) {
    return {
      response: buildSetupMessage()
    };
  }

  const artifacts = await resolveDocusealArtifacts(request);
  if (!artifacts.ok) {
    return { response: artifacts.message };
  }

  if (!isApprovalQueueAvailable(context)) {
    return {
      response: [
        'Owner approval is required before sending a live DocuSeal request.',
        '',
        'Serena detected live mode, but the autonomous approval queue is unavailable.',
        'She can still prepare a dry-run preview safely.'
      ].join('\n')
    };
  }

  let recordId = null;
  try {
    recordId = await ensureRecordForRequest(context.db, request, context);
  } catch (error) {
    logger.warn(`[ESIGN] Could not store request draft: ${error.message}`);
  }

  let queueId = null;
  try {
    queueId = await queueApprovalForLiveAction(context, 'docuseal_signature_request', request, {
      recordId,
      reason: 'Live e-signature request requested by an owner.',
      summary: `Send ${request.documentReference} to ${request.signers.map((signer) => signer.name).join(', ')} for signature.`
    });
  } catch (error) {
    logger.warn(`[ESIGN] Could not queue live request: ${error.message}`);
    return {
      response: 'Owner approval is required before sending, but the approval queue is unavailable right now.'
    };
  }

  if (!queueId) {
    return {
      response: buildLiveModeBlockedMessage()
    };
  }

  return {
    response: [
      'DocuSeal live request queued for owner approval.',
      '',
      `Queue ID: ${queueId}`,
      `Record ID: ${recordId || 'not stored'}`,
      `Document: ${request.documentReference}`,
      `Signers: ${request.signers.map((signer) => signer.name).join(', ')}`,
      artifacts.fieldPlan?.placement
        ? `Detected signature placement: page ${artifacts.fieldPlan.placement.page} @ x=${artifacts.fieldPlan.placement.x}, y=${artifacts.fieldPlan.placement.y}, w=${artifacts.fieldPlan.placement.w}, h=${artifacts.fieldPlan.placement.h}`
        : 'Detected signature placement: unavailable',
      artifacts.fieldPlan?.fields?.find((field) => field.type === 'date')
        ? (() => {
            const dateField = artifacts.fieldPlan.fields.find((field) => field.type === 'date');
            const area = dateField.areas[0];
            return `Detected date placement: page ${area.page} @ x=${area.x}, y=${area.y}, w=${area.w}, h=${area.h}`;
          })()
        : 'Detected date placement: unavailable',
      `Confidence: ${artifacts.fieldPlan?.confidence || 'medium'} (${artifacts.fieldPlan?.method || 'text extraction'})`,
      '',
      'Serena has not sent the document yet.'
    ].join('\n')
  };
}

async function handleStatusRequest(identifier, context) {
  const record = await loadRecord(context, identifier);
  const config = getDocusealConfig();
  if (!record && !isDocusealReady(config)) {
    return {
      response: `No signature request found for "${identifier}".`
    };
  }

  if (record?.submission_id && isDocusealReady(config)) {
    try {
      const status = await fetchStatusFromProvider(record, context);
      if (status.ok) {
        return { response: normalizeStatusText(record, status.submission, status.submitters) };
      }
      return { response: status.message };
    } catch (error) {
      logger.warn(`[ESIGN] Status fetch failed: ${error.message}`);
    }
  }

  if (!record) {
    return { response: `No signature request found for "${identifier}".` };
  }

  let signers = [];
  try {
    signers = JSON.parse(record.signers_json || '[]');
  } catch (_) {}

  return {
    response: normalizeStatusText(record, null, signers)
  };
}

async function handleReminderRequest(identifier, context) {
  const record = await loadRecord(context, identifier);
  if (!record) {
    return { response: `No signature request found for "${identifier}".` };
  }

  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return {
      response: [
        `Reminder preview for ${record.document_name}.`,
        '',
        'DocuSeal live mode is disabled or credentials are missing, so no reminder was sent.'
      ].join('\n')
    };
  }

  const result = await remindPendingSigners(record);
  if (context.db && record?.id && result.ok) {
    await updateSignatureRecord(context.db, record.id, {
      status: record.status || 'sent',
      raw_provider_response_json: { reminder: true, at: new Date().toISOString() }
    });
  }
  return { response: result.ok ? result.message : result.message };
}

async function handleArchiveRequest(identifier, context) {
  const record = await loadRecord(context, identifier);
  if (!record) {
    return { response: `No signature request found for "${identifier}".` };
  }

  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return {
      response: [
        `Archive preview for ${record.document_name}.`,
        '',
        'DocuSeal live mode is disabled or credentials are missing, so no archive action was sent.'
      ].join('\n')
    };
  }

  const result = await archiveCompletedSubmission(record, context);
  return { response: result.message };
}

async function handleCancelRequest(request, context) {
  const record = await loadRecord(context, request.identifier || request.documentReference);
  if (!record && !request.identifier && !request.documentReference) {
    return { response: 'No document was provided to cancel.' };
  }

  const config = getDocusealConfig();
  if (!isDocusealReady(config)) {
    return {
      response: [
        `Cancellation preview for ${record?.document_name || request.documentReference || 'unknown document'}.`,
        '',
        'DocuSeal live mode is disabled or credentials are missing, so the cancellation was not sent.'
      ].join('\n')
    };
  }

  if (!isApprovalQueueAvailable(context)) {
    return {
      response: 'Owner approval is required before cancelling a live signature request, but the autonomous approval queue is unavailable.'
    };
  }

  const recordId = record?.id || null;
  let queueId = null;
  try {
    queueId = await queueApprovalForLiveAction(context, 'docuseal_signature_cancel', request, {
      recordId,
      reason: 'Cancel a live e-signature request by owner request.',
      summary: `Cancel the DocuSeal request for ${record?.document_name || request.documentReference || 'unknown document'}.`
    });
  } catch (error) {
    logger.warn(`[ESIGN] Could not queue cancellation: ${error.message}`);
    return {
      response: 'Owner approval is required before cancelling, but the approval queue is unavailable right now.'
    };
  }

  return {
    response: queueId
      ? `Cancellation queued for owner approval.\n\nQueue ID: ${queueId}\nDocument: ${record?.document_name || request.documentReference || 'unknown'}`
      : buildLiveModeBlockedMessage()
  };
}

async function handleDirectApprovalExecution(payload, context, operation) {
  const request = payload.request || parseSignatureRequest('', 'SIGNATURE REQUEST:');
  const recordId = payload.recordId || null;
  const record = recordId ? await loadRecord(context, recordId) : await loadRecord(context, request.documentReference);

  if (operation === 'create') {
    return executeLiveCreate(request, context, recordId || record?.id || null);
  }

  if (operation === 'cancel') {
    return executeLiveCancel(request, context, record || null);
  }

  return {
    ok: false,
    message: 'Unsupported DocuSeal approval action.'
  };
}

module.exports = {
  id: '85-esignature',
  name: 'DocuSeal E-Signature',
  description: 'Prepare, preview, request, remind, archive, and cancel DocuSeal signature workflows safely.',
  triggers: ['ESIGN:', 'SIGN PDF:', 'SIGNATURE REQUEST:', 'SIGNATURE STATUS:', 'SIGNATURE REMINDER:', 'SIGNATURE ARCHIVE:', 'SIGNATURE CANCEL:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_85_esignature',
      description: 'Prepare and manage DocuSeal signature requests safely, with dry-run preview or owner-approved live sending.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['ESIGN:', 'SIGN PDF:', 'SIGNATURE REQUEST:', 'SIGNATURE STATUS:', 'SIGNATURE REMINDER:', 'SIGNATURE ARCHIVE:', 'SIGNATURE CANCEL:']
          },
          payload: { type: 'string' }
        },
        required: ['trigger']
      }
    }
  },

  install: async function install({ autonomousEngine, db } = {}) {
    if (db) {
      await ensureSignatureTable(db).catch((error) => logger.warn(`[ESIGN] Could not ensure signature table during install: ${error.message}`));
    }

    if (!autonomousEngine || typeof autonomousEngine.registerActionExecutor !== 'function') {
      return;
    }

    autonomousEngine.registerActionExecutor('docuseal_signature_request', async (payload, queueRow, engine) => {
      const context = { db: engine?.db || db };
      return handleDirectApprovalExecution(payload, context, 'create');
    });

    autonomousEngine.registerActionExecutor('docuseal_signature_cancel', async (payload, queueRow, engine) => {
      const context = { db: engine?.db || db };
      return handleDirectApprovalExecution(payload, context, 'cancel');
    });
  },

  async execute(payload, context) {
    try {
      if (!isOwner(context)) {
        return { response: buildOwnerOnlyMessage() };
      }

      const docusealConfig = getDocusealConfig();
      logDocusealConfig(docusealConfig);

      if (context.db) {
        await ensureSignatureTable(context.db).catch((error) => logger.warn(`[ESIGN] Table setup skipped: ${error.message}`));
      }

      const request = parseSignatureRequest(payload, context.triggerUsed);

      if (looksLikeSelfSigningRequest(request.source)) {
        return {
          response: '❌ Serena cannot sign documents on behalf of anyone. She can only prepare and send requests to the real signers.'
        };
      }

      if (request.operation === 'status') {
        const identifier = normalizeText(payload) || request.documentReference;
        if (!identifier) {
          return { response: 'Usage: SIGNATURE STATUS: document name or submission ID' };
        }
        return handleStatusRequest(identifier, context);
      }

      if (request.operation === 'reminder') {
        const identifier = normalizeText(payload) || request.documentReference;
        if (!identifier) {
          return { response: 'Usage: SIGNATURE REMINDER: document name or submission ID' };
        }
        return handleReminderRequest(identifier, context);
      }

      if (request.operation === 'archive') {
        const identifier = normalizeText(payload) || request.documentReference;
        if (!identifier) {
          return { response: 'Usage: SIGNATURE ARCHIVE: document name or submission ID' };
        }
        return handleArchiveRequest(identifier, context);
      }

      if (request.operation === 'cancel') {
        request.identifier = normalizeText(payload) || request.documentReference;
        return handleCancelRequest(request, context);
      }

      const validation = validateSignatureRequest(request);
      if (!validation.ok || !request.documentReference) {
        if (isLiveModeEnabled(docusealConfig)) {
          return {
            response: [
              'DocuSeal request validation failed.',
              '',
              ...(validation.errors.length ? validation.errors.map((error) => `- ${error}`) : ['- Please supply a document and at least one signer.']),
              ...(validation.missing.length ? [`Missing: ${validation.missing.join(', ')}`] : [])
            ].join('\n')
          };
        }

        return {
          response: buildPreviewMessage(request, {
            liveMode: false,
            missing: validation.missing,
            errors: validation.errors.length ? validation.errors : ['Please supply a document and at least one signer.']
          })
        };
      }

      if (!isLiveModeEnabled(docusealConfig)) {
        return {
          response: buildPreviewMessage(request, {
            liveMode: isLiveModeEnabled(docusealConfig),
            operationLabel: 'dry-run',
            missing: validation.missing,
            errors: validation.errors
          }) + '\n\n' + buildSetupMessage()
        };
      }

      if (!hasDocuSealConfig(docusealConfig)) {
        return {
          response: buildSetupMessage()
        };
      }

      return handleCreateRequest(request, context);
    } catch (error) {
      logger.error(`[ESIGN] Error: ${error.message}`);
      return { response: `❌ DocuSeal e-signature failed: ${error.message}` };
    }
  },

  __test: {
    getDocusealConfig,
    logDocusealConfig,
    isDocusealReady,
    parseSignatureRequest,
    validateSignatureRequest,
    ensureSignatureTable,
    findSignatureRecord,
    createDocusealClient,
    isLiveModeEnabled,
    hasDocuSealConfig,
    looksLikeSelfSigningRequest,
    buildPreviewMessage,
    buildSetupMessage,
    buildLiveModeBlockedMessage,
    executeLiveCreate,
    executeLiveCancel,
    handleCreateRequest,
    handleStatusRequest,
    handleReminderRequest,
    handleArchiveRequest,
    handleCancelRequest
  }
};
