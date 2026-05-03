// FIX: removed fictional 'medical-research-api' package — replaced with native https module
const https = require('https');

module.exports = {
    name: 'fetch_medical_research',

    description: `Create a module that interfaces with PubMed API and various web sources to retrieve recent clinical trials, systematic reviews related directly within the South African context. The information feeds into 06-notebook for grounded evidence-based medical advice.`,

    triggers: ['research-fetch', 'systematic-review-find'],

    execute(data) {
        // FIX: was bare 'keyword' identifier — now correctly pulled from data object
        const keyword = data.keyword;

        if (!keyword) {
            throw new Error("No keyword provided in data for fetch_medical_research.");
        }

        // FIX: replaced invalid Python-style '#' comment syntax with JS '//' comments
        // FIX: replaced '=' assignment with ':' for valid object literal syntax
        const sources = {
            PubMed: true,
            GoogleScholar: false,
            // Additional databases and publications can be added as needed.
        };

        const preferredSources = ["PUBMED", "SA Epidemiological Databases"];

        const encodedKeyword = encodeURIComponent(keyword);
        const url = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${encodedKeyword}&retmode=json&retmax=10`;

        return new Promise((resolve, reject) => {
            https.get(url, (res) => {
                let rawData = '';
                res.on('data', (chunk) => { rawData += chunk; });
                res.on('end', () => {
                    try {
                        const parsed = JSON.parse(rawData);
                        resolve({
                            keyword,
                            sources,
                            preferredSources,
                            results: parsed
                        });
                    } catch (e) {
                        reject(new Error('Failed to parse PubMed response: ' + e.message));
                    }
                });
            }).on('error', (e) => {
                reject(new Error('PubMed API request failed: ' + e.message));
            });
        });
    }
};
