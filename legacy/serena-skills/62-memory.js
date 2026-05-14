const logger = require('../helpers/logger');
const memoryService = require('../helpers/memory-service');
const { extractExplicitFacts } = require('../helpers/memory-consolidator');

function normalizeText(value) {
  return String(value || '').trim();
}

function cleanText(value) {
  return String(value || '')
    .replace(/[*_`]/g, '')
    .replace(/\\([_*`[\]()~>#+=|{}.!-])/g, '$1')
    .trim();
}

function titleCaseWords(words = []) {
  return words
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function deriveFallbackKey(part) {
  const words = String(part || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 5);

  return words.length ? `Note: ${titleCaseWords(words)}` : 'Remembered note';
}

function trimAtEmbeddedCommand(text) {
  const source = normalizeText(text);
  if (!source) return source;
  const embedded = /\b(RECALL:|FORGET:|MEMORY LIST|REMEMBER:)\b/ig;
  let match;
  let first = -1;
  while ((match = embedded.exec(source)) !== null) {
    if (match.index > 0) {
      first = match.index;
      break;
    }
  }
  return first === -1 ? source : source.slice(0, first).trim();
}

function buildNaturalFactsFromSentence(text) {
  const source = trimAtEmbeddedCommand(text);
  if (!source) return [];

  const explicit = extractExplicitFacts(source, { isOwner: false }) || [];
  if (explicit.length) {
    return explicit.map((fact) => ({
      key: fact.key,
      value: fact.value,
      scope: fact.userScoped ? 'user' : 'global',
      userScoped: Boolean(fact.userScoped),
      source: fact.source || 'explicit_memory_command',
      tags: Array.isArray(fact.tags) ? fact.tags : ['explicit']
    }));
  }

  const parts = source
    .split(/[.;]\s+/)
    .map((part) => part.trim())
    .filter(Boolean);

  const facts = [];

  for (const part of parts) {
    let matched = false;

    const prefers = part.match(/^([A-Za-z][A-Za-z0-9 '._-]{1,50})\s+prefers\s+(.+)$/i);
    if (prefers) {
      facts.push({
        key: `${prefers[1].trim()} preference`,
        value: prefers[2].trim(),
        scope: 'global',
        userScoped: false,
        source: 'preference_statement',
        tags: ['preference']
      });
      matched = true;
    }

    const serves = !matched && part.match(/^Serena\s+serves\s+(.+)$/i);
    if (serves) {
      facts.push({
        key: 'Serena serves',
        value: serves[1].trim(),
        scope: 'global',
        userScoped: false,
        source: 'identity_statement',
        tags: ['identity', 'role']
      });
      matched = true;
    }

    const simpleRule = !matched && part.match(/^(.+?)\s+is\s+(.+)$/i);
    if (simpleRule && /^my\s+/i.test(part) === false) {
      facts.push({
        key: deriveFallbackKey(simpleRule[1]),
        value: simpleRule[2].trim(),
        scope: 'global',
        userScoped: false,
        source: 'statement',
        tags: ['note']
      });
      matched = true;
    }

    if (!matched) {
      facts.push({
        key: deriveFallbackKey(part),
        value: part,
        scope: 'global',
        userScoped: false,
        source: 'freeform_memory_command',
        tags: ['note']
      });
    }
  }

  return facts;
}

async function mirrorFactToMcpMemory(mcpClient, fact) {
  if (!mcpClient) return false;
  const tools = typeof mcpClient.getToolsForServer === 'function' ? mcpClient.getToolsForServer('memory') : [];
  if (!tools || !tools.length) return false;

  const entityName = fact.scope === 'user' && fact.userId
    ? `${fact.key} [user:${fact.userId}]`
    : fact.key;

  try {
    await mcpClient.callTool('create_entities', {
      entities: [{
        name: entityName,
        entityType: 'memory',
        observations: [fact.value]
      }]
    });
    return true;
  } catch (_) {
    return false;
  }
}

function formatMcpMemoryText(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';

  try {
    const parsed = JSON.parse(text);
    const lines = [];
    if (Array.isArray(parsed.entities)) {
      for (const entity of parsed.entities.slice(0, 5)) {
        const observations = Array.isArray(entity.observations) ? entity.observations.join(' | ') : '';
        lines.push(`${cleanText(entity.name)}${observations ? ` = ${cleanText(observations)}` : ''}`);
      }
    }
    if (lines.length) return lines.join('\n');
  } catch (_) {}

  return cleanText(text).slice(0, 1200);
}

async function searchMcpMemory(mcpClient, query) {
  if (!mcpClient) return '';
  try {
    const result = await mcpClient.callToolRaw('search_nodes', { query: String(query || '').trim() }, { timeoutMs: 12000 });
    if (result && Array.isArray(result.content)) {
      const combined = result.content
        .filter((item) => item.type === 'text')
        .map((item) => item.text)
        .join('\n')
        .trim();
      return formatMcpMemoryText(combined);
    }
    if (typeof result === 'string') return formatMcpMemoryText(result);
    return '';
  } catch (_) {
    return '';
  }
}

function formatResultsByType(results = []) {
  const facts = [];
  const entities = [];
  const episodes = [];

  for (const item of results) {
    if (item.kind === 'fact') facts.push(item.value || {});
    else if (item.kind === 'entity') entities.push(item.value || {});
    else if (item.kind === 'episode') episodes.push(item.value || {});
  }

  const sections = [];

  if (facts.length) {
    sections.push('Facts');
    sections.push(...facts.slice(0, 6).map((fact) => `${cleanText(fact.originalKey || fact.key)}: ${cleanText(fact.value)}`));
  }

  if (entities.length) {
    if (sections.length) sections.push('');
    sections.push('Profiles');
    sections.push(...entities.slice(0, 4).map((entity) => {
      const summary = entity.profile?.summary || JSON.stringify(entity.profile || {}).slice(0, 160);
      return `${cleanText(entity.displayName)} (${cleanText(entity.entityType)}): ${cleanText(summary)}`;
    }));
  }

  if (episodes.length) {
    if (sections.length) sections.push('');
    sections.push('Relevant episodes');
    sections.push(...episodes.slice(0, 4).map((episode) => `[${cleanText(episode.createdAt)}] ${cleanText(episode.summary || episode.userText || '')}`));
  }

  return sections.join('\n');
}

function section(title, lines = []) {
  return [cleanText(title), '', ...lines].join('\n');
}

module.exports = {
  id: '62-memory',
  name: 'Persistent Memory',
  description: 'Store and recall structured facts across sessions — preferences, business rules, people, and project state.',
  triggers: ['REMEMBER:', 'RECALL:', 'FORGET:', 'MEMORY LIST'],

  async execute(payload, context) {
    try {
      logger.info(`[MEMORY] Triggered: ${context.triggerUsed} | ${(payload || '').substring(0, 80)}`);

      const text = normalizeText(payload);
      const trigger = String(context.triggerUsed || '').trim();
      const userId = context?.userId ? String(context.userId) : null;

      if (trigger === 'REMEMBER:') {
        if (!text) {
          return {
            response:
              'Remember\n\n' +
              'You can store memory in either format:\n' +
              'REMEMBER: key = value\n' +
              'REMEMBER: Kyle prefers direct technical answers.\n\n' +
              'Examples:\n' +
              'REMEMBER: office hours = Mon-Fri 8am-5pm\n' +
              'REMEMBER: Serena serves Dr Piet Muller’s business operations.'
          };
        }

        const trimmedInput = trimAtEmbeddedCommand(text);
        const facts = [];
        if (trimmedInput.includes('=')) {
          const sepIdx = trimmedInput.indexOf('=');
          const key = trimmedInput.substring(0, sepIdx).trim();
          const value = trimmedInput.substring(sepIdx + 1).trim();
          facts.push({
            key,
            value,
            userId: null,
            scope: 'global',
            source: 'explicit_memory_command',
            tags: ['explicit']
          });
        } else {
          for (const fact of buildNaturalFactsFromSentence(trimmedInput)) {
            facts.push({
              key: fact.key,
              value: fact.value,
              userId: fact.userScoped ? userId : null,
              scope: fact.scope || (fact.userScoped ? 'user' : 'global'),
              source: fact.source || 'freeform_memory_command',
              tags: fact.tags || ['note']
            });
          }
        }

        const stored = [];
        for (const fact of facts) {
          const record = await memoryService.rememberFact({
            key: fact.key,
            value: fact.value,
            userId: fact.userId,
            scope: fact.scope,
            source: fact.source,
            tags: fact.tags
          });
          await mirrorFactToMcpMemory(context?.mcpClient, record);
          stored.push(record);
        }

        return {
          response: [
            'Memory stored',
            '',
            ...stored.map((record) =>
              `${cleanText(record.originalKey || record.key)}: ${cleanText(record.value)}${record.scope === 'user' ? ' (user-scoped)' : ''}`
            ),
            '',
            'Use RECALL: to retrieve it later.'
          ].join('\n')
        };
      }

      if (trigger === 'RECALL:') {
        if (!text || text.length < 2) {
          return { response: 'Usage: RECALL: key or topic' };
        }

        const memoryPrompt = await memoryService.buildPromptContext({
          userId,
          query: text,
          limit: 10
        });

        const localResults = formatResultsByType(memoryPrompt.results || []);
        const mcpResults = await searchMcpMemory(context?.mcpClient, text);

        if (!localResults && !mcpResults) {
          return {
            response: `Nothing relevant found for: "${cleanText(text)}"\n\nUse REMEMBER: to store it first.`
          };
        }

        return {
          response: [
            `Memory recall: ${cleanText(text)}`,
            '',
            localResults ? localResults : null,
            mcpResults ? `MCP memory\n${mcpResults}` : null
          ].filter(Boolean).join('\n\n')
        };
      }

      if (trigger === 'MEMORY LIST') {
        const status = memoryService.getStatus ? memoryService.getStatus() : {};
        const recent = await memoryService.getRecentEpisodes(userId, 5);
        const topMemory = await memoryService.search('', { userId, limit: 25 });
        const factsAndEntities = topMemory.filter((item) => item.kind === 'fact' || item.kind === 'entity');
        const formatted = formatResultsByType(factsAndEntities);

        return {
          response: [
            'Memory bank',
            '',
            `Ready: ${status.ready ? 'yes' : 'no'}`,
            `Facts: ${status.factCount || 0}`,
            `Entities: ${status.entityCount || 0}`,
            `Episodes: ${status.episodeCount || 0}`,
            '',
            formatted || 'No stored facts yet.',
            recent.length ? `\nRecent episodes\n${recent.map((item) => cleanText(item.summary || item.userText || '')).join('\n')}` : ''
          ].join('\n')
        };
      }

      if (trigger === 'FORGET:') {
        if (!text || text.length < 2) {
          return { response: 'Usage: FORGET: key or exact memory label' };
        }

        const candidates = await memoryService.search(text, { userId, limit: 5 });
        const facts = candidates.filter((item) => item.kind === 'fact').map((item) => item.value || {});
        if (!facts.length) {
          return { response: `I could not find a stored memory for "${cleanText(text)}".` };
        }

        for (const fact of facts.slice(0, 3)) {
          await memoryService.rememberFact({
            key: fact.originalKey || fact.key,
            value: '[deleted]',
            userId: fact.userId || null,
            scope: fact.scope || (fact.userId ? 'user' : 'global'),
            source: 'forget_command',
            tags: ['deleted'],
            confidence: 1
          });
        }

        try {
          if (context?.mcpClient) {
            await context.mcpClient.callTool('delete_entities', { entityNames: [text, ...facts.map((fact) => fact.originalKey || fact.key)] });
          }
        } catch (_) {}

        return { response: `Memory deleted: ${cleanText(text)}` };
      }

      return { response: 'Usage: REMEMBER:, RECALL:, MEMORY LIST, FORGET:' };
    } catch (err) {
      logger.error('[MEMORY] Error: ' + err.message);
      return { response: `Memory error: ${err.message}` };
    }
  }
};
