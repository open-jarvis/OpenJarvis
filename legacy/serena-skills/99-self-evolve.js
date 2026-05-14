const fs = require('fs');
const path = require('path');
const Module = require('module');
const logger = require('../helpers/logger');

const ROOT_DIR = path.join(__dirname, '../..');
const MANIFEST_PATH = path.join(ROOT_DIR, 'skill-manifest.json');
const PACKAGE_PATH = path.join(ROOT_DIR, 'package.json');
const BACKUP_DIR = path.join(__dirname, 'backup');
const STATE_PATH = path.join(ROOT_DIR, 'data/self-evolve-state.json');
const LOG_PATHS = [
  path.join(ROOT_DIR, 'logs/agent.log'),
  path.join(ROOT_DIR, 'logs/errors.log')
];

const DEFAULT_TEST_CONTEXT = {
  chatId: 0,
  userId: 0,
  userName: 'SelfTest',
  test: true
};

function ensureState() {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  if (!fs.existsSync(STATE_PATH)) {
    fs.writeFileSync(STATE_PATH, JSON.stringify({
      lastCreationAt: null,
      queue: []
    }, null, 2));
  }
}

function readState() {
  ensureState();
  return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8'));
}

function writeState(state) {
  ensureState();
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

function getOwnerIds(context) {
  const envOwners = String(process.env.OWNER_TELEGRAM_ID || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  const manifestOwners = Object.entries(context.manifest?.allowed_users || {})
    .filter(([, value]) => value.role === 'owner' || value.access === 'full')
    .map(([id]) => id);

  return new Set([...envOwners, ...manifestOwners]);
}

function isOwner(context) {
  return getOwnerIds(context).has(String(context.userId));
}

function readManifest() {
  return JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));
}

function writeManifest(manifest) {
  fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2));
}

function incrementVersion(version) {
  const [major, minor = '0'] = String(version || '1.0').split('.');
  return `${major}.${parseInt(minor, 10) + 1}`;
}

function listAvailablePackages() {
  const pkg = JSON.parse(fs.readFileSync(PACKAGE_PATH, 'utf8'));
  return Object.keys(pkg.dependencies || {}).sort();
}

function findRequiredPackages(code) {
  const matches = new Set();
  const patterns = [
    /require\(['"]([^'"]+)['"]\)/g,
    /from ['"]([^'"]+)['"]/g
  ];

  patterns.forEach((pattern) => {
    let match = pattern.exec(code);
    while (match) {
      matches.add(match[1]);
      match = pattern.exec(code);
    }
  });

  return Array.from(matches);
}

function validateGeneratedCode(code, availablePackages) {
  const bannedPatterns = [
    { regex: /\beval\s*\(/, reason: 'Uses eval()' },
    { regex: /new\s+Function\s*\(/, reason: 'Uses new Function()' },
    { regex: /child_process\s*\.\s*exec/i, reason: 'Uses child_process.exec' },
    { regex: /child_process\s*\.\s*spawn/i, reason: 'Uses child_process.spawn' },
    { regex: /fs\.rmSync\s*\(/, reason: 'Uses fs.rmSync' },
    { regex: /fs\.unlinkSync\s*\(/, reason: 'Uses fs.unlinkSync' }
  ];

  const violations = [];
  bannedPatterns.forEach((rule) => {
    if (rule.regex.test(code)) violations.push(rule.reason);
  });

  const packageSet = new Set(availablePackages);
  const nativeModules = new Set(Module.builtinModules);
  findRequiredPackages(code).forEach((dep) => {
    if (dep.startsWith('.')) return;
    if (!packageSet.has(dep) && !nativeModules.has(dep)) {
      violations.push(`Requires unavailable package: ${dep}`);
    }
  });

  if (!/module\.exports\s*=/.test(code)) {
    violations.push('Missing module.exports');
  }
  if (!/TOOL_DEFINITION/.test(code)) {
    violations.push('Missing TOOL_DEFINITION export');
  }

  return {
    ok: violations.length === 0,
    violations
  };
}

function extractCodeBlock(content) {
  const match = String(content || '').match(/```(?:js|javascript)?\s*([\s\S]*?)```/i);
  return match ? match[1].trim() : String(content || '').trim();
}

function normaliseFileName(rawName) {
  const safe = String(rawName || 'generated-skill')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40) || 'generated-skill';
  return safe.endsWith('.js') ? safe : `${safe}.js`;
}

function inferSkillFileName(description, manifest) {
  const existing = new Set(manifest.active_skills || []);
  let prefix = 70;
  while (existing.has(`${prefix}-${String(description || '').toLowerCase()}`) || existing.has(`${prefix}`)) {
    prefix += 1;
  }

  const slug = normaliseFileName(description).replace(/\.js$/, '');
  return `${prefix}-${slug}.js`;
}

function buildMockContext(context) {
  return {
    ...context,
    ...DEFAULT_TEST_CONTEXT,
    triggerUsed: null,
    bot: null,
    db: context.db,
    test: true
  };
}

async function generateSkillCode(payload, context) {
  const availablePackages = listAvailablePackages();
  const pkg = JSON.parse(fs.readFileSync(PACKAGE_PATH, 'utf8'));

  const response = await context.aiEngine.chat(
    [{
      role: 'user',
      content:
        `Design and write a complete Serena skill for this request:\n${payload}\n\n` +
        `Available npm packages:\n${availablePackages.join(', ')}\n\n` +
        'Return only one production-ready CommonJS JavaScript file. ' +
        'The file must export module.exports with id, name, description, triggers, TOOL_DEFINITION, and execute. ' +
        'Use process.env for secrets. Follow existing Serena skill style.'
    }],
    {
      systemPrompt:
        `${context.soulFile}\n\n` +
        `Project package.json:\n${JSON.stringify(pkg.dependencies || {}, null, 2)}\n\n` +
        'You are Serena’s self-evolution engineer. Produce safe, production-ready code only.',
      reasoningEffort: 'high',
      maxTokens: 3200,
      task: 'skill-generation'
    }
  );

  return {
    code: extractCodeBlock(response.content),
    availablePackages
  };
}

function backupExistingSkill(targetPath) {
  if (!fs.existsSync(targetPath)) return null;
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  const backupPath = path.join(
    BACKUP_DIR,
    `${path.basename(targetPath)}.${Date.now()}.bak`
  );
  fs.copyFileSync(targetPath, backupPath);
  return backupPath;
}

function scanRecentLogs() {
  const lines = [];
  LOG_PATHS.forEach((logPath) => {
    if (!fs.existsSync(logPath)) return;
    const content = fs.readFileSync(logPath, 'utf8').split(/\r?\n/).slice(-250);
    lines.push(...content);
  });
  return lines.slice(-500);
}

async function runGapAnalysis(context) {
  const manifest = readManifest();
  const logLines = scanRecentLogs();
  const failedLines = logLines.filter((line) =>
    /unknown trigger|could not|failed|error|not available|unsupported/i.test(line)
  );

  const response = await context.aiEngine.chat(
    [{
      role: 'user',
      content:
        `Recent Serena log lines:\n${failedLines.join('\n') || 'No recent failures captured.'}\n\n` +
        `Disabled skills:\n${(manifest.disabled_skills || []).join(', ') || 'None'}\n\n` +
        'Business context: South African health and wellness practice running telehealth, memberships, content, compliance, and corporate wellness.\n\n' +
        'Return the top 5 prioritised gaps with columns: priority, suggested_skill_name, effort_estimate, reason.'
    }],
    {
      systemPrompt: `${context.soulFile}\n\nReturn a concise operational report.`,
      reasoningEffort: 'high',
      maxTokens: 1800,
      task: 'gap-analysis'
    }
  );

  return {
    response:
      `🧠 *Gap Analysis*\n\n${response.content}\n\n` +
      `Disabled skills considered: ${(manifest.disabled_skills || []).join(', ') || 'None'}`
  };
}

async function handleSkillStatus(context) {
  const manifest = readManifest();
  const active = manifest.active_skills || [];
  const disabled = manifest.disabled_skills || [];
  const backupFiles = fs.existsSync(BACKUP_DIR) ? fs.readdirSync(BACKUP_DIR).slice(-10) : [];

  return {
    response:
      `🧩 *Skill Status*\n\n` +
      `Active: ${active.length}\n` +
      `Disabled: ${disabled.length}\n` +
      `Backups: ${backupFiles.length}\n\n` +
      `*Disabled skills:* ${disabled.join(', ') || 'None'}\n\n` +
      `*Recent backups:* ${backupFiles.join(', ') || 'None'}`
  };
}

async function activateSkill(payload, context) {
  const manifest = readManifest();
  const target = String(payload || '').trim();
  if (!target) {
    return { response: '⚠️ Usage: `ACTIVATE SKILL: skill-name`' };
  }

  if (!manifest.disabled_skills?.includes(target)) {
    return { response: `⚠️ ${target} is not currently in disabled_skills.` };
  }

  manifest.disabled_skills = manifest.disabled_skills.filter((name) => name !== target);
  if (!manifest.active_skills.includes(target)) {
    manifest.active_skills.push(target);
  }
  manifest.skill_config = manifest.skill_config || {};
  manifest.skill_config[target] = manifest.skill_config[target] || { reasoning_effort: 'medium' };
  manifest.version = incrementVersion(manifest.version);
  writeManifest(manifest);

  const skill = await context.reloadSkill(target);
  return {
    response:
      `✅ *Skill Activated*\n\n` +
      `Skill: ${skill.name}\n` +
      `Manifest version: ${manifest.version}\n` +
      `Status: live now`
  };
}

async function testSkill(payload, context) {
  const firstSpace = String(payload || '').trim().indexOf(' ');
  const skillName = firstSpace === -1 ? String(payload || '').trim() : payload.slice(0, firstSpace).trim();
  const skillInput = firstSpace === -1 ? '' : payload.slice(firstSpace + 1).trim();
  if (!skillName) {
    return { response: '⚠️ Usage: `TEST SKILL: skill-name input`' };
  }

  const skill = context.skills[skillName] || context.reloadSkill && await context.reloadSkill(skillName);
  if (!skill) {
    return { response: `❌ Could not find skill: ${skillName}` };
  }

  const trigger = skill.triggers?.[0] || null;
  const result = await skill.execute(skillInput, {
    ...buildMockContext(context),
    triggerUsed: trigger
  });

  return {
    response:
      `🧪 *Skill Test Complete*\n\n` +
      `Skill: ${skillName}\n` +
      `Trigger: ${trigger || 'None'}\n` +
      `Result:\n${result?.response || JSON.stringify(result)}`
  };
}

async function rollbackSkill(payload, context) {
  const target = String(payload || '').trim();
  if (!target) {
    return { response: '⚠️ Usage: `ROLLBACK SKILL: skill-name.js` or `ROLLBACK SKILL: skill-name`' };
  }

  if (!fs.existsSync(BACKUP_DIR)) {
    return { response: '⚠️ No backup directory exists yet.' };
  }

  const desiredBase = target.endsWith('.js') ? target : `${target}.js`;
  const candidates = fs.readdirSync(BACKUP_DIR)
    .filter((name) => name.startsWith(desiredBase))
    .sort()
    .reverse();

  if (!candidates.length) {
    return { response: `❌ No backup found for ${desiredBase}` };
  }

  const latestBackup = path.join(BACKUP_DIR, candidates[0]);
  const livePath = path.join(__dirname, desiredBase);
  fs.copyFileSync(latestBackup, livePath);

  try {
    await context.reloadSkill(path.basename(desiredBase, '.js'));
    return {
      response:
        `↩️ *Rollback Complete*\n\n` +
        `Skill file: ${desiredBase}\n` +
        `Backup restored: ${path.basename(latestBackup)}\n` +
        `Status: live now`
    };
  } catch (error) {
    return {
      response:
        `⚠️ Backup restored to disk but hot-reload failed.\n\n` +
        `File: ${desiredBase}\n` +
        `Backup: ${path.basename(latestBackup)}\n` +
        `Error: ${error.message}`
    };
  }
}

async function evolveSkill(payload, context) {
  const state = readState();
  const now = Date.now();
  if (state.lastCreationAt && (now - new Date(state.lastCreationAt).getTime()) < (60 * 60 * 1000)) {
    state.queue.push({
      payload,
      requestedAt: new Date().toISOString(),
      requestedBy: String(context.userId)
    });
    writeState(state);
    const nextTime = new Date(new Date(state.lastCreationAt).getTime() + (60 * 60 * 1000));
    return {
      response:
        `⏳ *Evolution Queued*\n\n` +
        `Only one skill creation is allowed per hour.\n` +
        `Queued for processing after: ${nextTime.toLocaleString('en-ZA')}`
    };
  }

  const manifest = readManifest();
  const fileName = inferSkillFileName(payload, manifest);
  const targetPath = path.join(__dirname, fileName);
  const { code, availablePackages } = await generateSkillCode(payload, context);
  const validation = validateGeneratedCode(code, availablePackages);

  if (!validation.ok) {
    return {
      response:
        `❌ *Generated Skill Rejected*\n\n` +
        validation.violations.map((item) => `• ${item}`).join('\n') +
        `\n\nRetry with a narrower request if you want another pass.`
    };
  }

  const backupPath = backupExistingSkill(targetPath);
  fs.writeFileSync(targetPath, `${code.trim()}\n`);

  const skillName = path.basename(fileName, '.js');
  manifest.active_skills = manifest.active_skills || [];
  if (!manifest.active_skills.includes(skillName)) {
    manifest.active_skills.push(skillName);
  }
  manifest.skill_config = manifest.skill_config || {};
  manifest.skill_config[skillName] = manifest.skill_config[skillName] || { reasoning_effort: 'medium' };
  manifest.version = incrementVersion(manifest.version);
  writeManifest(manifest);

  let skill;
  let liveNow = true;
  let hotReloadError = null;
  try {
    skill = await context.reloadSkill(skillName);
  } catch (error) {
    liveNow = false;
    hotReloadError = error;
  }

  let testSummary = 'Not run';
  let testPassed = false;
  if (skill) {
    try {
      const testResult = await skill.execute('test mode', {
        ...buildMockContext(context),
        triggerUsed: skill.triggers?.[0] || null
      });
      testSummary = testResult?.response || 'Skill executed successfully.';
      testPassed = true;
    } catch (error) {
      testSummary = `Test failed: ${error.message}`;
      liveNow = false;
    }
  }

  state.lastCreationAt = new Date().toISOString();
  writeState(state);

  return {
    skillName,
    skillFile: fileName,
    liveNow,
    manifestVersion: manifest.version,
    testPassed,
    response:
      `🧬 *Evolution Complete*\n\n` +
      `Skill file: ${fileName}\n` +
      `Path: src/skills/${fileName}\n` +
      `Purpose: ${payload}\n` +
      `Packages used: ${findRequiredPackages(code).join(', ') || 'native modules only'}\n` +
      `Manifest version: ${manifest.version}\n` +
      `Backup: ${backupPath ? path.basename(backupPath) : 'not needed'}\n` +
      `Test result: ${testSummary}\n` +
      `Status: ${liveNow ? 'live now' : 'pending restart'}${hotReloadError ? `\nHot-reload error: ${hotReloadError.message}` : ''}\n` +
      `${testPassed ? 'Validation: passed' : 'Validation: requires review'}`
  };
}

module.exports = {
  id: '99-self-evolve',
  name: 'Self-Evolution Engine',
  description: 'Design, validate, register, hot-reload, test, and rollback Serena skills.',
  triggers: ['EVOLVE:', 'GAP ANALYSIS', 'SKILL STATUS', 'ACTIVATE SKILL:', 'TEST SKILL:', 'ROLLBACK SKILL:'],
  TOOL_DEFINITION: {
    type: 'function',
    function: {
      name: 'skill_99_self_evolve',
      description: 'Owner-only Serena self-evolution commands.',
      parameters: {
        type: 'object',
        properties: {
          trigger: {
            type: 'string',
            enum: ['EVOLVE:', 'GAP ANALYSIS', 'SKILL STATUS', 'ACTIVATE SKILL:', 'TEST SKILL:', 'ROLLBACK SKILL:']
          },
          payload: {
            type: 'string'
          }
        },
        required: ['trigger']
      }
    }
  },

  execute: async function (payload, context) {
    try {
      if (!isOwner(context)) {
        return { response: '🔒 This command is restricted to Serena owners.' };
      }

      if (context.triggerUsed === 'GAP ANALYSIS') {
        return await runGapAnalysis(context);
      }
      if (context.triggerUsed === 'SKILL STATUS') {
        return await handleSkillStatus(context);
      }
      if (context.triggerUsed === 'ACTIVATE SKILL:') {
        return await activateSkill(payload, context);
      }
      if (context.triggerUsed === 'TEST SKILL:') {
        return await testSkill(payload, context);
      }
      if (context.triggerUsed === 'ROLLBACK SKILL:') {
        return await rollbackSkill(payload, context);
      }
      if (context.triggerUsed === 'EVOLVE:') {
        return await evolveSkill(payload, context);
      }

      return { response: '⚠️ Unknown self-evolution command.' };
    } catch (error) {
      logger.error('[EVOLVE] Error: ' + error.message);
      return { response: `❌ Self-evolution error: ${error.message}` };
    }
  }
};
