const logger = require('../helpers/logger');

let researchSkill = null;
function getResearchSkill() {
  if (researchSkill) return researchSkill;
  try {
    researchSkill = require('./75-research-operator');
    if (researchSkill && typeof researchSkill.execute === 'function') {
      return researchSkill;
    }
  } catch (error) {
    logger.error('[WEB-SEARCH] Could not load 75-research-operator: ' + error.message);
  }
  return null;
}

let researchApi = null;
function getResearchApi() {
  if (researchApi) return researchApi;
  try {
    researchApi = require('../helpers/research-orchestrator');
    if (researchApi && typeof researchApi.extractPage === 'function' && typeof researchApi.researchQuestion === 'function') {
      return researchApi;
    }
  } catch (error) {
    logger.error('[WEB-SEARCH] Could not load helper research-orchestrator fallback: ' + error.message);
  }
  return null;
}

function cleanText(value) {
  return String(value || '').replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim();
}

function formatResearchErrorResponse(error, api) {
  if (api && typeof api.formatOperatorFacingError === 'function') {
    return `Web research error: ${api.formatOperatorFacingError(error)}`;
  }
  return `Web research error: ${String(error?.message || error || 'Unknown research error')}`;
}

module.exports = {
  id: '61-web-search',
  name: 'Web Search',
  description: 'Delegates live research and page extraction requests to the unified research operator.',
  triggers: [
    'WEB SEARCH:',
    'SEARCH:',
    'FIND NEWS:',
    'RESEARCH:',
    'RESEARCH PAGE:',
    'RESEARCH COMPARE:',
    'COMPETITOR:',
    'RESEARCH STATUS',
    'SEARCH STATUS',
    'SEARXNG STATUS'
  ],

  async execute(payload, context) {
    const skill = getResearchSkill();
    let trigger = String(context?.triggerUsed || '').trim().toUpperCase();
    if (trigger === 'WEB SEARCH:' || trigger === 'SEARCH:' || trigger === 'FIND NEWS:' || trigger === 'COMPETITOR:' || trigger === 'RESEARCH COMPARE:') {
      trigger = 'RESEARCH:';
    }

    if (skill && typeof skill.execute === 'function') {
      return skill.execute(payload, { ...context, triggerUsed: trigger });
    }

    const api = getResearchApi();
    if (!api) {
      return { response: 'Web research error: unified research operator is not available.' };
    }

    try {
      if (trigger === 'RESEARCH STATUS' || trigger === 'SEARCH STATUS' || trigger === 'SEARXNG STATUS') {
        const status = await api.getResearchStatus({ ...context, triggerUsed: trigger });
        return { response: api.formatResearchStatus(status) };
      }

      if (trigger === 'RESEARCH PAGE:') {
        const page = await api.extractPage(payload, { ...context, triggerUsed: trigger });
        return {
          response: [
            'Research page extraction',
            '',
            `URL: ${cleanText(page.url)}`,
            `Title: ${cleanText(page.title || 'unknown')}`,
            '',
            (page.text || '').slice(0, 3200) || 'No readable text extracted.'
          ].join('\n')
        };
      }

      const result = await api.researchQuestion(payload, { ...context, triggerUsed: trigger });
      return { response: api.formatResearchResult(result) };
    } catch (error) {
      logger.error('[WEB-SEARCH] Fallback operator error: ' + error.message);
      return { response: formatResearchErrorResponse(error, api) };
    }
  }
};
