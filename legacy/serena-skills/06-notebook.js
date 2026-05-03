const logger = require('../helpers/logger');
const { spawn } = require('child_process');
const path = require('path');

function runBridge(args) {
  return new Promise((resolve, reject) => {
    const bridgePath = path.join(__dirname, '../../notebooklm-bridge.py');
    const proc = spawn('python', [bridgePath, ...args], {
      timeout: 180000,
      env: process.env
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    proc.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    proc.on('close', (code) => {
      const raw = (stdout || stderr || '').trim();
      if (code !== 0 && !raw) {
        reject(new Error(`Bridge exited with code ${code}`));
        return;
      }

      try {
        resolve(JSON.parse(raw));
      } catch (_) {
        reject(new Error(`Bridge returned invalid JSON: ${raw.substring(0, 300)}`));
      }
    });

    proc.on('error', (err) => {
      reject(new Error(`Failed to start bridge: ${err.message}`));
    });
  });
}

function getValueLine(label, value) {
  return `${label}: ${value || 'not available'}`;
}

function formatStatus(data) {
  const lines = [
    'NotebookLM Hybrid Status',
    '',
    getValueLine('Provider', data.provider?.name),
    getValueLine('Configured vaults', `${data.configured_count}/${data.total_vaults}`),
    getValueLine('Manifest', data.manifestPath),
    getValueLine('Sync file', data.syncStatusPath),
    getValueLine('Output folder', data.outputDir),
  ];

  if (data.duplicateNotebookIds && Object.keys(data.duplicateNotebookIds).length) {
    lines.push('', 'Setup issues:');
    for (const [notebookId, keys] of Object.entries(data.duplicateNotebookIds)) {
      lines.push(`- ${notebookId}: ${keys.join(', ')}`);
    }
  }

  lines.push('', 'Use `VAULT MAP`, `NOTEBOOK SETUP`, `VAULT SYNC STATUS`, `VAULT INVENTORY`, or `VAULT MISSING DOCS` next.');
  return lines.join('\n');
}

function formatVaultMap(data) {
  const lines = [
    'NotebookLM Vault Map',
    '',
    `Configured vaults: ${data.configured_count}/${data.total_vaults}`,
  ];

  for (const [key, vault] of Object.entries(data.vaults || {})) {
    lines.push('');
    lines.push(`*${key}* - ${vault.name}`);
    lines.push(`Purpose: ${vault.description}`);
    lines.push(`Status: ${vault.configured ? 'configured' : 'missing'}`);
    lines.push(`Missing docs: ${vault.missing_document_count}`);
  }

  if (data.duplicateNotebookIds && Object.keys(data.duplicateNotebookIds).length) {
    lines.push('', 'Issue to fix: Core and Business should not share the same notebook ID.');
  }

  return lines.join('\n');
}

function formatSetup(data) {
  const manifest = data.manifest || {};
  const vaults = manifest.vaults || {};
  const lines = [
    'NotebookLM Setup Guide',
    '',
    'Recommended build order:',
    '1. core',
    '2. clinical',
    '3. patient',
    '4. compliance',
    '5. content',
    '6. sales',
    '7. market',
    '8. corporate',
    '9. business',
  ];

  for (const key of Object.keys(vaults)) {
    const vault = vaults[key];
    lines.push('');
    lines.push(`*${vault.name}* (${key})`);
    lines.push(`Purpose: ${vault.description}`);
    lines.push(`Required docs: ${vault.requiredDocuments.join(', ')}`);
  }

  lines.push('', 'Best next step: ask Serena to stage sources, then run `VAULT SYNC`.');
  return lines.join('\n');
}

function formatSyncStatus(data) {
  const lines = [
    'Vault Sync Status',
    '',
    `Configured vaults: ${data.configuredVaults}/${data.totalVaults}`,
    `Missing documents: ${data.totalMissingDocuments}`,
    `Uploaded sources: ${data.totalUploadedSources}`,
    `Staged sources: ${data.totalStagedSources}`,
  ];

  for (const [key, vault] of Object.entries(data.vaults || {})) {
    lines.push('');
    lines.push(`*${key}* - ${vault.name}`);
    lines.push(`Status: ${vault.status}`);
    lines.push(`Missing: ${vault.missingCount} | Uploaded: ${vault.uploadedCount} | Staged: ${vault.stagedCount}`);
  }

  return lines.join('\n');
}

function formatMissingDocs(data) {
  const lines = ['Vault Missing Documents'];
  for (const [key, vault] of Object.entries(data.missing || {})) {
    lines.push('');
    lines.push(`*${key}* - ${vault.name}`);
    if (!vault.missingDocuments.length) {
      lines.push('All required documents accounted for.');
      continue;
    }
    for (const doc of vault.missingDocuments) {
      lines.push(`- ${doc}`);
    }
  }
  return lines.join('\n');
}

function formatInventory(data) {
  const lines = ['Vault Inventory'];

  for (const [key, vault] of Object.entries(data.vaults || {})) {
    lines.push('');
    lines.push(`*${key}* - ${vault.name}`);
    lines.push(`Notebook ID: ${vault.notebookId || 'not configured'}`);
    lines.push(`Missing docs: ${(vault.missingDocuments || []).length}`);

    const staged = vault.stagedSources || [];
    if (!staged.length) {
      lines.push('Staged sources: none');
    } else {
      lines.push('Staged sources:');
      staged.slice(0, 10).forEach((item) => {
        lines.push(`- ${item.documentTitle} [${item.status}]`);
      });
    }
  }

  return lines.join('\n');
}

function formatCreateLayout(data) {
  const lines = ['NotebookLM Layout Build'];
  (data.actions || []).forEach((action) => {
    lines.push('');
    lines.push(`*${action.vault}* - ${action.title}`);
    lines.push(`Action: ${action.action}`);
    if (action.notebookId) {
      lines.push(`Notebook ID: ${action.notebookId}`);
    }
    if (action.reason) {
      lines.push(`Reason: ${action.reason}`);
    }
    if (action.error) {
      lines.push(`Error: ${action.error}`);
    }
  });
  lines.push('', 'Any newly created notebook IDs are saved in the manifest as suggestedNotebookId for review.');
  return lines.join('\n');
}

function formatSyncResult(data) {
  const lines = ['Vault Sync Result'];
  (data.actions || []).forEach((action) => {
    lines.push(`- ${action.vault}: ${action.action}${action.documentTitle ? ` -> ${action.documentTitle}` : ''}`);
  });
  if (data.snapshot) {
    lines.push('', `Remaining missing documents: ${data.snapshot.totalMissingDocuments}`);
  }
  return lines.join('\n');
}

function parseVaultOnly(payload) {
  if (!payload) return null;
  const key = payload.trim().toLowerCase();
  return key || null;
}

function parseStagePayload(payload) {
  const parts = (payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return {
    vault: parts[0] || '',
    title: parts[1] || '',
    source: parts[2] || '',
    status: parts[3] || 'staged'
  };
}

function parseSourcePayload(payload) {
  const parts = (payload || '').split('|').map((part) => part.trim()).filter(Boolean);
  return {
    vault: parts[0] || '',
    source: parts[1] || '',
    title: parts[2] || ''
  };
}

module.exports = {
  id: '06-notebook',
  name: 'NotebookLM Knowledge Brain',
  description: 'Hybrid NotebookLM manager with query, vault layout, sync tracking, and source inventory.',
  triggers: [
    'ASK KNOWLEDGE:',
    'VAULT QUERY:',
    'VAULT STATUS',
    'VAULT MAP',
    'NOTEBOOK SETUP',
    'VAULT SYNC STATUS',
    'VAULT INVENTORY',
    'VAULT INVENTORY:',
    'VAULT MISSING DOCS',
    'VAULT MISSING DOCS:',
    'VAULT STAGE:',
    'VAULT SOURCE ADD:',
    'VAULT SYNC',
    'VAULT CREATE ALL',
    'VAULT AUTOMATION STATUS'
  ],

  execute: async function (payload, context) {
    try {
      logger.info(`[NOTEBOOK] Triggered: ${context.triggerUsed} | payload: ${(payload || '').substring(0, 80)}`);

      if (context.triggerUsed === 'VAULT STATUS') {
        const result = await runBridge(['status']);
        return { response: formatStatus(result) };
      }

      if (context.triggerUsed === 'VAULT MAP') {
        const result = await runBridge(['status']);
        return { response: formatVaultMap(result) };
      }

      if (context.triggerUsed === 'NOTEBOOK SETUP') {
        const result = await runBridge(['manifest']);
        return { response: formatSetup(result) };
      }

      if (context.triggerUsed === 'VAULT SYNC STATUS') {
        const result = await runBridge(['sync_status']);
        return { response: formatSyncStatus(result) };
      }

      if (context.triggerUsed === 'VAULT INVENTORY' || context.triggerUsed === 'VAULT INVENTORY:') {
        const vault = parseVaultOnly(payload);
        const result = await runBridge(vault ? ['inventory', vault] : ['inventory']);
        return { response: formatInventory(result) };
      }

      if (context.triggerUsed === 'VAULT MISSING DOCS' || context.triggerUsed === 'VAULT MISSING DOCS:') {
        const vault = parseVaultOnly(payload);
        const result = await runBridge(vault ? ['missing_docs', vault] : ['missing_docs']);
        return { response: formatMissingDocs(result) };
      }

      if (context.triggerUsed === 'VAULT CREATE ALL') {
        const result = await runBridge(['create_layout']);
        return { response: formatCreateLayout(result) };
      }

      if (context.triggerUsed === 'VAULT AUTOMATION STATUS') {
        const result = await runBridge(['automation_status']);
        return {
          response:
            `NotebookLM Automation Status\n\n` +
            `Provider: ${result.provider?.name}\n` +
            `Browser helper: ${result.browserAutomation?.name}\n` +
            `Configured vaults: ${result.syncSnapshot?.configuredVaults}/${result.syncSnapshot?.totalVaults}\n` +
            `Manifest: ${result.syncSnapshot?.manifestPath}\n\n` +
            `Recommended flow:\n- ${result.recommendedFlow.join('\n- ')}`
        };
      }

      if (context.triggerUsed === 'VAULT STAGE:') {
        const { vault, title, source, status } = parseStagePayload(payload);
        if (!vault || !source) {
          return { response: 'Usage: `VAULT STAGE: vault | document title | source path or URL | staged`' };
        }
        const result = await runBridge(['stage_source', source, vault.toLowerCase(), title, status]);
        return { response: `Staged for ${result.vault}: ${result.item.documentTitle} [${result.item.status}]` };
      }

      if (context.triggerUsed === 'VAULT SOURCE ADD:') {
        const { vault, source, title } = parseSourcePayload(payload);
        if (!vault || !source) {
          return { response: 'Usage: `VAULT SOURCE ADD: vault | source path or URL | optional title`' };
        }
        const result = await runBridge(['add_source', source, vault.toLowerCase(), title]);
        if (!result.success) {
          return { response: `Vault source add failed: ${result.error}` };
        }
        return { response: `Source uploaded to ${result.vault}: ${result.item.documentTitle}` };
      }

      if (context.triggerUsed === 'VAULT SYNC') {
        const vault = parseVaultOnly(payload);
        const result = await runBridge(vault ? ['sync', vault] : ['sync']);
        return { response: formatSyncResult(result) };
      }

      if (!payload || payload.trim().length < 3) {
        return {
          response:
            'NotebookLM Hybrid Commands\n\n' +
            '- `ASK KNOWLEDGE: your question`\n' +
            '- `VAULT STATUS`\n' +
            '- `VAULT MAP`\n' +
            '- `NOTEBOOK SETUP`\n' +
            '- `VAULT SYNC STATUS`\n' +
            '- `VAULT INVENTORY`\n' +
            '- `VAULT MISSING DOCS`\n' +
            '- `VAULT CREATE ALL`\n' +
            '- `VAULT STAGE: vault | document title | source path or URL`\n' +
            '- `VAULT SOURCE ADD: vault | source path or URL | optional title`\n' +
            '- `VAULT SYNC`'
        };
      }

      const query = payload.trim().slice(0, 1000);
      let bridgeResult;

      try {
        bridgeResult = await runBridge(['query', query]);
      } catch (bridgeErr) {
        logger.warn('[NOTEBOOK] Bridge unavailable, falling back to AI: ' + bridgeErr.message);
        if (!context.aiEngine) {
          return { response: 'Both NotebookLM bridge and AI engine are unavailable.' };
        }

        const fallback = await context.aiEngine.chat(
          [{
            role: 'user',
            content:
              'Answer this question about Dr Piet Muller using your best available knowledge:\n\n' +
              query + '\n\n' +
              'State clearly that NotebookLM was unavailable and this is a fallback answer.'
          }],
          { systemPrompt: context.soulFile, temperature: 0.3 }
        );

        return {
          response:
            `Knowledge Query (AI Fallback)\n\n` +
            `${fallback.content}\n\n` +
            `NotebookLM bridge was unavailable during this request.`
        };
      }

      if (!bridgeResult.success) {
        return {
          response:
            `Vault query failed\n\n` +
            `${bridgeResult.error || 'Unknown error'}\n\n` +
            `Run \`VAULT STATUS\` or \`VAULT SYNC STATUS\` for setup detail.`
        };
      }

      return {
        response:
          `Knowledge Answer\n` +
          `Vault: ${bridgeResult.vault_name || bridgeResult.vault}\n\n` +
          `${bridgeResult.answer}\n\n` +
          `Grounded answer from NotebookLM. Verify clinical content against current literature when needed.`
      };
    } catch (err) {
      logger.error('[NOTEBOOK] Error: ' + err.message);
      return { response: `NotebookLM error: ${err.message}` };
    }
  }
};
