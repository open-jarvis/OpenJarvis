const logger = require('../helpers/logger');

function getHubSpotHeaders() {
  if (!process.env.HUBSPOT_API_KEY) {
    throw new Error('HUBSPOT_API_KEY is not configured');
  }

  return {
    Authorization: `Bearer ${process.env.HUBSPOT_API_KEY}`,
    'Content-Type': 'application/json'
  };
}

async function hubspotRequest(endpoint, options = {}) {
  const response = await fetch(`https://api.hubapi.com${endpoint}`, {
    method: options.method || 'GET',
    headers: getHubSpotHeaders(),
    body: options.body ? JSON.stringify(options.body) : undefined
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HubSpot API ${response.status}: ${text || response.statusText}`);
  }

  return response.json();
}

module.exports = {
  id: '44-hubspot',
  name: 'HubSpot CRM',
  description: 'Create HubSpot contacts and deals through the HubSpot CRM API.',
  triggers: ['HUBSPOT CONTACT:', 'HUBSPOT DEAL:'],

  execute: async function (payload, context) {
    try {
      if (!process.env.HUBSPOT_API_KEY) {
        return { response: '⚠️ HubSpot requires `HUBSPOT_API_KEY` in `.env`.' };
      }

      const parts = String(payload || '').split('|').map((part) => part.trim()).filter(Boolean);
      if (context.triggerUsed === 'HUBSPOT CONTACT:') {
        if (parts.length < 2) {
          return { response: '⚠️ Usage: `HUBSPOT CONTACT: Name | email | phone | notes`' };
        }

        const [name, email, phone = '', notes = ''] = parts;
        const created = await hubspotRequest('/crm/v3/objects/contacts', {
          method: 'POST',
          body: {
            properties: {
              firstname: name.split(' ')[0] || name,
              lastname: name.split(' ').slice(1).join(' ') || '',
              email,
              phone
            }
          }
        });

        return {
          response:
            `✅ *HubSpot contact created*\n\n` +
            `👤 *Name:* ${name}\n` +
            `📧 *Email:* ${email}\n` +
            `🆔 *ID:* ${created.id}`
        };
      }

      if (parts.length < 2) {
        return { response: '⚠️ Usage: `HUBSPOT DEAL: Deal name | amount | stage | notes`' };
      }

      const [dealName, amount, stage = process.env.HUBSPOT_DEFAULT_DEAL_STAGE || '', notes = ''] = parts;
      const created = await hubspotRequest('/crm/v3/objects/deals', {
        method: 'POST',
        body: {
          properties: {
            dealname: dealName,
            amount,
            dealstage: stage,
            description: notes
          }
        }
      });

      return {
        response:
          `✅ *HubSpot deal created*\n\n` +
          `💼 *Deal:* ${dealName}\n` +
          `💰 *Amount:* ${amount}\n` +
          `🆔 *ID:* ${created.id}`
      };
    } catch (error) {
      logger.error('[HUBSPOT] Error: ' + error.message);
      return { response: `❌ HubSpot error: ${error.message}` };
    }
  }
};
