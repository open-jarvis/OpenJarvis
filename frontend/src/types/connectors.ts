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

export interface SourceCard {
  connector_id: string;
  display_name: string;
  auth_type: string;
  category: "communication" | "documents" | "pim";
  icon: string;
  color: string;
  description: string;
}

export const SOURCE_CATALOG: ConnectorMeta[] = [
  {
    connector_id: 'gmail_imap',
    display_name: 'Gmail (IMAP)',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email via app password',
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
    steps: [
      { label: 'Open the Granola desktop app → Settings → API' },
      { label: 'Copy your API key and paste below' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'grn_...', type: 'password' },
    ],
  },
  {
    connector_id: 'gmail',
    display_name: 'Gmail',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email messages and threads (OAuth)',
    steps: [
      { label: 'Click "Authorize" to open Google consent screen' },
      { label: 'Grant read-only access to your Gmail' },
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
    steps: [
      { label: 'Open System Settings → Privacy & Security → Full Disk Access' },
      { label: 'Enable access for your terminal app or OpenJarvis' },
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
    steps: [
      { label: 'Enter the path to your Obsidian vault folder' },
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
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Drive' },
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
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Calendar' },
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
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Contacts' },
    ],
  },
];
