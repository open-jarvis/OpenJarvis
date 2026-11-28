import { isTauri } from './api';

export interface LocalAccessSettings {
  enabled: boolean;
  allowedDirs: string[];
  allowedApps: string[];
  allowedCommands: string[];
}

export interface LocalFileEntry {
  name: string;
  path: string;
  isDir: boolean;
  sizeBytes: number;
}

export interface LocalCommandResult {
  stdout: string;
  stderr: string;
  success: boolean;
  returnCode: number | null;
}

async function invoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  if (!isTauri()) {
    throw new Error('Local computer access is available in the OpenJarvis desktop app only.');
  }
  const { invoke: tauriInvoke } = await import('@tauri-apps/api/core');
  return tauriInvoke<T>(command, args);
}

export const getLocalAccessSettings = () =>
  invoke<LocalAccessSettings>('get_local_access_settings');

export const setLocalAccessSettings = (settings: LocalAccessSettings) =>
  invoke<LocalAccessSettings>('set_local_access_settings', { settings });

export const listLocalFiles = (path: string) =>
  invoke<LocalFileEntry[]>('list_local_files', { path });

export const readLocalFile = (path: string) =>
  invoke<string>('read_local_file', { path });

export const writeLocalFile = (path: string, content: string, confirmOverwrite = false) =>
  invoke<void>('write_local_file', { path, content, confirmOverwrite });

export const launchAllowedApp = (appName: string, confirmed: boolean) =>
  invoke<void>('launch_allowed_app', { appName, confirmed });

export const runAllowedCommand = (command: string, confirmed: boolean) =>
  invoke<LocalCommandResult>('run_allowed_command', { command, confirmed });
