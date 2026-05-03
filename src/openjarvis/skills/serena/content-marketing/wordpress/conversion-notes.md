# Conversion Notes

Legacy source:
- `legacy/serena-skills/13-wordpress.js`

Legacy triggers:
- `WP STATUS`
- `WP DRAFT:`
- `WP PUBLISH:`
- `WP PAGE:`
- `WP UPDATE:`
- `WP LIST POSTS`
- `WP LIST PAGES`
- `WP MEDIA:`
- `WP SITE MAP`
- `WP ASK:`
- `WP SEARCH:`

Upgrade decisions:
- Replace trigger parsing with natural-language tool descriptions.
- Replace old JavaScript helper dependency with native Python REST client.
- Use WordPress Application Passwords via environment variables.
- Keep publishing and live updates behind explicit approval.
- Keep GitHub artifact sync as a later enhancement, likely through `serena_github.py`.

Research checked:
- GitHub/PyPI `wp-api-client`
- WordPress REST API Python client documentation
- lighter Python WordPress packages including `wordpress-api-client`, `WordPResT`, and `wpypress`

Native tool file:
- `src/openjarvis/tools/serena_wordpress.py`

Status:
- native tool conversion in progress
