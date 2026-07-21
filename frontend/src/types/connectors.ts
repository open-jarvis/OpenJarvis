export interface SetupStep {
  label: string;
  url?: string;
  urlLabel?: string;
}

export interface ConnectorMeta {
  connector_id: string;
  display_name: string;
  auth_type: 'oauth' | 'local' | 'bridge' | 'filesystem';
  category: 'communication' | 'documents' | 'pim' | 'other';
  icon: string;
  color: string;
  description: string;
  unitLabel?: string;  // "emails", "messages", "meeting notes", "pages", "notes", etc.
  steps?: SetupStep[];
  troubleshooting?: string[];
  inputFields?: Array<{
    name: string;
    placeholder: string;
    type?: 'text' | 'password';
  }>;
}

export interface ConnectorInfo {
  connector_id: string;
  display_name: string;
  auth_type: "oauth" | "local" | "bridge" | "filesystem";
  connected: boolean;
  auth_url?: string;
  mcp_tools?: string[];
  chunks?: number;
}

export interface SyncStatus {
  state: "idle" | "syncing" | "paused" | "error";
  items_synced: number;
  items_total: number;
  /** Items processed in the current (or most recent) run only. `null`
   *  when no sync has been triggered through this server session yet. */
  new_items_synced?: number | null;
  /** ISO 8601 timestamp of the oldest indexed item, used to label how far
   *  back the corpus reaches ("past 3 months", "past 5 years"). `null`
   *  before anything is indexed. */
  oldest_item_date?: string | null;
  last_sync: string | null;
  error: string | null;
}

export interface ConnectRequest {
  path?: string;
  token?: string;
  code?: string;
  email?: string;
  password?: string;
}

/** Response from POST /v1/connectors/{id}/connect.
 *  For OAuth connectors, pasting a Client ID / Secret pair only registers the
 *  app credentials; the backend returns `status: "oauth_required"` plus an
 *  `oauth_start` path the UI must open to run the browser consent flow that
 *  actually mints an access token (see issue #512). */
export interface ConnectResponse {
  connector_id: string;
  connected: boolean;
  status: "connected" | "pending" | "oauth_required" | "disconnected";
  oauth_start?: string;
  sync_status?: string | null;
}

export type WizardStep = "pick" | "connect" | "ingest" | "ready";

// Backward-compatible alias
export type SourceCard = ConnectorMeta;

export type ConnectorCategory = ConnectorMeta['category'];

export const SOURCE_CATALOG: ConnectorMeta[] = [
  // ── Upload / Paste ─────────────────────────────────────────────────
  {
    connector_id: 'upload',
    display_name: 'Upload / Paste',
    auth_type: 'filesystem',
    category: 'other',
    icon: 'FileUp',
    color: 'text-blue-400',
    description: 'Paste text or upload documents',
    unitLabel: 'documents',
    steps: [
      { label: 'Paste text or upload files (.txt, .md, .pdf, .docx, .csv) to add them to your knowledge base.' },
    ],
    inputFields: [],
  },
  // ── Communication ──────────────────────────────────────────────────
  {
    // Unified Gmail card. Defaults to the IMAP (app-password) flow because
    // it needs no Google Cloud setup; the OAuth path is offered as an
    // "Advanced" disclosure rendered in DataSourcesPage.
    connector_id: 'gmail_imap',
    display_name: 'Gmail',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email messages and threads',
    unitLabel: 'emails',
    steps: [
      {
        label: 'Make sure 2-Step Verification is enabled, then generate a 16-character App Password (Mail / Other / "OpenJarvis"). Paste it below \u2014 spaces are fine, and use the app password, not your regular Gmail password.',
        url: 'https://myaccount.google.com/apppasswords',
        urlLabel: 'How to get an app password \u2192',
      },
    ],
    troubleshooting: [
      "Don't see App Passwords? Make sure 2-Step Verification is enabled first.",
      "Google Workspace user? Your admin may need to enable App Passwords for your organization.",
    ],
    inputFields: [
      { name: 'email', placeholder: 'you@gmail.com', type: 'text' },
      { name: 'password', placeholder: 'App password (xxxx xxxx xxxx xxxx)', type: 'password' },
    ],
  },
  {
    connector_id: 'imap',
    display_name: 'Email (IMAP)',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-amber-400',
    description: 'Any IMAP mailbox',
    unitLabel: 'emails',
    steps: [
      {
        label: 'Generate an app password with your email provider (IMAP must be enabled), then enter your email address and the app password below. The server is detected from your email domain.',
      },
    ],
    troubleshooting: [
      'Most providers require an app password rather than your normal password.',
      'Connects over TLS on port 993; providers that only offer STARTTLS on port 143 are not supported yet.',
    ],
    inputFields: [
      { name: 'email', placeholder: 'you@example.com', type: 'text' },
      { name: 'password', placeholder: 'App password', type: 'password' },
    ],
  },
  {
    connector_id: 'slack',
    display_name: 'Slack',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Hash',
    color: 'text-purple-400',
    description: 'Read messages from every channel, private channel, DM, and group DM you have access to',
    unitLabel: 'messages',
    steps: [
      {
        label: 'Go to api.slack.com/apps and click "Create New App" → choose "From scratch". Name it "OpenJarvis" and pick your workspace',
        url: 'https://api.slack.com/apps',
        urlLabel: 'Open Slack Apps',
      },
      {
        label: 'In the left sidebar, click "OAuth & Permissions". Scroll down to "User Token Scopes" (NOT "Bot Token Scopes"). Click "Add an OAuth Scope" and add EACH of these scopes one by one:',
      },
      {
        label: 'channels:history • channels:read • groups:history • groups:read • im:history • im:read • mpim:history • mpim:read • users:read',
      },
      {
        label: 'In the left sidebar, click "Install App" → click "Install to Workspace" → click "Allow". After installing, copy the "User OAuth Token" that appears (starts with xoxp-, NOT xoxb-)',
      },
      {
        label: 'Paste the user token below. Sync indexes every channel, private channel, DM, and group DM you have access to — no need to invite anything to channels',
      },
      {
        label: '(Optional) Set the app icon: in the left sidebar click "Basic Information" → scroll to "Display Information" → upload the OpenJarvis logo',
        url: 'https://github.com/open-jarvis/OpenJarvis/blob/main/assets/openjarvis-slack-icon.jpg',
        urlLabel: 'Download icon',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'xoxp-...', type: 'password' },
    ],
  },
  {
    connector_id: 'notion',
    display_name: 'Notion',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'FileText',
    color: 'text-gray-300',
    description: 'Pages and databases',
    unitLabel: 'pages',
    steps: [
      {
        label: 'Go to notion.so/profile/integrations → click "+ New integration". Name it "OpenJarvis", select your workspace, and click Submit',
        url: 'https://www.notion.so/profile/integrations',
        urlLabel: 'Open Notion Integrations',
      },
      {
        label: 'Copy the "Internal Integration Secret" (starts with ntn_) and paste it below',
      },
      {
        label: 'To share ALL your pages at once: open any top-level page → click "..." (top right) → "Connections" → "Add connections" → search "OpenJarvis" → click it. This shares the page and all its sub-pages. Repeat for each top-level page, or share your entire workspace by doing this on every root page',
      },
      {
        label: 'Tip: if you have a single top-level page that contains everything, sharing just that one page will share all nested sub-pages automatically',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'ntn_...', type: 'password' },
    ],
  },
  {
    connector_id: 'granola',
    display_name: 'Granola',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'Mic',
    color: 'text-amber-400',
    description: 'AI meeting notes',
    unitLabel: 'meeting notes',
    steps: [
      { label: 'Open the Granola desktop app. Click the gear icon (Settings) in the bottom-left corner, then click "API"' },
      { label: 'Click "Generate API Key" (or copy your existing key). Paste the key below' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'grn_...', type: 'password' },
    ],
  },
  {
    connector_id: 'imessage',
    display_name: 'iMessage',
    auth_type: 'local',
    category: 'communication',
    icon: 'MessageSquare',
    color: 'text-green-400',
    description: 'macOS Messages history',
    unitLabel: 'messages',
    steps: [
      {
        label: 'Open the Apple menu () → System Settings → Privacy & Security (in the left sidebar) → scroll down and click "Full Disk Access"',
      },
      {
        label: 'Click the "+" button at the bottom of the list. Navigate to Applications → Utilities → select "Terminal.app" (or iTerm2/Warp if you use those). If you\'re using the desktop app, also add "OpenJarvis.app" from Applications',
      },
      {
        label: 'Toggle the switch ON next to each app you added. Close and reopen your terminal (or restart OpenJarvis). iMessage data will be detected automatically — no credentials needed',
      },
    ],
  },
  // ── Documents ──────────────────────────────────────────────────────
  {
    connector_id: 'obsidian',
    display_name: 'Obsidian',
    auth_type: 'filesystem',
    category: 'documents',
    icon: 'FolderOpen',
    color: 'text-purple-300',
    description: 'Markdown vault',
    unitLabel: 'notes',
    steps: [
      {
        label: 'Find your vault path: open Obsidian → click the vault name in the bottom-left corner → "Manage Vaults" → look at the path shown under your vault name. On macOS this is usually ~/Documents/MyVault or ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault',
      },
      {
        label: 'Alternatively, open Finder → navigate to your vault folder (it contains a hidden .obsidian directory). Right-click the folder → "Copy as Pathname" to get the full path',
      },
      {
        label: 'Paste the full path below. OpenJarvis will index all .md files in the vault',
      },
    ],
    inputFields: [
      { name: 'path', placeholder: '/Users/you/Documents/MyVault', type: 'text' },
    ],
  },
  {
    connector_id: 'gdrive',
    display_name: 'Google Drive',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'FolderOpen',
    color: 'text-blue-400',
    description: 'Docs, Sheets, and files',
    unitLabel: 'files',
    steps: [
      {
        label: 'Go to Google Cloud Console → create a new project (or select an existing one). Give it any name (e.g. "OpenJarvis")',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Create Project',
      },
      {
        label: 'Enable the Google Drive API: click the link below, make sure your project is selected at the top, then click "Enable"',
        url: 'https://console.cloud.google.com/apis/library/drive.googleapis.com',
        urlLabel: 'Enable Drive API',
      },
      {
        label: 'Create OAuth credentials: go to Credentials (link below) → click "+ Create Credentials" → choose "OAuth client ID" → Application type: "Web application". Under "Authorized redirect URIs" add this server\'s callback (e.g. http://localhost:1313/v1/connectors/gdrive/oauth/callback — match the host/port your OpenJarvis server is bound to) → click "Create".',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'A dialog will show your Client ID and Client Secret. Copy both and paste them below, then click Connect — a Google sign-in window opens to finish authorization. (If you miss the dialog, click the download icon next to your OAuth client to see them again.)',
      },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Client ID (e.g. 123456-abc.apps.googleusercontent.com)', type: 'text' },
      { name: 'password', placeholder: 'Client Secret', type: 'password' },
    ],
  },
  // ── PIM (Calendar, Contacts) ───────────────────────────────────────
  {
    connector_id: 'gcalendar',
    display_name: 'Google Calendar',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Calendar',
    color: 'text-blue-400',
    description: 'Events and meetings',
    unitLabel: 'events',
    steps: [
      {
        label: 'Go to Google Cloud Console → use the same project as Google Drive (or create a new one)',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Open Console',
      },
      {
        label: 'Enable the Google Calendar API: click the link below, select your project, then click "Enable"',
        url: 'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com',
        urlLabel: 'Enable Calendar API',
      },
      {
        label: 'Go to Credentials → "+ Create Credentials" → "OAuth client ID" → Application type: "Desktop app" → "Create". Copy the Client ID and Client Secret',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'Paste the Client ID and Client Secret below (you can reuse the same OAuth client as Google Drive if you enabled both APIs in the same project)',
      },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Client ID', type: 'text' },
      { name: 'password', placeholder: 'Client Secret', type: 'password' },
    ],
  },
  {
    connector_id: 'gcontacts',
    display_name: 'Google Contacts',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Users',
    color: 'text-blue-400',
    description: 'People and contact info',
    unitLabel: 'contacts',
    steps: [
      {
        label: 'Go to Google Cloud Console → use the same project as Google Drive (or create a new one)',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Open Console',
      },
      {
        label: 'Enable the People API: click the link below, select your project, then click "Enable"',
        url: 'https://console.cloud.google.com/apis/library/people.googleapis.com',
        urlLabel: 'Enable People API',
      },
      {
        label: 'Go to Credentials → "+ Create Credentials" → "OAuth client ID" → Application type: "Desktop app" → "Create". Copy the Client ID and Client Secret',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'Paste the Client ID and Client Secret below',
      },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Client ID', type: 'text' },
      { name: 'password', placeholder: 'Client Secret', type: 'password' },
    ],
  },
  {
    connector_id: 'apple_notes',
    display_name: 'Apple Notes',
    auth_type: 'local',
    category: 'documents',
    icon: 'FileText',
    color: 'text-yellow-400',
    description: 'macOS Notes app',
    unitLabel: 'notes',
    steps: [
      {
        label: 'Open the Apple menu () → System Settings → Privacy & Security (in the left sidebar) → scroll down and click "Full Disk Access"',
      },
      {
        label: 'Click the "+" button at the bottom of the list. Navigate to Applications → Utilities → select "Terminal.app" (or iTerm2/Warp if you use those). If you\'re using the desktop app, also add "OpenJarvis.app" from Applications',
      },
      {
        label: 'Toggle the switch ON next to each app you added. Close and reopen your terminal (or restart OpenJarvis). Apple Notes will be detected automatically — no credentials needed',
      },
    ],
  },
  {
    connector_id: 'apple_contacts',
    display_name: 'Apple Contacts',
    auth_type: 'local',
    category: 'pim',
    icon: 'Users',
    color: 'text-orange-400',
    description: 'macOS Contacts app',
    unitLabel: 'contacts',
    steps: [
      {
        label: 'Open the Apple menu () → System Settings → Privacy & Security (in the left sidebar) → scroll down and click "Full Disk Access"',
      },
      {
        label: 'Click the "+" button at the bottom of the list. Navigate to Applications → Utilities → select "Terminal.app" (or iTerm2/Warp if you use those). If you\'re using the desktop app, also add "OpenJarvis.app" from Applications',
      },
      {
        label: 'Toggle the switch ON next to each app you added. Close and reopen your terminal (or restart OpenJarvis). Apple Contacts will be detected automatically — no credentials needed',
      },
    ],
  },
  {
    connector_id: 'outlook',
    display_name: 'Outlook',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-blue-400',
    description: 'Microsoft email and calendar',
    unitLabel: 'emails',
    steps: [
      {
        label: 'Go to the Azure Portal → App Registrations → click "+ New registration". Name it "OpenJarvis", select "Accounts in this organizational directory only", and click Register',
        url: 'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
        urlLabel: 'Open Azure App Registrations',
      },
      {
        label: 'In the left sidebar, click "API Permissions" → "Add a permission" → "Microsoft Graph" → "Delegated permissions" → search and check "Mail.Read" → click "Add permissions"',
      },
      {
        label: 'In the left sidebar, click "Certificates & secrets" → "New client secret" → set a description and expiry → click "Add" → immediately copy the "Value" (you won\'t see it again)',
      },
      {
        label: 'Go to "Overview" in the left sidebar and copy the "Application (client) ID". Paste both the Client ID and the Client Secret below',
      },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Application (client) ID', type: 'text' },
      { name: 'password', placeholder: 'Client Secret Value', type: 'password' },
    ],
  },
  {
    connector_id: 'dropbox',
    display_name: 'Dropbox',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'FolderOpen',
    color: 'text-blue-300',
    description: 'Cloud file storage',
    unitLabel: 'files',
    steps: [
      {
        label: 'Go to the Dropbox App Console and click "Create app". Choose "Scoped access" → "Full Dropbox" → give it a name (e.g. "OpenJarvis") → click "Create app"',
        url: 'https://www.dropbox.com/developers/apps/create',
        urlLabel: 'Open Dropbox App Console',
      },
      {
        label: 'Click the "Permissions" tab at the top. Check "files.metadata.read" and "files.content.read" → click "Submit" at the bottom to save',
      },
      {
        label: 'Go back to the "Settings" tab. Under "OAuth 2", find "Generated access token" and click "Generate". Copy the token and paste it below',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Access token (sl.u...)', type: 'password' },
    ],
  },
  {
    connector_id: 'whatsapp',
    display_name: 'WhatsApp',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'MessageSquare',
    color: 'text-green-400',
    description: 'WhatsApp messages (Meta Cloud API)',
    unitLabel: 'messages',
    steps: [
      {
        label: 'Go to Meta for Developers → click "Create App" → choose "Business" type → fill in your app details and click "Create App"',
        url: 'https://developers.facebook.com/apps/',
        urlLabel: 'Open Meta Developer Portal',
      },
      {
        label: 'On the app dashboard, find "WhatsApp" and click "Set up". Follow the prompts to add a WhatsApp test number. Go to "API Setup" and copy the temporary access token',
      },
      {
        label: 'Copy your "Phone Number ID" (shown on the API Setup page) and the access token. Paste them below separated by a colon — e.g. 123456789:EAABx...',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Phone Number ID:Access Token', type: 'password' },
    ],
  },
];
