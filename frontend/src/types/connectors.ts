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

export const SOURCE_CATALOG: SourceCard[] = [
  { connector_id: "gmail", display_name: "Gmail", auth_type: "oauth", category: "communication", icon: "Mail", color: "text-red-400", description: "Email messages and threads" },
  { connector_id: "gmail_imap", display_name: "Gmail (IMAP)", auth_type: "oauth", category: "communication", icon: "Mail", color: "text-red-400", description: "Email via app password" },
  { connector_id: "slack", display_name: "Slack", auth_type: "oauth", category: "communication", icon: "Hash", color: "text-purple-400", description: "Channel messages and threads" },
  { connector_id: "imessage", display_name: "iMessage", auth_type: "local", category: "communication", icon: "MessageSquare", color: "text-green-400", description: "macOS Messages history" },
  { connector_id: "gdrive", display_name: "Google Drive", auth_type: "oauth", category: "documents", icon: "FolderOpen", color: "text-blue-400", description: "Docs, Sheets, and files" },
  { connector_id: "notion", display_name: "Notion", auth_type: "oauth", category: "documents", icon: "FileText", color: "text-gray-300", description: "Pages and databases" },
  { connector_id: "obsidian", display_name: "Obsidian", auth_type: "filesystem", category: "documents", icon: "Diamond", color: "text-violet-400", description: "Markdown vault" },
  { connector_id: "granola", display_name: "Granola", auth_type: "oauth", category: "documents", icon: "Mic", color: "text-amber-400", description: "AI meeting notes" },
  { connector_id: "gcalendar", display_name: "Calendar", auth_type: "oauth", category: "pim", icon: "Calendar", color: "text-blue-400", description: "Events and meetings" },
  { connector_id: "gcontacts", display_name: "Contacts", auth_type: "oauth", category: "pim", icon: "Users", color: "text-blue-400", description: "People and contact info" },
];
