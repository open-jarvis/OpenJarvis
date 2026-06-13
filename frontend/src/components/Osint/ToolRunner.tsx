import { useState } from 'react';
import { Play, Loader2, Terminal, AlertTriangle, CheckCircle } from 'lucide-react';
import { execOsintTool, type OsintExecResponse } from '../Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

interface ToolRunnerProps {
  toolName: string;
  target: string;
}

export function ToolRunner({ toolName, target }: ToolRunnerProps) {
  const [output, setOutput] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState<boolean | null>(null);

  const handleRun = async () => {
    setLoading(true);
    setOutput('');
    setSuccess(null);
    try {
      const res = await execOsintTool(API_URL, toolName, target, 60);
      setOutput(res.output);
      setSuccess(res.success);
    } catch (err) {
      setOutput(err instanceof Error ? err.message : 'Execution failed');
      setSuccess(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg p-3" style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={handleRun}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
          style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          {loading ? 'Running…' : 'Run Tool'}
        </button>
        <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Target: {target}
        </span>
        {success === true && <CheckCircle size={12} style={{ color: 'var(--color-success)' }} />}
        {success === false && <AlertTriangle size={12} style={{ color: 'var(--color-error)' }} />}
      </div>

      {output && (
        <div className="rounded-md p-2 overflow-auto max-h-64">
          <div className="flex items-center gap-1 mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
            <Terminal size={10} />
            <span className="text-[10px] font-medium uppercase tracking-wider">Output</span>
          </div>
          <pre
            className="text-[11px] font-mono whitespace-pre-wrap leading-relaxed"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {output}
          </pre>
        </div>
      )}
    </div>
  );
}
