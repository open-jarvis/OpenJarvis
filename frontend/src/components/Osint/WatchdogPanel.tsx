import { useState, useEffect } from 'react';
import { Shield, Globe, Server, MapPin, Calendar, AlertTriangle, CheckCircle, Loader2, Download, FileJson, FileSpreadsheet } from 'lucide-react';
import { runWatchdogScan, exportWatchdogScan } from '../Desktop/lib/api';

interface DnsRecord {
  type: string;
  values: string[];
}

interface DnsData {
  records: DnsRecord[];
  error?: string;
}

interface HttpData {
  status_code: number;
  headers: Record<string, string>;
  body_hash: string | null;
  title: string | null;
  server: string | null;
  error?: string;
}

interface WhoisData {
  registrar: string | null;
  creation_date: string | null;
  expiration_date: string | null;
  privacy_protected: boolean;
  seized: boolean;
  error?: string;
}

interface IpData {
  ip: string;
  reverse_dns: string | null;
  country: string | null;
  region: string | null;
  city: string | null;
  org: string | null;
  asn: string | null;
  error?: string;
}

interface WatchdogResult {
  target: string;
  modules: string[];
  dns?: DnsData;
  http?: HttpData;
  whois?: WhoisData;
  ip?: IpData;
}

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

function parseApiResult(apiResult: Record<string, unknown>): WatchdogResult {
  const result: WatchdogResult = {
    target: (apiResult.target as string) || '',
    modules: (apiResult.modules as string[]) || [],
  };

  const rawResults = (apiResult.results || {}) as Record<string, unknown>;

  if (rawResults.dns) {
    const dnsRaw = rawResults.dns as Record<string, unknown>;
    const records: DnsRecord[] = [];
    const rawRecords = dnsRaw.records as Record<string, string[]> | undefined;
    if (rawRecords) {
      for (const [type, values] of Object.entries(rawRecords)) {
        records.push({ type, values });
      }
    }
    const dnsErrors = (dnsRaw.errors || []) as string[];
    result.dns = {
      records,
      error: dnsErrors.length > 0 ? dnsErrors.join(', ') : undefined,
    };
  }

  if (rawResults.http) {
    const httpRaw = rawResults.http as Record<string, unknown>;
    result.http = {
      status_code: (httpRaw.status_code as number) || 0,
      headers: (httpRaw.headers as Record<string, string>) || {},
      body_hash: (httpRaw.body_hash as string) || null,
      title: (httpRaw.title as string) || null,
      server: (httpRaw.server as string) || null,
      error: (httpRaw.error as string) || undefined,
    };
  }

  if (rawResults.whois) {
    const whoisRaw = rawResults.whois as Record<string, unknown>;
    result.whois = {
      registrar: (whoisRaw.registrar as string) || null,
      creation_date: (whoisRaw.creation_date as string) || null,
      expiration_date: (whoisRaw.expiration_date as string) || null,
      privacy_protected: Boolean(whoisRaw.privacy_protected),
      seized: Boolean(whoisRaw.seized),
      error: (whoisRaw.error as string) || undefined,
    };
  }

  if (rawResults.ip) {
    const ipRaw = rawResults.ip as Record<string, unknown>;
    const geoRaw = (ipRaw.geolocation as Record<string, unknown>) || {};
    let asnValue: string | null = null;
    if (typeof ipRaw.asn === 'string') {
      asnValue = ipRaw.asn;
    } else if (ipRaw.asn && typeof ipRaw.asn === 'object') {
      const asnObj = ipRaw.asn as Record<string, unknown>;
      asnValue = (asnObj.asn as string) || null;
    }
    result.ip = {
      ip: (ipRaw.target as string) || (ipRaw.ip as string) || '',
      reverse_dns: (ipRaw.reverse_dns as string) || null,
      country: (geoRaw.country as string) || (ipRaw.country as string) || null,
      region: (geoRaw.region as string) || (ipRaw.region as string) || null,
      city: (geoRaw.city as string) || (ipRaw.city as string) || null,
      org: (geoRaw.org as string) || (geoRaw.isp as string) || (ipRaw.org as string) || null,
      asn: asnValue,
      error: (ipRaw.error as string) || undefined,
    };
  }

  return result;
}

export function WatchdogPanel() {
  const [target, setTarget] = useState('');
  const [selectedModules, setSelectedModules] = useState<string[]>(['dns', 'http', 'whois']);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WatchdogResult | null>(null);
  const [error, setError] = useState('');
  const [rawApiResult, setRawApiResult] = useState<Record<string, unknown> | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const t = (e as CustomEvent).detail;
      if (typeof t === 'string') setTarget(t);
    };
    window.addEventListener('osint-watchdog-target', handler);
    return () => window.removeEventListener('osint-watchdog-target', handler);
  }, []);

  const modules = [
    { key: 'dns', label: 'DNS', icon: Server },
    { key: 'http', label: 'HTTP', icon: Globe },
    { key: 'whois', label: 'WHOIS', icon: Calendar },
    { key: 'ip', label: 'IP Geo', icon: MapPin },
  ];

  const toggleModule = (key: string) => {
    setSelectedModules((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const handleScan = async () => {
    if (!target.trim() || selectedModules.length === 0) return;
    setLoading(true);
    setError('');
    try {
      const data = await runWatchdogScan(API_URL, target, selectedModules);
      setRawApiResult(data as unknown as Record<string, unknown>);
      setResult(parseApiResult(data as unknown as Record<string, unknown>));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async (format: 'json' | 'csv') => {
    if (!target.trim() || !rawApiResult) return;
    setExporting(true);
    try {
      const res = await exportWatchdogScan(API_URL, target, selectedModules, format);
      const blob = new Blob(
        [typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2)],
        { type: format === 'json' ? 'application/json' : 'text/csv' },
      );
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Globe
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <input
              type="text"
              placeholder="Enter domain or IP..."
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleScan()}
              className="w-full pl-9 pr-4 py-2 rounded-lg text-sm outline-none"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <button
            onClick={handleScan}
            disabled={loading || !target.trim() || selectedModules.length === 0}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-2"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-on-accent)',
            }}
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Scanning...
              </>
            ) : (
              <>
                <Shield size={14} />
                Scan
              </>
            )}
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          {modules.map((mod) => {
            const isSelected = selectedModules.includes(mod.key);
            return (
              <button
                key={mod.key}
                onClick={() => toggleModule(mod.key)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer"
                style={{
                  background: isSelected ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                  color: isSelected ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  border: `1px solid ${isSelected ? 'var(--color-accent-muted)' : 'var(--color-border)'}`,
                }}
              >
                <mod.icon size={12} />
                {mod.label}
              </button>
            );
          })}
        </div>
      </div>

      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          {error}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              <CheckCircle size={14} style={{ color: 'var(--color-success)' }} />
              Scan completed for {result.target}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleExport('json')}
                disabled={exporting}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
                title="Export JSON"
              >
                <FileJson size={12} /> JSON
              </button>
              <button
                onClick={() => handleExport('csv')}
                disabled={exporting}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer disabled:opacity-50"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}
                title="Export CSV"
              >
                <FileSpreadsheet size={12} /> CSV
              </button>
            </div>
          </div>

          {result.dns && !result.dns.error && (
            <ScanCard title="DNS Records" icon={Server}>
              <div className="flex flex-col gap-1.5">
                {result.dns.records.map((rec, idx) => (
                  <div key={idx} className="flex gap-3 text-xs">
                    <span
                      className="shrink-0 font-mono px-1.5 py-0.5 rounded"
                      style={{
                        background: 'var(--color-bg-tertiary)',
                        color: 'var(--color-accent)',
                      }}
                    >
                      {rec.type}
                    </span>
                    <div className="flex flex-col gap-0.5">
                      {rec.values.map((val, vidx) => (
                        <span key={vidx} style={{ color: 'var(--color-text-secondary)' }}>
                          {val}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </ScanCard>
          )}
          {result.dns?.error && <ErrorCard message={result.dns.error} />}

          {result.http && !result.http.error && (
            <ScanCard title="HTTP Analysis" icon={Globe}>
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex gap-2">
                  <span style={{ color: 'var(--color-text-secondary)' }}>Status:</span>
                  <span
                    className="font-mono px-1.5 py-0.5 rounded"
                    style={{
                      background:
                        result.http.status_code < 400
                          ? 'color-mix(in srgb, var(--color-success) 12%, transparent)'
                          : 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                      color:
                        result.http.status_code < 400
                          ? 'var(--color-success)'
                          : 'var(--color-error)',
                    }}
                  >
                    {result.http.status_code}
                  </span>
                </div>
                {result.http.title && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Title:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.http.title}</span>
                  </div>
                )}
                {result.http.server && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Server:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.http.server}</span>
                  </div>
                )}
                <div className="mt-1">
                  <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-text-tertiary)' }}>
                    Headers
                  </span>
                  <div className="flex flex-col gap-0.5 mt-1">
                    {Object.entries(result.http.headers).slice(0, 6).map(([key, val]) => (
                      <div key={key} className="flex gap-2 font-mono">
                        <span style={{ color: 'var(--color-accent)' }}>{key}:</span>
                        <span className="truncate" style={{ color: 'var(--color-text-secondary)' }}>
                          {val}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </ScanCard>
          )}
          {result.http?.error && <ErrorCard message={result.http.error} />}

          {result.whois && !result.whois.error && (
            <ScanCard title="WHOIS" icon={Calendar}>
              <div className="flex flex-col gap-2 text-xs">
                {result.whois.registrar && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Registrar:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.whois.registrar}</span>
                  </div>
                )}
                {result.whois.creation_date && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Created:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.whois.creation_date}</span>
                  </div>
                )}
                {result.whois.expiration_date && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Expires:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.whois.expiration_date}</span>
                  </div>
                )}
                <div className="flex gap-2 mt-1">
                  {result.whois.privacy_protected && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px]"
                      style={{
                        background: 'color-mix(in srgb, var(--color-warning) 12%, transparent)',
                        color: 'var(--color-warning)',
                      }}
                    >
                      Privacy Protected
                    </span>
                  )}
                  {result.whois.seized && (
                    <span
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px]"
                      style={{
                        background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                        color: 'var(--color-error)',
                      }}
                    >
                      <AlertTriangle size={10} />
                      Seized
                    </span>
                  )}
                </div>
              </div>
            </ScanCard>
          )}
          {result.whois?.error && <ErrorCard message={result.whois.error} />}

          {result.ip && !result.ip.error && (
            <ScanCard title="IP Intelligence" icon={MapPin}>
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex gap-2">
                  <span style={{ color: 'var(--color-text-secondary)' }}>IP:</span>
                  <span className="font-mono" style={{ color: 'var(--color-text)' }}>{result.ip.ip}</span>
                </div>
                {result.ip.reverse_dns && (
                  <div className="flex gap-2">
                    <span style={{ color: 'var(--color-text-secondary)' }}>Reverse DNS:</span>
                    <span style={{ color: 'var(--color-text)' }}>{result.ip.reverse_dns}</span>
                  </div>
                )}
                <div className="flex flex-wrap gap-2 mt-1">
                  {result.ip.country && (
                    <Badge>{result.ip.country}</Badge>
                  )}
                  {result.ip.region && (
                    <Badge>{result.ip.region}</Badge>
                  )}
                  {result.ip.city && (
                    <Badge>{result.ip.city}</Badge>
                  )}
                  {result.ip.org && (
                    <Badge>{result.ip.org}</Badge>
                  )}
                  {result.ip.asn && (
                    <Badge>{result.ip.asn}</Badge>
                  )}
                </div>
              </div>
            </ScanCard>
          )}
          {result.ip?.error && <ErrorCard message={result.ip.error} />}
        </div>
      )}
    </div>
  );
}

function ScanCard({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} style={{ color: 'var(--color-accent)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg p-3 flex items-center gap-2 text-xs"
      style={{
        background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
        color: 'var(--color-error)',
      }}
    >
      <AlertTriangle size={14} />
      {message}
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="px-1.5 py-0.5 rounded text-[10px]"
      style={{
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-tertiary)',
      }}
    >
      {children}
    </span>
  );
}
