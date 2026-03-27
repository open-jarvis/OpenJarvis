export interface SetupStep {
  label: string;
  url?: string;
  urlLabel?: string;
}

export interface ConnectorMeta {
  connector_id: string;
  display_name: string;
  auth_type: 'oauth' | 'local' | 'bridge' | 'filesystem';
  category: 'communication' | 'documents' | 'pim';
  icon: string;
  color: string;
  description: string;
  unitLabel?: string;  // "emails", "messages", "meeting notes", "pages", "notes", etc.
  steps?: SetupStep[];
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

export type WizardStep = "pick" | "connect" | "ingest" | "ready";

// Backward-compatible alias
export type SourceCard = ConnectorMeta;

export const SOURCE_CATALOG: ConnectorMeta[] = [
  {
    connector_id: 'gmail',
    display_name: 'Gmail',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email messages and threads',
    unitLabel: 'emails',
    steps: [
      {
        label: 'Enable 2-Factor Authentication on your Google account',
        url: 'https://myaccount.google.com/signinoptions/two-step-verification',
        urlLabel: 'Open Google Security',
      },
      {
        label: 'Generate an App Password for "Mail"',
        url: 'https://myaccount.google.com/apppasswords',
        urlLabel: 'Open App Passwords',
      },
      { label: 'Paste your credentials below' },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Email address', type: 'text' },
      { name: 'password', placeholder: 'App password (xxxx xxxx xxxx xxxx)', type: 'password' },
    ],
  },
  {
    connector_id: 'slack',
    display_name: 'Slack',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Hash',
    color: 'text-purple-400',
    description: 'Channel messages and threads',
    unitLabel: 'messages',
    steps: [
      {
        label: 'Go to your Slack App settings and copy the Bot User OAuth Token',
        url: 'https://api.slack.com/apps',
        urlLabel: 'Open Slack Apps',
      },
      { label: 'Paste the bot token below (starts with xoxb-)' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'xoxb-...', type: 'password' },
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
        label: 'Create an internal integration and copy the secret',
        url: 'https://www.notion.so/profile/integrations',
        urlLabel: 'Open Notion Integrations',
      },
      { label: 'Paste the integration token below (starts with ntn_)' },
      { label: 'Then share pages with your integration: Page → ... → Connections → Add' },
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
      { label: 'Open the Granola desktop app → Settings → API' },
      { label: 'Copy your API key and paste below' },
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
        label: 'Open System Settings → Privacy & Security → Full Disk Access',
        url: 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
        urlLabel: 'Open System Settings',
      },
      {
        label: 'Enable Full Disk Access for your terminal app (Terminal, iTerm, or Warp)',
      },
      {
        label: 'iMessage history will be detected automatically once access is granted',
      },
    ],
  },
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
        label: 'Find your Obsidian vault folder on your computer. It\'s the folder containing the .obsidian directory.',
      },
      {
        label: 'Paste the full path below (e.g. /Users/you/Documents/MyVault)',
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
        label: 'Go to the Google Cloud Console and create a project (or use an existing one)',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Open Google Cloud Console',
      },
      {
        label: 'Enable the Google Drive API for your project',
        url: 'https://console.cloud.google.com/apis/library/drive.googleapis.com',
        urlLabel: 'Enable Drive API',
      },
      {
        label: 'Go to Credentials → Create OAuth 2.0 Client ID (choose "Desktop app")',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'Copy the Client ID and Client Secret, then paste them below',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Client ID:Client Secret', type: 'password' },
    ],
  },
  {
    connector_id: 'gcalendar',
    display_name: 'Calendar',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Calendar',
    color: 'text-blue-400',
    description: 'Events and meetings',
    unitLabel: 'events',
    steps: [
      {
        label: 'Go to the Google Cloud Console and create a project (or use an existing one)',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Open Google Cloud Console',
      },
      {
        label: 'Enable the Google Calendar API for your project',
        url: 'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com',
        urlLabel: 'Enable Calendar API',
      },
      {
        label: 'Go to Credentials → Create OAuth 2.0 Client ID (choose "Desktop app")',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'Copy the Client ID and Client Secret, then paste them below',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Client ID:Client Secret', type: 'password' },
    ],
  },
  {
    connector_id: 'gcontacts',
    display_name: 'Contacts',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Users',
    color: 'text-blue-400',
    description: 'People and contact info',
    unitLabel: 'contacts',
    steps: [
      {
        label: 'Go to the Google Cloud Console and create a project (or use an existing one)',
        url: 'https://console.cloud.google.com/projectcreate',
        urlLabel: 'Open Google Cloud Console',
      },
      {
        label: 'Enable the People API for your project',
        url: 'https://console.cloud.google.com/apis/library/people.googleapis.com',
        urlLabel: 'Enable People API',
      },
      {
        label: 'Go to Credentials → Create OAuth 2.0 Client ID (choose "Desktop app")',
        url: 'https://console.cloud.google.com/apis/credentials',
        urlLabel: 'Open Credentials',
      },
      {
        label: 'Copy the Client ID and Client Secret, then paste them below',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Client ID:Client Secret', type: 'password' },
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
        label: 'Open System Settings → Privacy & Security → Full Disk Access',
        url: 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
        urlLabel: 'Open System Settings',
      },
      {
        label: 'Enable Full Disk Access for your terminal app (Terminal, iTerm, or Warp)',
      },
      {
        label: 'Apple Notes will be detected automatically once access is granted',
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
        label: 'Go to the Azure Portal and register a new application',
        url: 'https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
        urlLabel: 'Open Azure App Registrations',
      },
      {
        label: 'Under API Permissions, add Microsoft Graph → Mail.Read',
      },
      {
        label: 'Create a client secret and paste the Application (client) ID and secret below',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Client ID:Client Secret', type: 'password' },
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
        label: 'Go to the Dropbox App Console and create a new app',
        url: 'https://www.dropbox.com/developers/apps/create',
        urlLabel: 'Open Dropbox App Console',
      },
      {
        label: 'Choose "Scoped access" → "Full Dropbox" → name your app',
      },
      {
        label: 'Under Permissions, enable "files.metadata.read" and "files.content.read"',
      },
      {
        label: 'Go to Settings → Generate an access token and paste it below',
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
    description: 'WhatsApp messages',
    unitLabel: 'messages',
    steps: [
      {
        label: 'Go to Meta for Developers and create a WhatsApp Business app',
        url: 'https://developers.facebook.com/apps/',
        urlLabel: 'Open Meta Developer Portal',
      },
      {
        label: 'Set up WhatsApp → Get a temporary access token from the API Setup page',
      },
      {
        label: 'Copy your Phone Number ID and Access Token, paste below as "phone_id:token"',
      },
    ],
    inputFields: [
      { name: 'token', placeholder: 'Phone Number ID:Access Token', type: 'password' },
    ],
  },
];
