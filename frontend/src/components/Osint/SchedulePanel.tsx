import { useState, useEffect, useCallback } from 'react';
import {
  Clock,
  Play,
  Pause,
  Trash2,
  Plus,
  Loader2,
  AlertTriangle,
  Target,
  Settings,
  Pencil,
  X,
  Check,
  Zap,
} from 'lucide-react';
import {
  createSchedule,
  fetchSchedules,
  deleteSchedule,
  toggleSchedule,
  updateSchedule,
  runScheduleNow,
  type ScheduleJob,
} from '../Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

const DEFAULT_MODULES = [
  { key: 'dns', label: 'DNS' },
  { key: 'http', label: 'HTTP' },
  { key: 'whois', label: 'WHOIS' },
  { key: 'ip', label: 'IP' },
];

export function SchedulePanel() {
  const [schedules, setSchedules] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [runningNow, setRunningNow] = useState<Set<string>>(new Set());

  // Form state
  const [target, setTarget] = useState('');
  const [selectedModules, setSelectedModules] = useState<string[]>(['dns', 'http', 'whois', 'ip']);
  const [interval, setInterval] = useState(60);
  const [saving, setSaving] = useState(false);

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState('');
  const [editModules, setEditModules] = useState<string[]>([]);
  const [editInterval, setEditInterval] = useState(60);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchSchedules(API_URL);
      setSchedules(data.schedules);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!target.trim()) return;
    setSaving(true);
    try {
      await createSchedule(API_URL, {
        target: target.trim(),
        modules: selectedModules,
        interval_minutes: interval,
      });
      setTarget('');
      setSelectedModules(['dns', 'http', 'whois', 'ip']);
      setInterval(60);
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create schedule');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteSchedule(API_URL, id);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // ignore
    }
  };

  const handleToggle = async (id: string) => {
    try {
      const res = await toggleSchedule(API_URL, id);
      setSchedules((prev) =>
        prev.map((s) => (s.id === id ? { ...s, enabled: res.enabled } : s)),
      );
    } catch {
      // ignore
    }
  };

  const handleRunNow = async (id: string) => {
    setRunningNow((prev) => new Set(prev).add(id));
    try {
      await runScheduleNow(API_URL, id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run schedule');
    } finally {
      setRunningNow((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const toggleModule = (mod: string) => {
    setSelectedModules((prev) =>
      prev.includes(mod) ? prev.filter((m) => m !== mod) : [...prev, mod],
    );
  };

  const handleEditStart = (job: ScheduleJob) => {
    setEditingId(job.id);
    setEditTarget(job.target);
    setEditModules(job.modules);
    setEditInterval(job.interval_minutes);
  };

  const handleEditSave = async (id: string) => {
    setSaving(true);
    try {
      await updateSchedule(API_URL, id, {
        target: editTarget.trim(),
        modules: editModules,
        interval_minutes: editInterval,
      });
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update schedule');
    } finally {
      setSaving(false);
    }
  };

  const handleEditCancel = () => {
    setEditingId(null);
    setEditTarget('');
    setEditModules([]);
    setEditInterval(60);
  };

  const toggleEditModule = (mod: string) => {
    setEditModules((prev) =>
      prev.includes(mod) ? prev.filter((m) => m !== mod) : [...prev, mod],
    );
  };

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock size={16} style={{ color: 'var(--color-accent)' }} />
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            Recurring Scans
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
            }}
          >
            {schedules.length}
          </span>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
          style={{
            background: 'var(--color-accent-subtle)',
            color: 'var(--color-accent)',
            border: '1px solid var(--color-accent-muted)',
          }}
        >
          {showForm ? <Settings size={12} /> : <Plus size={12} />}
          {showForm ? 'Close' : 'New Schedule'}
        </button>
      </div>

      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm flex items-center gap-2"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Create Form */}
      {showForm && (
        <form
          onSubmit={handleCreate}
          className="rounded-lg p-4 flex flex-col gap-3"
          style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
              Target
            </label>
            <input
              type="text"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="example.com"
              className="px-3 py-2 rounded-md text-sm outline-none"
              style={{
                background: 'var(--color-bg-primary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
              Modules
            </label>
            <div className="flex gap-2 flex-wrap">
              {DEFAULT_MODULES.map((m) => {
                const active = selectedModules.includes(m.key);
                return (
                  <button
                    key={m.key}
                    type="button"
                    onClick={() => toggleModule(m.key)}
                    className="px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer"
                    style={{
                      background: active ? 'var(--color-accent-subtle)' : 'var(--color-bg-primary)',
                      color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                      border: `1px solid ${active ? 'var(--color-accent-muted)' : 'var(--color-border)'}`,
                    }}
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
              Interval (minutes)
            </label>
            <input
              type="number"
              min={5}
              max={10080}
              value={interval}
              onChange={(e) => setInterval(Math.max(5, parseInt(e.target.value || '5', 10)))}
              className="px-3 py-2 rounded-md text-sm outline-none w-32"
              style={{
                background: 'var(--color-bg-primary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!target.trim() || saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
              style={{
                background: 'var(--color-accent)',
                color: '#fff',
              }}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
              Create Schedule
            </button>
          </div>
        </form>
      )}

      {/* Schedule List */}
      {loading && (
        <div className="flex items-center gap-2 text-xs py-8 justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
          <Loader2 size={14} className="animate-spin" />
          Loading...
        </div>
      )}

      {!loading && schedules.length === 0 && (
        <div
          className="rounded-lg p-8 text-center text-sm"
          style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
        >
          <Clock size={24} className="mx-auto mb-2 opacity-50" />
          No schedules yet. Create one to automate recurring scans.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {schedules.map((job) => (
          <div
            key={job.id}
            className="rounded-lg p-3 flex flex-col gap-3"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            {editingId === job.id ? (
              <>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
                    Target
                  </label>
                  <input
                    type="text"
                    value={editTarget}
                    onChange={(e) => setEditTarget(e.target.value)}
                    placeholder="example.com"
                    className="px-3 py-2 rounded-md text-sm outline-none"
                    style={{
                      background: 'var(--color-bg-primary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
                    Modules
                  </label>
                  <div className="flex gap-2 flex-wrap">
                    {DEFAULT_MODULES.map((m) => {
                      const active = editModules.includes(m.key);
                      return (
                        <button
                          key={m.key}
                          type="button"
                          onClick={() => toggleEditModule(m.key)}
                          className="px-2.5 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer"
                          style={{
                            background: active ? 'var(--color-accent-subtle)' : 'var(--color-bg-primary)',
                            color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                            border: `1px solid ${active ? 'var(--color-accent-muted)' : 'var(--color-border)'}`,
                          }}
                        >
                          {m.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium uppercase" style={{ color: 'var(--color-text-tertiary)' }}>
                    Interval (minutes)
                  </label>
                  <input
                    type="number"
                    min={5}
                    max={10080}
                    value={editInterval}
                    onChange={(e) => setEditInterval(Math.max(5, parseInt(e.target.value || '5', 10)))}
                    className="px-3 py-2 rounded-md text-sm outline-none w-32"
                    style={{
                      background: 'var(--color-bg-primary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                </div>

                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={handleEditCancel}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                    style={{
                      background: 'var(--color-bg-primary)',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <X size={12} /> Cancel
                  </button>
                  <button
                    type="button"
                    disabled={!editTarget.trim() || saving}
                    onClick={() => handleEditSave(job.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                    style={{
                      background: 'var(--color-accent)',
                      color: '#fff',
                    }}
                  >
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                    Save
                  </button>
                </div>
              </>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div
                    className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
                    style={{
                      background: job.enabled
                        ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
                        : 'color-mix(in srgb, var(--color-text-tertiary) 12%, transparent)',
                    }}
                  >
                    <Target
                      size={16}
                      style={{ color: job.enabled ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
                    />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
                      {job.target}
                    </span>
                    <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                      <span>{job.modules.join(', ')}</span>
                      <span>·</span>
                      <span>every {job.interval_minutes}m</span>
                      {job.last_run && (
                        <>
                          <span>·</span>
                          <span>last: {new Date(job.last_run).toLocaleString()}</span>
                        </>
                      )}
                      {job.next_run && (
                        <>
                          <span>·</span>
                          <span>next: {new Date(job.next_run).toLocaleString()}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full mr-1"
                    style={{
                      background: job.enabled
                        ? 'color-mix(in srgb, var(--color-success) 12%, transparent)'
                        : 'color-mix(in srgb, var(--color-text-tertiary) 12%, transparent)',
                      color: job.enabled ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                    }}
                  >
                    {job.enabled ? 'Active' : 'Paused'}
                  </span>
                  <button
                    onClick={() => handleEditStart(job)}
                    className="p-1.5 rounded-md transition-colors cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)' }}
                    title="Edit"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={() => handleRunNow(job.id)}
                    disabled={runningNow.has(job.id)}
                    className="p-1.5 rounded-md transition-colors cursor-pointer disabled:opacity-50"
                    style={{ color: 'var(--color-accent)' }}
                    title="Run Now"
                  >
                    {runningNow.has(job.id) ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  </button>
                  <button
                    onClick={() => handleToggle(job.id)}
                    className="p-1.5 rounded-md transition-colors cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)' }}
                    title={job.enabled ? 'Pause' : 'Resume'}
                  >
                    {job.enabled ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                  <button
                    onClick={() => handleDelete(job.id)}
                    className="p-1.5 rounded-md transition-colors cursor-pointer"
                    style={{ color: 'var(--color-error)' }}
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
