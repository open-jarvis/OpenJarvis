import { useMemo } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  Bot,
  Braces,
  Check,
  CircleDot,
  Cpu,
  Database,
  FileText,
  LockKeyhole,
  MessageSquare,
  Network,
  Radio,
  Search,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react';
import type { LogEntry, ToolCallInfo } from '../types';
import { useAppStore } from '../lib/store';
import './orchestrator.css';

type NodeKind = 'conversation' | 'model' | 'tool' | 'research' | 'data' | 'agents' | 'logs';

interface NodeState {
  id: NodeKind;
  label: string;
  detail: string;
  x: number;
  y: number;
  active: boolean;
  current?: boolean;
  count?: number;
}

const nodeIcons = {
  conversation: MessageSquare,
  model: Cpu,
  tool: Braces,
  research: Search,
  data: Database,
  agents: Bot,
  logs: FileText,
} as const;

const number = new Intl.NumberFormat('pt-BR');

function clock(timestamp: number) {
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(timestamp);
}

function lastToolCalls(messages: { toolCalls?: ToolCallInfo[] }[]) {
  return messages.flatMap((message) => message.toolCalls ?? []);
}

function statusFor(node: NodeKind, logs: LogEntry[], calls: ToolCallInfo[], messages: number, isStreaming: boolean) {
  if (node === 'conversation') return messages > 0;
  if (node === 'model') return isStreaming || logs.some((entry) => entry.category === 'model' || entry.category === 'chat');
  if (node === 'tool') return calls.length > 0;
  if (node === 'research') return logs.some((entry) => entry.message.toLowerCase().includes('research') || entry.message.toLowerCase().includes('search'));
  if (node === 'data') return false;
  if (node === 'agents') return isStreaming;
  return logs.length > 0;
}

export function OrchestratorPage() {
  const messages = useAppStore((state) => state.messages);
  const logs = useAppStore((state) => state.logEntries);
  const stream = useAppStore((state) => state.streamState);
  const selectedModel = useAppStore((state) => state.selectedModel);
  const serverInfo = useAppStore((state) => state.serverInfo);
  const savings = useAppStore((state) => state.savings);
  const liveEnergy = useAppStore((state) => state.liveEnergy);

  const view = useMemo(() => {
    const calls = lastToolCalls(messages);
    const running = stream.activeToolCalls.find((call) => call.status === 'running');
    const recentLogs = logs.slice(-6).reverse();
    const activeDestination: NodeKind | undefined = running ? 'tool'
      : stream.isStreaming && logs.some((entry) => entry.message.toLowerCase().includes('research') || entry.message.toLowerCase().includes('search')) ? 'research'
      : undefined;
    const localModel = selectedModel || serverInfo?.model || 'Aguardando seleção';
    const nodes: NodeState[] = [
      { id: 'conversation', label: 'CONVERSA', detail: messages.length ? `${messages.length} mensagens na sessão` : 'Sem mensagens nesta sessão', x: 17, y: 49, active: statusFor('conversation', logs, calls, messages.length, stream.isStreaming), current: stream.isStreaming && !activeDestination },
      { id: 'model', label: 'MODELO LOCAL', detail: localModel, x: 48, y: 82, active: statusFor('model', logs, calls, messages.length, stream.isStreaming), current: stream.isStreaming },
      { id: 'tool', label: 'FERRAMENTAS', detail: running ? `${running.tool} em execução` : calls.length ? `${calls.length} acionamento${calls.length === 1 ? '' : 's'}` : 'Nenhuma ferramenta acionada', x: 77, y: 29, active: statusFor('tool', logs, calls, messages.length, stream.isStreaming), current: activeDestination === 'tool', count: calls.length || undefined },
      { id: 'research', label: 'PESQUISA', detail: statusFor('research', logs, calls, messages.length, stream.isStreaming) ? 'Atividade registrada' : 'Não acionada nesta sessão', x: 82, y: 49, active: statusFor('research', logs, calls, messages.length, stream.isStreaming), current: activeDestination === 'research' },
      { id: 'data', label: 'FONTES DE DADOS', detail: 'Nenhuma fonte acessada nesta sessão', x: 72, y: 73, active: false },
      { id: 'agents', label: 'AGENTES', detail: stream.isStreaming ? 'Orquestração em curso' : 'Sem execução em curso', x: 48, y: 16, active: statusFor('agents', logs, calls, messages.length, stream.isStreaming), current: stream.isStreaming },
      { id: 'logs', label: 'LOGS', detail: logs.length ? `${logs.length} eventos locais` : 'Sem eventos registrados', x: 24, y: 23, active: statusFor('logs', logs, calls, messages.length, stream.isStreaming) },
    ];
    const route = activeDestination === 'tool'
      ? `conversa → modelo local → ${running?.tool ?? 'ferramenta'}`
      : activeDestination === 'research'
        ? 'conversa → modelo local → pesquisa'
        : stream.isStreaming ? 'conversa → modelo local → resposta'
          : 'Aguardando uma solicitação local';
    const detail = stream.isStreaming
      ? stream.phase || 'O modelo local está preparando uma resposta.'
      : calls.length
        ? `Última ferramenta observada: ${calls[calls.length - 1].tool}.`
        : 'A rota será exibida quando você iniciar uma conversa ou uma ferramenta for acionada.';
    return { calls, recentLogs, nodes, route, detail, localModel, activeDestination };
  }, [logs, messages, selectedModel, serverInfo, stream]);

  const activeNodeIds = new Set(view.nodes.filter((node) => node.active).map((node) => node.id));
  const energyValue = liveEnergy ? `${liveEnergy.power_w.toFixed(1)} W` : 'em espera';

  return (
    <div className="orchestrator-page">
      <header className="orchestrator-topbar">
        <div className="orchestrator-title"><span className="brand-orbit" /><span>OPEN<span>JARVIS</span></span><i /><strong>ORQUESTRADOR</strong></div>
        <div className="privacy-mark"><LockKeyhole size={13} /> LOCAL E PRIVADO</div>
      </header>

      <div className="orchestrator-layout">
        <aside className="orchestrator-rail system-rail">
          <RailHeading icon={<Activity size={17} />} title="ATIVIDADE LOCAL" status={stream.isStreaming ? 'em execução' : 'em espera'} live={stream.isStreaming} />
          <div className="model-select"><Cpu size={20} /><div><span>MODELO LOCAL</span><strong>{view.localModel}</strong></div><CircleDot size={15} /></div>
          <div className="rail-chart"><div className="rail-chart-header"><span>Atividade</span><strong>{logs.length ? 'registrada' : 'sem eventos'}</strong></div><ActivityBars count={Math.max(logs.length, messages.length)} /></div>
          <div className="rail-meter"><div><Zap size={17} /><span>Energia atual</span><strong>{energyValue}</strong></div><span className="meter-track"><i style={{ width: liveEnergy ? `${Math.min(100, liveEnergy.power_w)}%` : '0%' }} /></span></div>
          <div className="health-list"><Health label="Requisições locais" value={number.format(savings?.total_calls ?? 0)} /><Health label="Tokens" value={number.format(savings?.total_tokens ?? 0)} /><Health label="Eventos de sessão" value={number.format(logs.length)} /></div>
        </aside>

        <main className="orbital-stage">
          <div className="stage-heading"><span>MAPA DE DECISÃO</span><div className={`live-chip ${stream.isStreaming ? 'active' : ''}`}><i />{stream.isStreaming ? 'ATIVO AGORA' : 'SEM ROTA ATIVA'}</div></div>
          <div className="orbit-field">
            <div className="nebula nebula-one" /><div className="nebula nebula-two" />
            <div className="orbit orbit-a" /><div className="orbit orbit-b" /><div className="orbit orbit-c" />
            <svg className="routing-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              {view.nodes.map((node) => node.id !== 'model' && <line key={node.id} className={activeNodeIds.has(node.id) ? 'observed' : ''} x1="50" y1="50" x2={node.x} y2={node.y} />)}
              {stream.isStreaming && <polyline className="route-active" points={view.activeDestination === 'tool' ? '17,49 48,82 77,29' : view.activeDestination === 'research' ? '17,49 48,82 82,49' : '17,49 48,82 50,50'} />}
            </svg>
            <div className={`orchestrator-core ${stream.isStreaming ? 'thinking' : ''}`}><div className="core-void" /><div className="core-wave" /><strong>ORQUESTRADOR</strong><span>{stream.isStreaming ? 'processando rota' : 'pronto'}</span></div>
            {view.nodes.map((node) => <OrbitNode key={node.id} node={node} />)}
          </div>
          <div className="stage-footer"><span><i className="legend active" /> sinal observado</span><span><i className="legend current" /> rota em curso</span><span><i className="legend idle" /> não acionado</span></div>
        </main>

        <aside className="orchestrator-rail decision-rail">
          <RailHeading icon={<Network size={17} />} title="DECISÃO ATUAL" />
          <div className={`route-card ${stream.isStreaming ? 'active' : ''}`}><span>ROTA</span><strong>{view.route}</strong></div>
          <p className="decision-description">{view.detail}</p>
          <div className="decision-steps">
            <DecisionStep label="Solicitação recebida" detail={messages.length ? 'Entrada da conversa local' : 'Aguardando entrada'} state={messages.length ? 'done' : 'idle'} />
            <DecisionStep label="Análise e compreensão" detail={stream.isStreaming ? 'Interpretação em curso' : 'Sem processamento em curso'} state={stream.isStreaming ? 'current' : 'idle'} />
            <DecisionStep label="Modelo local" detail={stream.isStreaming ? 'Gerando estratégia de resposta' : view.localModel} state={stream.isStreaming ? 'current' : activeNodeIds.has('model') ? 'done' : 'idle'} />
            <DecisionStep label={view.activeDestination === 'tool' ? 'Ferramenta' : view.activeDestination === 'research' ? 'Pesquisa' : 'Roteamento'} detail={view.activeDestination === 'tool' ? 'Chamada de ferramenta em curso' : view.activeDestination === 'research' ? 'Coleta de informações em curso' : 'Nenhum destino externo acionado'} state={view.activeDestination ? 'current' : 'idle'} />
            <DecisionStep label="Consolidação e resposta" detail={stream.isStreaming ? 'Aguardando conclusão' : 'Sem resposta pendente'} state="idle" />
          </div>
          <div className="no-external"><ShieldCheck size={16} /><span>Nenhuma integração externa ativa</span></div>
        </aside>
      </div>

      <section className="local-timeline" aria-label="Linha do tempo local">
        <div className="timeline-title"><Radio size={16} /><strong>Linha do tempo</strong><span>eventos locais</span></div>
        <div className="timeline-events">
          {view.recentLogs.length ? view.recentLogs.map((entry, index) => <TimelineEvent key={`${entry.timestamp}-${index}`} entry={entry} />) : <div className="timeline-empty"><Sparkles size={15} /> Aguardando uma atividade na sessão para construir a linha do tempo.</div>}
        </div>
      </section>
    </div>
  );
}

function RailHeading({ icon, title, status, live }: { icon: ReactNode; title: string; status?: string; live?: boolean }) {
  return <div className="rail-heading"><div>{icon}<strong>{title}</strong></div>{status && <span className={live ? 'live' : ''}><i />{status}</span>}</div>;
}

function Health({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function ActivityBars({ count }: { count: number }) {
  const values = [18, 31, 24, 45, 33, 58, 39, 67, 44, 52, 76, 61, 84, 58, 47, 70];
  return <div className="activity-bars" aria-label={`${count} sinais na sessão`}>{values.map((value, index) => <i key={index} style={{ height: `${count ? Math.min(100, value + count * 2) : 10}%` }} />)}</div>;
}

function OrbitNode({ node }: { node: NodeState }) {
  const Icon = nodeIcons[node.id];
  return <div className={`orbit-node ${node.active ? 'observed' : ''} ${node.current ? 'current' : ''}`} style={{ left: `${node.x}%`, top: `${node.y}%` }}><span className="node-icon"><Icon size={18} /></span><div><strong>{node.label}</strong><small>{node.detail}</small></div>{node.count && <b>{node.count}</b>}</div>;
}

function DecisionStep({ label, detail, state }: { label: string; detail: string; state: 'done' | 'current' | 'idle' }) {
  return <div className={`decision-step ${state}`}><i>{state === 'done' ? <Check size={10} /> : null}</i><div><strong>{label}</strong><small>{detail}</small></div></div>;
}

function TimelineEvent({ entry }: { entry: LogEntry }) {
  const error = entry.level === 'error';
  return <div className={`timeline-event ${error ? 'error' : ''}`}><i /><time>{clock(entry.timestamp)}</time><strong>{entry.category === 'tool' ? 'Ferramenta' : entry.category === 'model' ? 'Modelo' : entry.category === 'chat' ? 'Conversa' : 'Servidor'}</strong><span>{entry.message}</span></div>;
}
