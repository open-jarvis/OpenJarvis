const logger = require('../helpers/logger');
const clickup = require('../helpers/clickup');
const clickupMcp = require('../helpers/clickup-mcp');

let generateStructuredOutput = null;
try {
  ({ generateStructuredOutput } = require('../helpers/structured-output'));
} catch (_) {}

const TRIGGERS = [
  'CU SETUP',
  'CU WORKSPACES',
  'CU WORKSPACES:',
  'CU LIST SPACES',
  'CU LIST SPACES:',
  'CU SPACES:',
  'CU LIST',
  'CU LIST:',
  'CU STRUCTURE',
  'CU STRUCTURE:',
  'CU FOLDERS',
  'CU FOLDERS:',
  'CU LISTS',
  'CU LISTS:',
  'CU CREATE SPACE:',
  'CU UPDATE SPACE:',
  'CU DELETE SPACE:',
  'CU CREATE FOLDER:',
  'CU UPDATE FOLDER:',
  'CU DELETE FOLDER:',
  'CU CREATE LIST:',
  'CU UPDATE LIST:',
  'CU DELETE LIST:',
  'CU LIST TASKS',
  'CU LIST TASKS:',
  'CU TASK:',
  'TASK:',
  'CU CREATE TASK:',
  'CU UPDATE:',
  'CU DELETE TASK:',
  'CU SUBTASK:',
  'CU MCP SEARCH:',
  'CU MCP REPORT:',
  'CU MCP COMMENT:',
  'CU MCP TIME:',
  'CU ASK:'
];

function isConfigured() {
  return Boolean(String(process.env.CLICKUP_API_KEY || '').trim());
}

function configMessage() {
  return (
    '⚠️ *ClickUp not configured*\n\n' +
    'Add these to `.env`:\n' +
    '• `CLICKUP_API_KEY=...`\n' +
    '• `CLICKUP_TEAM_ID=...`\n\n' +
    'Optional:\n' +
    '• `CLICKUP_DEFAULT_SPACE=...`\n' +
    '• `CLICKUP_MCP_ENABLED=true`\n' +
    '• `CLICKUP_MCP_SERVER_URL=https://mcp.clickup.com/mcp`'
  );
}

function sanitizeLine(value) {
  return String(value || '').replace(/[*_`]/g, '').trim();
}

function parseLooseFields(text) {
  const source = String(text || '').trim();
  const out = {};
  if (!source) return out;
  for (const segment of source.split('|')) {
    const part = segment.trim();
    const m = part.match(/^([A-Za-z][A-Za-z0-9 _-]+)\s*=\s*(.+)$/);
    if (!m) continue;
    const key = m[1].trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
    out[key] = m[2].trim();
  }
  return out;
}

function formatWorkspaces(teams) {
  if (!teams.length) return 'No ClickUp workspaces are visible to the configured credentials.';
  return teams.map((team) => `• ${sanitizeLine(team.name)} — \`${team.id}\``).join('\n');
}

function formatSpaces(spaces) {
  if (!spaces.length) return 'No spaces found.';
  return spaces.map((space) => `• ${sanitizeLine(space.name)} — \`${space.id}\``).join('\n');
}

function formatTree(tree) {
  if (!tree.length) return 'No spaces found.';
  return tree.map((space) => {
    const lines = [`• *${sanitizeLine(space.name)}* — \`${space.id}\``];
    if (space.lists?.length) {
      lines.push(...space.lists.map((list) => `  - list: ${sanitizeLine(list.name)} — \`${list.id}\``));
    }
    if (space.folders?.length) {
      for (const folder of space.folders) {
        lines.push(`  - folder: ${sanitizeLine(folder.name)} — \`${folder.id}\``);
        if (folder.lists?.length) {
          lines.push(...folder.lists.map((list) => `    · list: ${sanitizeLine(list.name)} — \`${list.id}\``));
        }
      }
    }
    return lines.join('\n');
  }).join('\n\n');
}


function stripCodeFences(text) {
  return String(text || '').replace(/^```(?:json)?/i, '').replace(/```$/i, '').trim();
}

function safeParseMcpJson(raw) {
  const text = stripCodeFences(raw);
  if (!text) return null;

  const candidates = [
    text,
    text.replace(/,\s*([}\]])/g, '$1'),
    text.replace(/:\s*,/g, ': null,').replace(/,\s*([}\]])/g, '$1'),
    text.replace(/"assignees"\s*:\s*,/g, '"assignees": null,').replace(/,\s*([}\]])/g, '$1')
  ];

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch (_) {}
  }

  return null;
}

function formatTimestamp(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return null;
  try {
    return new Date(num).toISOString().replace('T', ' ').replace('.000Z', ' UTC');
  } catch (_) {
    return null;
  }
}

function humanizeHierarchy(item = {}) {
  const hierarchy = item.hierarchy || {};
  const parts = [];
  if (hierarchy.project?.name) parts.push(sanitizeLine(hierarchy.project.name));
  if (hierarchy.category?.name) parts.push(sanitizeLine(hierarchy.category.name));
  if (hierarchy.subcategory?.name) parts.push(sanitizeLine(hierarchy.subcategory.name));
  return parts.join(' / ');
}

function formatSingleMcpItem(item) {
  const lines = [];
  const itemType = sanitizeLine(item.type || 'item');
  if (item.name) lines.push(`• ${itemType}: ${sanitizeLine(item.name)}`);
  if (item.status) lines.push(`  Status: ${sanitizeLine(item.status)}`);
  const hierarchy = humanizeHierarchy(item);
  if (hierarchy) lines.push(`  Location: ${hierarchy}`);
  if (item.id) lines.push(`  ID: \`${item.id}\``);
  if (item.dateUpdated) {
    const ts = formatTimestamp(item.dateUpdated);
    if (ts) lines.push(`  Updated: ${ts}`);
  }
  if (item.url) lines.push(`  Link: ${item.url}`);
  return lines.join('\n');
}

function formatMcpResultForTelegram(kind, raw) {
  const parsed = typeof raw === 'string' ? safeParseMcpJson(raw) : raw;
  if (!parsed || typeof parsed !== 'object') {
    return `🤖 *ClickUp MCP result*\n\n${String(raw || '').trim() || 'No readable result returned.'}`;
  }

  const resultRows = Array.isArray(parsed.results)
    ? parsed.results
    : Array.isArray(parsed.items)
      ? parsed.items
      : parsed.results && typeof parsed.results === 'object'
        ? [parsed.results]
        : [];

  const overview = sanitizeLine(parsed.overview || '');
  const headerByKind = {
    search: '🔎 *ClickUp search result*',
    answer: '🧠 *ClickUp answer*',
    report: '🧾 *ClickUp report*',
    comment: '💬 *ClickUp comment result*',
    time: '⏱️ *ClickUp time result*'
  };
  const header = headerByKind[String(kind || '').toLowerCase()] || '🤖 *ClickUp MCP result*';

  const parts = [header];

  if (overview) parts.push('', overview);
  if (resultRows.length) {
    parts.push('', ...resultRows.slice(0, 10).map(formatSingleMcpItem));
  } else if (parsed.summary) {
    parts.push('', sanitizeLine(parsed.summary));
  } else if (parsed.message) {
    parts.push('', sanitizeLine(parsed.message));
  }

  if (parsed.nextcursor) parts.push('', 'More results are available.');
  return parts.join('\n');
}

function summarizeItem(label, item) {
  const parts = [`✅ *${label}*`, '', `• Name: ${sanitizeLine(item.name || item.title || '—')}`];
  if (item.id) parts.push(`• ID: \`${item.id}\``);
  if (item.url) parts.push(`• URL: ${item.url}`);
  return parts.join('\n');
}

async function parseOperationRequest(payload, context) {
  if (!generateStructuredOutput) return null;
  return generateStructuredOutput(context, {
    logLabel: 'clickup-operation-parse',
    reasoningEffort: 'medium',
    systemPrompt: 'Extract a ClickUp operation request from the user instruction. Infer only one primary operation. If the user refers to folders as sublists, map that to folder. If the user asks for list creation inside a folder, include folderName or folderId.',
    userPrompt: `User request: ${payload}\n\nReturn JSON for the ClickUp request.`,
    schema: {
      type: 'object',
      required: ['operation'],
      properties: {
        operation: { type: 'string', enum: ['list_workspaces','list_spaces','list_structure','create_space','update_space','delete_space','create_folder','update_folder','delete_folder','create_list','update_list','delete_list','list_tasks','create_task','update_task','delete_task','create_subtask','mcp_search','mcp_report','mcp_comment','mcp_time','mcp_answer','status'] },
        workspaceId: { type: 'string' }, workspaceName: { type: 'string' },
        spaceId: { type: 'string' }, spaceName: { type: 'string' },
        folderId: { type: 'string' }, folderName: { type: 'string' },
        listId: { type: 'string' }, listName: { type: 'string' },
        taskId: { type: 'string' }, taskName: { type: 'string' }, parentTaskId: { type: 'string' },
        name: { type: 'string' }, newName: { type: 'string' }, description: { type: 'string' }, status: { type: 'string' },
        priority: { type: 'integer' }, dueDate: { type: 'string' }, includeClosed: { type: 'boolean' },
        query: { type: 'string' }, question: { type: 'string' }, comment: { type: 'string' }, rawSummary: { type: 'string' }
      }
    }
  }).catch(() => null);
}

function normalizeTriggerPayload(trigger, payload) {
  const upper = String(trigger || '').trim().toUpperCase();
  const cleanPayload = String(payload || '').trim();
  const fields = parseLooseFields(cleanPayload);

  switch (upper) {
    case 'CU SETUP':
      return { operation: 'status', rawSummary: cleanPayload };
    case 'CU WORKSPACES':
    case 'CU WORKSPACES:':
      return { operation: 'list_workspaces', rawSummary: cleanPayload };
    case 'CU LIST SPACES':
    case 'CU LIST SPACES:':
    case 'CU SPACES:':
      return { operation: 'list_spaces', workspaceId: fields.workspaceid || fields.teamid || undefined, workspaceName: fields.workspace || fields.team || undefined, rawSummary: cleanPayload };
    case 'CU LIST':
    case 'CU LIST:':
    case 'CU STRUCTURE':
    case 'CU STRUCTURE:':
    case 'CU FOLDERS':
    case 'CU FOLDERS:':
    case 'CU LISTS':
    case 'CU LISTS:':
      return { operation: 'list_structure', workspaceId: fields.workspaceid || fields.teamid || undefined, workspaceName: fields.workspace || fields.team || undefined, rawSummary: cleanPayload };
    case 'CU CREATE SPACE:':
      return { operation: 'create_space', workspaceId: fields.workspaceid || fields.teamid || undefined, name: fields.name || cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU UPDATE SPACE:':
      return { operation: 'update_space', workspaceId: fields.workspaceid || fields.teamid || undefined, spaceId: fields.spaceid || undefined, spaceName: fields.space || fields.name || undefined, newName: fields.newname || fields.rename || undefined, rawSummary: cleanPayload };
    case 'CU DELETE SPACE:':
      return { operation: 'delete_space', workspaceId: fields.workspaceid || fields.teamid || undefined, spaceId: fields.spaceid || cleanPayload || undefined, spaceName: fields.space || fields.name || undefined, rawSummary: cleanPayload };
    case 'CU CREATE FOLDER:':
      return { operation: 'create_folder', spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderName: fields.folder || fields.name || cleanPayload || undefined, name: fields.folder || fields.name || cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU UPDATE FOLDER:':
      return { operation: 'update_folder', spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderId: fields.folderid || undefined, folderName: fields.folder || fields.name || undefined, newName: fields.newname || fields.rename || undefined, rawSummary: cleanPayload };
    case 'CU DELETE FOLDER:':
      return { operation: 'delete_folder', spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderId: fields.folderid || cleanPayload || undefined, folderName: fields.folder || fields.name || undefined, rawSummary: cleanPayload };
    case 'CU CREATE LIST:':
      return { operation: 'create_list', spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderId: fields.folderid || undefined, folderName: fields.folder || undefined, listName: fields.name || fields.list || cleanPayload || undefined, name: fields.name || fields.list || cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU UPDATE LIST:':
      return { operation: 'update_list', listId: fields.listid || undefined, listName: fields.list || fields.name || undefined, spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderId: fields.folderid || undefined, folderName: fields.folder || undefined, newName: fields.newname || fields.rename || undefined, rawSummary: cleanPayload };
    case 'CU DELETE LIST:':
      return { operation: 'delete_list', listId: fields.listid || cleanPayload || undefined, listName: fields.list || fields.name || undefined, spaceId: fields.spaceid || undefined, spaceName: fields.space || undefined, folderId: fields.folderid || undefined, folderName: fields.folder || undefined, rawSummary: cleanPayload };
    case 'CU LIST TASKS':
    case 'CU LIST TASKS:':
      return { operation: 'list_tasks', listId: fields.listid || cleanPayload || undefined, listName: fields.list || fields.name || undefined, includeClosed: /include\s*closed/i.test(cleanPayload), rawSummary: cleanPayload };
    case 'CU TASK:':
    case 'TASK:':
    case 'CU CREATE TASK:':
      return { operation: 'create_task', listId: fields.listid || undefined, listName: fields.list || undefined, taskName: fields.task || fields.name || cleanPayload || undefined, name: fields.task || fields.name || cleanPayload || undefined, description: fields.description || undefined, status: fields.status || undefined, rawSummary: cleanPayload };
    case 'CU UPDATE:':
      return { operation: 'update_task', taskId: fields.taskid || undefined, taskName: fields.task || fields.name || undefined, listId: fields.listid || undefined, listName: fields.list || undefined, status: fields.status || undefined, newName: fields.newname || fields.rename || undefined, description: fields.description || undefined, rawSummary: cleanPayload };
    case 'CU DELETE TASK:':
      return { operation: 'delete_task', taskId: fields.taskid || cleanPayload || undefined, taskName: fields.task || fields.name || undefined, listId: fields.listid || undefined, listName: fields.list || undefined, rawSummary: cleanPayload };
    case 'CU SUBTASK:':
      return { operation: 'create_subtask', listId: fields.listid || undefined, listName: fields.list || undefined, parentTaskId: fields.parenttaskid || fields.parentid || undefined, taskName: fields.task || fields.name || cleanPayload || undefined, name: fields.task || fields.name || cleanPayload || undefined, description: fields.description || undefined, rawSummary: cleanPayload };
    case 'CU MCP SEARCH:':
      return { operation: 'mcp_search', query: cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU MCP REPORT:':
      return { operation: 'mcp_report', query: cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU MCP COMMENT:':
      return { operation: 'mcp_comment', comment: cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU MCP TIME:':
      return { operation: 'mcp_time', query: cleanPayload || undefined, rawSummary: cleanPayload };
    case 'CU ASK:':
      return { operation: 'mcp_answer', question: cleanPayload || undefined, rawSummary: cleanPayload };
    default:
      return null;
  }
}

async function resolveWorkspaceId(request) {
  if (request.workspaceId) return String(request.workspaceId);
  if (request.workspaceName) {
    const teams = await clickup.getTeams();
    const match = clickup.fuzzyMatch(teams, request.workspaceName);
    if (!match) throw new Error(`Workspace not found: ${request.workspaceName}`);
    return String(match.id);
  }
  return await clickup.getTeamId();
}

async function resolveSpace(request) {
  if (request.spaceId) {
    const space = await clickup.getSpace(request.spaceId);
    return { id: String(space.id), item: space };
  }

  if (request.spaceName) {
    const teamId = await resolveWorkspaceId(request).catch(() => null);
    const space = await clickup.findSpaceByName(request.spaceName, teamId);
    if (!space) throw new Error(`Space not found: ${request.spaceName}`);
    return { id: String(space.id), item: space };
  }

  if (process.env.CLICKUP_DEFAULT_SPACE) {
    return { id: String(process.env.CLICKUP_DEFAULT_SPACE), item: null };
  }

  throw new Error('No space specified. Provide a space name or space ID.');
}

async function resolveFolder(request) {
  if (request.folderId) return { id: String(request.folderId), item: null };
  const space = await resolveSpace(request);
  if (!request.folderName) throw new Error('No folder specified. Provide a folder name or folder ID.');
  const folder = await clickup.findFolderByName(space.id, request.folderName);
  if (!folder) throw new Error(`Folder not found: ${request.folderName}`);
  return { id: String(folder.id), item: folder, spaceId: space.id };
}

async function resolveList(request) {
  if (request.listId) return { id: String(request.listId), item: null };

  if (request.folderId || request.folderName) {
    const folder = await resolveFolder(request);
    const list = await clickup.findListByName(request.listName, { folderId: folder.id });
    if (!list) throw new Error(`List not found: ${request.listName}`);
    return { id: String(list.id), item: list, folderId: folder.id };
  }

  if (request.spaceId || request.spaceName || request.listName) {
    const spaceId = request.spaceId || (await resolveSpace(request)).id;
    const list = await clickup.findListByName(request.listName, { spaceId });
    if (!list) throw new Error(`List not found: ${request.listName}`);
    return { id: String(list.id), item: list, spaceId };
  }

  throw new Error('No list specified. Provide a list name or list ID.');
}

async function resolveTask(request) {
  if (request.taskId) return { id: String(request.taskId), item: null };
  if (!request.taskName) throw new Error('No task specified. Provide a task name or task ID.');
  const list = await resolveList(request);
  const task = await clickup.findTaskByName(request.taskName, { listId: list.id });
  if (!task) throw new Error(`Task not found: ${request.taskName}`);
  return { id: String(task.id), item: task, listId: list.id };
}

function inferMcpIntent(request) {
  const operation = String(request?.operation || '').trim().toLowerCase();
  if (operation.startsWith('mcp_')) return operation.replace(/^mcp_/, '').replace(/^answer$/, 'answer');
  if (operation === 'status') return 'summary';
  if (operation === 'list_structure' || operation === 'list_workspaces' || operation === 'list_spaces') return 'search';
  return 'answer';
}

async function searchTasksAcrossWorkspace(query, workspaceId) {
  const tree = await clickup.getWorkspaceTree(workspaceId).catch(() => []);
  const tokens = String(query || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
    .slice(0, 6);

  const matches = [];
  const listRefs = [];

  for (const space of tree) {
    for (const list of space.lists || []) {
      listRefs.push({ space: space.name, folder: null, list });
    }
    for (const folder of space.folders || []) {
      for (const list of folder.lists || []) {
        listRefs.push({ space: space.name, folder: folder.name, list });
      }
    }
  }

  for (const ref of listRefs.slice(0, 20)) {
    const tasks = await clickup.getTasks(ref.list.id, { includeClosed: true, includeSubtasks: true }).catch(() => []);
    for (const task of tasks) {
      const haystack = `${task.name || ''} ${task.description || ''}`.toLowerCase();
      if (!tokens.length || tokens.some((token) => haystack.includes(token))) {
        matches.push({
          taskName: task.name,
          taskId: String(task.id),
          listName: ref.list.name,
          folderName: ref.folder,
          spaceName: ref.space,
          status: task?.status?.status || task?.status || 'unknown'
        });
      }
      if (matches.length >= 12) return matches;
    }
  }

  return matches;
}

function formatRestFallback(kind, request, details = {}) {
  const intro = [
    '⚠️ *ClickUp MCP fallback activated*',
    '',
    `Reason: ${details.reason || 'ClickUp MCP was unavailable for this request.'}`
  ];

  if (details.health && details.health.coolingDown) {
    intro.push(`Cooldown: ${Math.ceil(details.health.cooldownMsRemaining / 1000)}s remaining`);
  }

  if (details.health?.lastError) {
    intro.push(`Last MCP error: ${sanitizeLine(details.health.lastError)}`);
  }

  intro.push('');
  intro.push('Using REST-visible ClickUp data instead.');

  const body = [];
  if (details.treeSummary) body.push(details.treeSummary);
  if (details.taskSummary) body.push(details.taskSummary);

  if (!body.length) {
    switch (kind) {
      case 'comment':
        body.push('Comment-style MCP actions are currently unavailable through REST fallback.');
        break;
      case 'time':
        body.push('Time-tracking MCP actions are currently unavailable through REST fallback.');
        break;
      default:
        body.push('REST fallback could not produce more detail for this request.');
        break;
    }
  }

  return [...intro, '', ...body].join('\n');
}

async function buildRestFallback(kind, request) {
  const workspaceId = await resolveWorkspaceId(request).catch(() => null);
  const tree = await clickup.getWorkspaceTree(workspaceId).catch(() => []);
  const treeSummary = `🗂️ *Visible ClickUp structure*\n\n${formatTree(tree)}`;
  let taskSummary = '';

  if (['search', 'answer', 'report', 'summary'].includes(kind)) {
    const query = request.query || request.question || request.rawSummary || '';
    const matches = await searchTasksAcrossWorkspace(query, workspaceId);
    if (matches.length) {
      taskSummary = [
        '📋 *Matching tasks*',
        '',
        ...matches.map((match) => `• ${sanitizeLine(match.taskName)} — ${sanitizeLine(match.status)}\n  ↳ ${sanitizeLine(match.spaceName)}${match.folderName ? ` / ${sanitizeLine(match.folderName)}` : ''} / ${sanitizeLine(match.listName)} — \`${match.taskId}\``)
      ].join('\n');
    }
  }

  return { treeSummary, taskSummary };
}

async function maybeCallClickUpMcp(context, request, forcedIntent = null) {
  const intent = forcedIntent || inferMcpIntent(request);
  const explicitMcpCommand = String(request.operation || '').startsWith('mcp_');
  const decision = clickupMcp.getRoutingDecision(context?.mcpClient, intent, { explicitMcpCommand });

  if (!decision.useMcp) {
    return {
      usedMcp: false,
      decision,
      fallback: await buildRestFallback(intent, request)
    };
  }

  try {
    const prompt = request.rawSummary || request.question || request.comment || request.query || request.operation;
    const result = await clickupMcp.callIntent(context.mcpClient, intent, prompt, {
      query: request.query || request.rawSummary || prompt,
      question: request.question || request.rawSummary || prompt,
      comment: request.comment,
      taskId: request.taskId,
      taskName: request.taskName || request.name,
      listId: request.listId
    }, {
      explicitMcpCommand
    });

    return {
      usedMcp: true,
      decision,
      response: formatMcpResultForTelegram(intent, result)
    };
  } catch (error) {
    const reason = String(error?.message || error || 'Unknown MCP error');
    const fallback = await buildRestFallback(intent, request);
    return {
      usedMcp: false,
      decision: {
        ...clickupMcp.getRoutingDecision(context?.mcpClient, intent, { explicitMcpCommand }),
        reason
      },
      fallback
    };
  }
}

function mergeRequest(primary, secondary) {
  return {
    ...(secondary || {}),
    ...(primary || {})
  };
}

module.exports = {
  id: '43-clickup',
  name: 'ClickUp Command Center',
  description: 'Manage ClickUp workspaces, spaces, folders, lists, tasks, subtasks, and MCP-powered ClickUp queries with resilient MCP→REST fallback routing.',
  triggers: TRIGGERS,
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_43_clickup',
      description: 'Manage ClickUp workspaces, spaces, folders, lists, tasks, and subtasks. Use when the user wants ClickUp structure or CRUD operations.',
      parameters: {
        type: 'object',
        properties: {
          trigger: { type: 'string', enum: TRIGGERS },
          payload: { type: 'string' },
          operation: {
            type: 'string',
            enum: [
              'list_workspaces', 'list_spaces', 'list_structure',
              'create_space', 'update_space', 'delete_space',
              'create_folder', 'update_folder', 'delete_folder',
              'create_list', 'update_list', 'delete_list',
              'list_tasks', 'create_task', 'update_task', 'delete_task', 'create_subtask',
              'mcp_search', 'mcp_report', 'mcp_comment', 'mcp_time', 'mcp_answer',
              'status'
            ]
          },
          workspaceId: { type: 'string' },
          workspaceName: { type: 'string' },
          spaceId: { type: 'string' },
          spaceName: { type: 'string' },
          folderId: { type: 'string' },
          folderName: { type: 'string' },
          listId: { type: 'string' },
          listName: { type: 'string' },
          taskId: { type: 'string' },
          taskName: { type: 'string' },
          parentTaskId: { type: 'string' },
          name: { type: 'string' },
          newName: { type: 'string' },
          description: { type: 'string' },
          status: { type: 'string' },
          priority: { type: 'integer' },
          dueDate: { type: 'string' },
          includeClosed: { type: 'boolean' },
          query: { type: 'string' },
          question: { type: 'string' },
          comment: { type: 'string' },
          rawSummary: { type: 'string' }
        },
        required: []
      }
    }
  },

  async execute(payload, context) {
    try {
      if (!isConfigured()) {
        return { response: configMessage() };
      }

      const trigger = String(context?.triggerUsed || '').trim();
      const triggerRequest = normalizeTriggerPayload(trigger, payload);
      let request = mergeRequest(context?.toolArgs, triggerRequest);

      if ((!request || !request.operation) && payload && String(payload).trim()) {
        request = await parseOperationRequest(payload, context);
      }

      if (!request || !request.operation) {
        request = { operation: 'status' };
      }

      request.rawSummary = request.rawSummary || String(payload || '').trim();

      switch (request.operation) {
        case 'status': {
          const teams = await clickup.getTeams();
          const tree = await clickup.getWorkspaceTree().catch(() => []);
          const mcpStatus = clickupMcp.buildStatus(context?.mcpClient);
          return {
            response: [
              '🧩 *ClickUp connection status*',
              '',
              '• API key: configured',
              `• Default workspace/team: ${process.env.CLICKUP_TEAM_ID || 'auto-discover'}`,
              `• ClickUp MCP: ${mcpStatus.enabled ? 'enabled' : 'disabled'}`,
              `• ClickUp MCP connected: ${mcpStatus.connected ? 'yes' : 'no'}`,
              `• ClickUp MCP URL: ${clickupMcp.getRemoteUrl()}`,
              `• ClickUp MCP tools: ${mcpStatus.toolCount}`,
              `• Workspaces visible: ${teams.length}`,
              `• Spaces visible: ${tree.length}`,
              '',
              'Smart routing layer:',
              `• MCP healthy: ${mcpStatus.routing.healthy ? 'yes' : 'no'}`,
              `• MCP cooling down: ${mcpStatus.routing.coolingDown ? `yes (${Math.ceil(mcpStatus.routing.cooldownMsRemaining / 1000)}s)` : 'no'}`,
              `• Last MCP error: ${sanitizeLine(mcpStatus.routing.lastError || 'none')}`,
              '',
              'Available direct operations:',
              '• list workspaces / spaces / structure',
              '• create, update, delete spaces',
              '• create, update, delete folders',
              '• create, update, delete lists',
              '• create, update, delete tasks and subtasks',
              '',
              'Preferred MCP operations:',
              `• search / Q&A: ${clickupMcp.getPreferences().search ? 'prefer MCP until unstable, then REST-first' : 'prefer REST'}`,
              `• summaries / reports: ${clickupMcp.getPreferences().summaries ? 'prefer MCP until unstable, then REST-first' : 'prefer REST'}`,
              `• comments: ${clickupMcp.getPreferences().comments ? 'prefer MCP until unstable, then REST-first' : 'prefer REST'}`,
              `• time: ${clickupMcp.getPreferences().time ? 'prefer MCP until unstable, then REST-first' : 'prefer REST'}`,
              '• Serena quarantines ClickUp MCP automatically when repeated SSE stream failures are detected.'
            ].join('\n')
          };
        }

        case 'list_workspaces': {
          const teams = await clickup.getTeams();
          return { response: `🏢 *ClickUp workspaces*\n\n${formatWorkspaces(teams)}` };
        }

        case 'list_spaces': {
          const workspaceId = await resolveWorkspaceId(request);
          const spaces = await clickup.getSpaces(workspaceId);
          return { response: `📦 *ClickUp spaces*\n\n${formatSpaces(spaces)}` };
        }

        case 'list_structure': {
          const workspaceId = await resolveWorkspaceId(request).catch(() => null);
          const tree = await clickup.getWorkspaceTree(workspaceId);
          return { response: `🗂️ *ClickUp structure*\n\n${formatTree(tree)}` };
        }

        case 'create_space': {
          const workspaceId = await resolveWorkspaceId(request);
          const name = request.name || request.spaceName;
          if (!name) throw new Error('Provide a space name to create.');
          const created = await clickup.createSpace(name, { teamId: workspaceId });
          return { response: summarizeItem('Space created', created) };
        }

        case 'update_space': {
          const space = await resolveSpace(request);
          const updates = {};
          if (request.newName) updates.name = request.newName;
          if (!Object.keys(updates).length) throw new Error('No space updates supplied.');
          const updated = await clickup.updateSpace(space.id, updates);
          return { response: summarizeItem('Space updated', updated) };
        }

        case 'delete_space': {
          const space = await resolveSpace(request);
          await clickup.deleteSpace(space.id);
          return { response: `✅ *Space deleted*\n\n• ID: \`${space.id}\`` };
        }

        case 'create_folder': {
          const space = await resolveSpace(request);
          const name = request.name || request.folderName;
          if (!name) throw new Error('Provide a folder name to create.');
          const created = await clickup.createFolder(space.id, name);
          return { response: summarizeItem('Folder created', created) };
        }

        case 'update_folder': {
          const folder = await resolveFolder(request);
          const updates = {};
          if (request.newName) updates.name = request.newName;
          if (!Object.keys(updates).length) throw new Error('No folder updates supplied.');
          const updated = await clickup.updateFolder(folder.id, updates);
          return { response: summarizeItem('Folder updated', updated) };
        }

        case 'delete_folder': {
          const folder = await resolveFolder(request);
          await clickup.deleteFolder(folder.id);
          return { response: `✅ *Folder deleted*\n\n• ID: \`${folder.id}\`` };
        }

        case 'create_list': {
          const name = request.name || request.listName;
          if (!name) throw new Error('Provide a list name to create.');
          let created;
          if (request.folderId || request.folderName) {
            const folder = await resolveFolder(request);
            created = await clickup.createFolderList(folder.id, name);
          } else {
            const space = await resolveSpace(request);
            created = await clickup.createList(space.id, name);
          }
          return { response: summarizeItem('List created', created) };
        }

        case 'update_list': {
          const list = await resolveList(request);
          const updates = {};
          if (request.newName) updates.name = request.newName;
          if (!Object.keys(updates).length) throw new Error('No list updates supplied.');
          const updated = await clickup.updateList(list.id, updates);
          return { response: summarizeItem('List updated', updated) };
        }

        case 'delete_list': {
          const list = await resolveList(request);
          await clickup.deleteList(list.id);
          return { response: `✅ *List deleted*\n\n• ID: \`${list.id}\`` };
        }

        case 'list_tasks': {
          const list = await resolveList(request);
          const tasks = await clickup.getTasks(list.id, {
            includeClosed: request.includeClosed === true,
            includeSubtasks: true
          });
          if (!tasks.length) {
            return { response: `📋 *Tasks*\n\nNo tasks found in list \`${list.id}\`.` };
          }
          const lines = tasks.slice(0, 25).map((task) => {
            const status = task?.status?.status || task?.status || 'unknown';
            return `• [${sanitizeLine(status)}] ${sanitizeLine(task.name)} — \`${task.id}\``;
          });
          return { response: `📋 *Tasks (${tasks.length} total)*\n\n${lines.join('\n')}` };
        }

        case 'create_task': {
          const list = await resolveList(request);
          const name = request.name || request.taskName;
          if (!name) throw new Error('Provide a task name to create.');
          const created = await clickup.createTask(list.id, name, {
            description: request.description,
            status: request.status,
            priority: request.priority,
            due_date: request.dueDate
          });
          return { response: summarizeItem('Task created', created) };
        }

        case 'update_task': {
          const task = await resolveTask(request);
          const updates = {};
          if (request.status) updates.status = request.status;
          if (request.newName) updates.name = request.newName;
          if (request.description) updates.description = request.description;
          if (!Object.keys(updates).length) throw new Error('No task updates supplied.');
          const updated = await clickup.updateTask(task.id, updates);
          return { response: summarizeItem('Task updated', updated) };
        }

        case 'delete_task': {
          const task = await resolveTask(request);
          await clickup.deleteTask(task.id);
          return { response: `✅ *Task deleted*\n\n• ID: \`${task.id}\`` };
        }

        case 'create_subtask': {
          const list = await resolveList(request);
          const name = request.name || request.taskName;
          if (!name) throw new Error('Provide a subtask name to create.');
          if (!request.parentTaskId) throw new Error('Provide `ParentTaskId` for the subtask.');
          const created = await clickup.createTask(list.id, name, {
            description: request.description,
            parent: request.parentTaskId,
            status: request.status,
            priority: request.priority
          });
          return { response: summarizeItem('Subtask created', created) };
        }

        case 'mcp_search':
        case 'mcp_report':
        case 'mcp_comment':
        case 'mcp_time':
        case 'mcp_answer': {
          const forcedIntent = inferMcpIntent(request);
          const mcpOutcome = await maybeCallClickUpMcp(context, request, forcedIntent);
          if (mcpOutcome.usedMcp) {
            return { response: mcpOutcome.response };
          }
          return {
            response: formatRestFallback(forcedIntent, request, {
              ...(mcpOutcome.fallback || {}),
              reason: mcpOutcome.decision?.reason,
              health: mcpOutcome.decision?.health
            })
          };
        }

        default:
          return { response: '⚠️ Unknown ClickUp command. Try: `CU SETUP`, `CU WORKSPACES`, `CU LIST SPACES`, `CU STRUCTURE`, `CU TASK:`' };
      }
    } catch (err) {
      logger.error('[CLICKUP] Error: ' + err.message);
      return { response: `❌ ClickUp error: ${err.message}` };
    }
  }
};
