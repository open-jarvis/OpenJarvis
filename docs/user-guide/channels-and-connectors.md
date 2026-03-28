# Channels & Connectors

OpenJarvis connects to your personal data sources to power Deep Research. This guide walks you through setting up each connector and troubleshooting common issues.

---

## Gmail

**What it indexes:** Email messages and threads from your Gmail inbox.

### Setup (App Password — recommended)

1. **Enable 2-Factor Authentication** on your Google account:
   [Open Google Security Settings →](https://myaccount.google.com/signinoptions/two-step-verification)

2. **Generate an App Password** for "Mail":
   [Open App Passwords →](https://myaccount.google.com/apppasswords)
   - Select "Mail" as the app
   - Copy the 16-character password (e.g. `qpde kebj evhy zljc`)

3. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → your agent → Channels tab → Gmail → Reconnect
   - CLI: `uv run jarvis connect gmail_imap`
   - Enter your email address and the app password

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "App Passwords" page not available | Enable 2-Factor Authentication first |
| Login failed | Make sure you're using the app password, not your regular Google password |
| No emails syncing | Check that IMAP is enabled: [Gmail Settings → Forwarding and POP/IMAP](https://mail.google.com/mail/u/0/#settings/fwdandpop) |
| Only getting recent emails | By default, the last 500 emails are synced. Increase with `max_messages` config |

---

## Google Drive

**What it indexes:** Documents, Sheets, PDFs, and other files from your Drive.

### Setup

1. **Go to Google Cloud Console** and create a project (or use an existing one):
   [Create Project →](https://console.cloud.google.com/projectcreate)

2. **Enable the Google Drive API:**
   [Enable Drive API →](https://console.cloud.google.com/apis/library/drive.googleapis.com)

3. **Create OAuth credentials:**
   [Open Credentials →](https://console.cloud.google.com/apis/credentials)
   - Click "Create Credentials" → "OAuth 2.0 Client ID"
   - Choose "Desktop app" as the application type
   - Copy the **Client ID** and **Client Secret**

4. **Add yourself as a test user** (required while app is unverified):
   [Open OAuth Consent Screen →](https://console.cloud.google.com/apis/credentials/consent)
   - Scroll to "Test users" → click "+ Add Users"
   - Add your Gmail address (e.g. `jonsaadfalcon@gmail.com`)

5. **Add the redirect URI:**
   [Open Credentials →](https://console.cloud.google.com/apis/credentials)
   - Click your OAuth Client → Authorized redirect URIs
   - Add: `http://localhost:8789/callback`

6. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Google Drive → paste Client ID and Client Secret
   - Your browser will open Google's consent page → grant read-only access
   - You'll see "Authorization successful!" → Drive data starts syncing

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Access blocked: app has not completed verification" | Add your email as a test user (step 4 above) |
| "Error 400: redirect_uri_mismatch" | Add `http://localhost:8789/callback` as an authorized redirect URI (step 5) |
| "Error 403: access_denied" | Make sure you selected "Desktop app" when creating the OAuth client |
| Connected but 0 files | Check that you granted Drive read access in the consent screen. Try reconnecting. |
| Token expired | Access tokens expire after 1 hour. Reconnect to get a new one. (Auto-refresh coming soon.) |

---

## Google Calendar

**What it indexes:** Events, meetings, and calendar entries.

### Setup

Same as Google Drive — use the same Google Cloud project and OAuth client.

1. **Enable the Google Calendar API:**
   [Enable Calendar API →](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)

2. Follow steps 3-6 from the Google Drive section above (same Client ID/Secret works)

### Troubleshooting

Same as Google Drive. Additionally:

| Issue | Solution |
|-------|----------|
| Only seeing primary calendar | The connector reads all calendars you have access to |
| Missing shared calendars | Shared calendars from other users may require additional permissions |

---

## Google Contacts

**What it indexes:** People, phone numbers, emails, and contact information.

### Setup

Same as Google Drive — use the same Google Cloud project and OAuth client.

1. **Enable the People API:**
   [Enable People API →](https://console.cloud.google.com/apis/library/people.googleapis.com)

2. Follow steps 3-6 from the Google Drive section above

---

## Slack

**What it indexes:** Channel messages and threads from your Slack workspace.

### Setup

1. **Go to Slack App Settings:**
   [Open Slack Apps →](https://api.slack.com/apps)

2. **Create a new app** (or use existing):
   - Click "Create New App" → "From scratch"
   - Name it (e.g. "OpenJarvis") and select your workspace

3. **Add OAuth scopes:**
   - Go to "OAuth & Permissions"
   - Under "Bot Token Scopes", add: `channels:history`, `channels:read`, `users:read`

4. **Install to workspace:**
   - Click "Install to Workspace" → Authorize
   - Copy the **Bot User OAuth Token** (starts with `xoxb-`)

5. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Slack → paste the bot token
   - CLI: `uv run jarvis connect slack`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "not_allowed_token_type" | Make sure you're using the **Bot** token (`xoxb-...`), not a user token (`xoxp-`) or session token (`xoxe-`) |
| No messages found | The bot can only see channels it's been added to. Invite it: `/invite @OpenJarvis` in the channel |
| Missing private channels | Add `groups:history` and `groups:read` scopes, then reinstall the app |

---

## Notion

**What it indexes:** Pages, databases, and their content.

### Setup

1. **Create an internal integration:**
   [Open Notion Integrations →](https://www.notion.so/profile/integrations)
   - Click "New integration"
   - Name it (e.g. "OpenJarvis")
   - Select your workspace
   - Copy the **Internal Integration Secret** (starts with `ntn_`)

2. **Share pages with your integration:**
   - Open any Notion page you want indexed
   - Click "..." (top right) → "Connections" → find your integration → click it
   - Repeat for each page or database

3. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Notion → paste the token
   - CLI: `uv run jarvis connect notion`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| 0 pages found | You must explicitly share pages with the integration (step 2). The integration can only see pages you've connected. |
| Missing database content | Share the database page itself, not just individual entries |
| Token expired | Notion integration tokens don't expire. If it stops working, regenerate at the integrations page. |

---

## Granola

**What it indexes:** AI meeting notes and transcripts from the Granola app.

### Setup

1. **Open the Granola desktop app** → Settings → API
2. **Copy your API key** (starts with `grn_`)
3. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Granola → paste the key
   - CLI: `uv run jarvis connect granola`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| No API key in settings | Granola API is available on Business and Enterprise plans |
| 0 meeting notes | Check that you have meetings recorded in Granola |

---

## Apple Notes

**What it indexes:** Notes from the macOS Notes app.

### Setup (automatic)

1. **Grant Full Disk Access** to your terminal app:
   - Open System Settings → Privacy & Security → Full Disk Access
   - Enable access for Terminal, iTerm, Warp, or the OpenJarvis desktop app

2. Apple Notes is detected automatically when Full Disk Access is granted

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Not connected" despite Full Disk Access | Restart your terminal app after granting access |
| Notes content is garbled | Some very old notes may have encoding issues. Most notes should be clean. |
| Missing notes | Only notes stored locally or in iCloud are indexed. Notes in third-party accounts (Gmail, Exchange) may not appear. |

---

## iMessage

**What it indexes:** Text messages from the macOS Messages app.

### Setup (automatic)

Same as Apple Notes — requires Full Disk Access.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Not connected" | Grant Full Disk Access (see Apple Notes above) |
| Very slow sync | iMessage databases can be large (50K+ messages). First sync may take 10-30 seconds. |
| Missing recent messages | Messages sync from the local database. If Messages.app hasn't synced from iCloud yet, recent messages may be missing. |

---

## Outlook / Microsoft 365

**What it indexes:** Email messages via IMAP.

### Setup

1. **Enable 2-Factor Authentication** on your Microsoft account:
   [Open Microsoft Security →](https://account.microsoft.com/security)

2. **Generate an App Password:**
   - Go to Security → Advanced security options → App passwords
   - Create a new app password

3. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Outlook → enter email + app password
   - CLI: `uv run jarvis connect outlook`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Login failed | Use the app password, not your regular Microsoft password |
| "Authentication failed" | Some Microsoft 365 organizations disable IMAP. Check with your IT admin. |
| Only getting Inbox | Currently only the Inbox folder is synced |

---

## Obsidian

**What it indexes:** Markdown files from your Obsidian vault.

### Setup

1. Find your Obsidian vault folder (the folder containing the `.obsidian` directory)
2. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Obsidian → paste the vault path
   - CLI: `uv run jarvis connect obsidian --path /path/to/vault`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Not connected" | Double-check the path exists and contains a `.obsidian` folder |
| Missing files | Only `.md`, `.markdown`, and `.txt` files are indexed. Binary files and images are skipped. |
| Slow sync for large vaults | Vaults with 1000+ files may take a minute to sync |

---

## Dropbox

**What it indexes:** Files and documents from your Dropbox.

### Setup

1. **Create a Dropbox app:**
   [Open Dropbox App Console →](https://www.dropbox.com/developers/apps/create)
   - Choose "Scoped access" → "Full Dropbox"

2. **Set permissions:**
   - Under Permissions tab, enable `files.metadata.read` and `files.content.read`

3. **Generate an access token:**
   - Go to Settings tab → "Generated access token" → Generate

4. **Connect in OpenJarvis:**
   - Desktop/Browser: Agents → Channels tab → Dropbox → paste the token
   - CLI: `uv run jarvis connect dropbox`

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid access token" | Dropbox short-lived tokens expire after 4 hours. Generate a new one. |
| Missing files | Check that you enabled the correct permissions (step 2) |

---

## General Troubleshooting

### All connectors

| Issue | Solution |
|-------|----------|
| "Connected — no data synced yet" | The connector authenticated but hasn't synced. Try running `uv run jarvis deep-research-setup --skip-chat` to trigger a sync. |
| Data seems stale | Connectors sync on demand. Run the setup command or click "Reconnect" to re-sync. |
| Want to reset a connector | Click "Reconnect" in the Channels tab, or delete the credential file at `~/.openjarvis/connectors/{connector}.json` |

### Where credentials are stored

All credentials are saved locally at `~/.openjarvis/connectors/` with file permissions `0600` (owner-only read/write). No credentials are sent to any server — everything stays on your device.

```
~/.openjarvis/connectors/
├── gmail_imap.json    # Gmail email + app password
├── gdrive.json        # Google Drive OAuth tokens
├── gcalendar.json     # Google Calendar OAuth tokens
├── gcontacts.json     # Google Contacts OAuth tokens
├── slack.json         # Slack bot token
├── notion.json        # Notion integration token
├── granola.json       # Granola API key
├── outlook.json       # Outlook email + app password
└── dropbox.json       # Dropbox access token
```
