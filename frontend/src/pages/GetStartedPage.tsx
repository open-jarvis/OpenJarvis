import { useState, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router';
import {
  Sparkles,
  Download,
  Terminal,
  Globe,
  Monitor,
  Apple,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Cpu,
  CheckCircle2,
  MessageSquare,
  ArrowRight,
} from 'lucide-react';
import { isTauri, checkHealth } from '../lib/api';

const GITHUB_BASE =
  'https://github.com/open-jarvis/OpenJarvis/releases/latest/download';

interface Platform {
  id: string;
  label: string;
  shortLabel: string;
  file: string;
  icon: typeof Apple;
}

const PLATFORMS: Platform[] = [
  {
    id: 'mac-arm',
    label: 'macOS (Apple Silicon)',
    shortLabel: 'macOS (Apple Silicon)',
    file: 'OpenJarvis_aarch64.dmg',
    icon: Apple,
  },
  {
    id: 'mac-intel',
    label: 'macOS (Intel)',
    shortLabel: 'macOS (Intel)',
    file: 'OpenJarvis_x64.dmg',
    icon: Apple,
  },
  {
    id: 'windows',
    label: 'Windows (64-bit)',
    shortLabel: 'Windows (64-bit)',
    file: 'OpenJarvis_x64-setup.msi',
    icon: Monitor,
  },
  {
    id: 'linux-deb',
    label: 'Linux (DEB)',
    shortLabel: 'Linux (DEB)',
    file: 'OpenJarvis_amd64.deb',
    icon: Terminal,
  },
  {
    id: 'linux-rpm',
    label: 'Linux (RPM)',
    shortLabel: 'Linux (RPM)',
    file: 'OpenJarvis_x86_64.rpm',
    icon: Terminal,
  },
];

type DeployContext = 'hosted' | 'desktop' | 'selfhosted';

function detectContext(): DeployContext {
  if (isTauri()) return 'desktop';
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0') {
    return 'selfhosted';
  }
  return 'hosted';
}

function detectPlatform(): string {
  const ua = navigator.userAgent.toLowerCase();
  const platform = navigator.platform?.toLowerCase() || '';

  if (platform.includes('mac') || ua.includes('macintosh')) {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl');
      if (gl) {
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        if (ext) {
          const renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
          if (renderer && /apple m/i.test(renderer)) return 'mac-arm';
        }
      }
    } catch {}
    return 'mac-arm';
  }
  if (platform.includes('win') || ua.includes('windows')) return 'windows';
  if (ua.includes('ubuntu') || ua.includes('debian')) return 'linux-deb';
  if (ua.includes('linux')) return 'linux-deb';
  return 'mac-arm';
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className="relative group rounded-lg px-4 py-3 text-sm font-mono overflow-x-auto"
      style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}
    >
      <pre className="whitespace-pre-wrap break-all">{code}</pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-tertiary)' }}
        title="Copy"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
  defaultOpen = false,
}: {
  icon: typeof Terminal;
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: '1px solid var(--color-border)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-3 w-full px-5 py-4 text-left cursor-pointer transition-colors"
        style={{ background: open ? 'var(--color-bg-secondary)' : 'var(--color-surface)' }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.background = 'var(--color-bg-secondary)';
        }}
        onMouseLeave={(e) => {
          if (!open) e.currentTarget.style.background = 'var(--color-surface)';
        }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Icon size={16} />
        </div>
        <span className="text-sm font-medium flex-1" style={{ color: 'var(--color-text)' }}>
          {title}
        </span>
        <Chevron size={16} style={{ color: 'var(--color-text-tertiary)' }} />
      </button>
      {open && (
        <div className="px-5 pb-5 pt-3 flex flex-col gap-3" style={{ background: 'var(--color-surface)' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hosted view: visitor on a deployed website
// ---------------------------------------------------------------------------
function HostedView() {
  const navigate = useNavigate();
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setHealthy);
  }, []);

  return (
    <div className="text-center mb-14">
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <Sparkles size={32} />
      </div>
      <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
        OpenJarvis
      </h1>
      <p
        className="text-sm mb-6 leading-relaxed max-w-md mx-auto"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        Private AI that runs on your hardware. Chat, tools, agents, and
        energy profiling &mdash; no cloud required.
      </p>

      {healthy === true && (
        <div className="flex flex-col items-center gap-4">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent)' }}>
            <CheckCircle2 size={16} />
            <span>Server is running</span>
          </div>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'white' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            <MessageSquare size={18} />
            Start Chatting
            <ArrowRight size={16} />
          </button>
        </div>
      )}

      {healthy === false && (
        <div
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm"
          style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' }}
        >
          Server is not responding. The backend may be starting up.
        </div>
      )}

      {healthy === null && (
        <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          Checking server...
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desktop view: running in the Tauri app
// ---------------------------------------------------------------------------
function DesktopView() {
  const navigate = useNavigate();

  return (
    <>
      <div className="text-center mb-14">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Sparkles size={32} />
        </div>
        <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          OpenJarvis Desktop
        </h1>
        <p
          className="text-sm mb-4 leading-relaxed max-w-md mx-auto"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Your local AI is ready. Everything runs on your device &mdash; no
          data leaves your machine.
        </p>
        <span
          className="inline-block text-[11px] font-mono px-2.5 py-1 rounded-full"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
        >
          v2.8
        </span>
      </div>

      <div
        className="rounded-xl p-6 mb-8 text-center"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center justify-center gap-2 mb-2" style={{ color: 'var(--color-accent)' }}>
          <CheckCircle2 size={18} />
          <span className="text-sm font-medium">All systems running</span>
        </div>
        <p className="text-xs mb-5" style={{ color: 'var(--color-text-tertiary)' }}>
          Ollama inference engine, API server, and AI model are active.
        </p>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
          style={{ background: 'var(--color-accent)', color: 'white' }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
        >
          <MessageSquare size={18} />
          Start Chatting
          <ArrowRight size={16} />
        </button>
      </div>

      <div className="flex flex-col gap-3 mb-8">
        <Section icon={Cpu} title="Keyboard Shortcuts" defaultOpen>
          <div className="grid grid-cols-2 gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+K</kbd> Model picker</div>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+I</kbd> System panel</div>
            <div><kbd className="font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--color-bg-tertiary)' }}>Cmd+N</kbd> New chat</div>
          </div>
        </Section>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Self-hosted view: running on localhost (manual setup)
// ---------------------------------------------------------------------------
function SelfHostedView() {
  const detectedId = useMemo(() => detectPlatform(), []);
  const primary = PLATFORMS.find((p) => p.id === detectedId) || PLATFORMS[0];
  const others = PLATFORMS.filter((p) => p.id !== primary.id);

  return (
    <>
      {/* Hero */}
      <div className="text-center mb-14">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <Sparkles size={32} />
        </div>
        <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          OpenJarvis
        </h1>
        <p
          className="text-sm mb-4 leading-relaxed max-w-md mx-auto"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Private AI that runs on your hardware. Chat, tools, agents, and
          energy profiling &mdash; no cloud required.
        </p>
        <span
          className="inline-block text-[11px] font-mono px-2.5 py-1 rounded-full"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
        >
          v2.8
        </span>
      </div>

      {/* Desktop Download */}
      <div className="mb-10">
        <div
          className="rounded-xl p-8 text-center"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center justify-center gap-2 mb-1">
            <Monitor size={18} style={{ color: 'var(--color-text-secondary)' }} />
            <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
              Desktop App
            </h2>
          </div>
          <p className="text-xs mb-6" style={{ color: 'var(--color-text-tertiary)' }}>
            One-click install. Bundles Ollama and the server &mdash; no setup required.
          </p>

          <a
            href={`${GITHUB_BASE}/${primary.file}`}
            className="inline-flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-medium transition-opacity cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'white' }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            <Download size={18} />
            Download for {primary.label}
          </a>

          <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
              Or
            </span>
            {others.map((p) => (
              <a
                key={p.id}
                href={`${GITHUB_BASE}/${p.file}`}
                className="text-[11px] underline underline-offset-2 transition-colors"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-secondary)')}
              >
                {p.shortLabel}
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* CLI + Browser sections */}
      <div className="flex flex-col gap-3 mb-10">
        <Section icon={Terminal} title="Command Line (macOS / Linux)" defaultOpen>
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Install with pip (Python 3.10+ required):
          </p>
          <CodeBlock code="pip install openjarvis" />
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Or with uv for faster installs:
          </p>
          <CodeBlock code="uv pip install openjarvis" />
          <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
            Then get started:
          </p>
          <CodeBlock code="jarvis init\njarvis doctor\njarvis chat" />
        </Section>

        <Section icon={Globe} title="Browser App (Self-Hosted)">
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Launch the API server to get the full UI in your browser:
          </p>
          <CodeBlock code="pip install 'openjarvis[server]'\njarvis serve --port 8000" />
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            The chat, dashboard, energy profiling, and cost comparison all run
            locally on your machine.
          </p>
        </Section>

        <Section icon={Globe} title="Docker (Cloud / VPS Deploy)">
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Deploy with Docker Compose for a zero-setup hosted instance:
          </p>
          <CodeBlock code="git clone https://github.com/open-jarvis/OpenJarvis.git\ncd OpenJarvis\ndocker compose -f deploy/docker/docker-compose.yml up -d" />
          <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            This starts both the API server and Ollama. The web UI is bundled and
            served automatically at port 8000.
          </p>
        </Section>
      </div>

      {/* System Requirements */}
      <div
        className="rounded-xl px-6 py-5"
        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Cpu size={14} style={{ color: 'var(--color-text-tertiary)' }} />
          <h3 className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
            System Requirements
          </h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>Desktop App</div>
            No prerequisites &mdash; everything is bundled
          </div>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>CLI / Self-Hosted</div>
            Python 3.10+ and an inference engine (Ollama recommended)
          </div>
          <div>
            <div className="font-medium mb-0.5" style={{ color: 'var(--color-text)' }}>Memory</div>
            8 GB+ RAM recommended
          </div>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page — delegates to the context-appropriate view
// ---------------------------------------------------------------------------

export function GetStartedPage() {
  const context = useMemo(detectContext, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-16">
        {context === 'hosted' && <HostedView />}
        {context === 'desktop' && <DesktopView />}
        {context === 'selfhosted' && <SelfHostedView />}
      </div>
    </div>
  );
}
