import { describe, expect, it } from 'vitest';
import config, { resolveApiProxyTarget } from '../../vite.config';

describe('Vite API proxy', () => {
  it('forwards Local Voice Stream WebSocket upgrades', () => {
    const server = config.server as {
      proxy: Record<string, { ws?: boolean }>;
    };

    expect(server.proxy['/api'].ws).toBe(true);
  });

  it('uses a server-only override for the Vite proxy target', () => {
    expect(resolveApiProxyTarget('http://127.0.0.1:8001')).toBe('http://127.0.0.1:8001');
  });
});
