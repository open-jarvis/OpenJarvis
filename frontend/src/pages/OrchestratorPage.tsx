import { useMemo, useState } from 'react';
import type { WheelEvent } from 'react';
import {
  Box,
  Crosshair,
  Database,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import type { ChatMessage, ToolCallInfo } from '../types';
import { useAppStore } from '../lib/store';
import './orchestrator.css';

type NodeKind = 'core' | 'context' | 'source' | 'skill';
type SkillState = 'ready' | 'active' | 'locked' | 'pending';

interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  detail: string;
  x: number;
  y: number;
  size: number;
  state?: SkillState;
}

interface GraphLink {
  source: string;
  target: string;
  kind: 'context' | 'knowledge' | 'skill';
}

interface GraphModel {
  nodes: GraphNode[];
  links: GraphLink[];
  skillCount: number;
  activeSkillCount: number;
  readySkillCount: number;
  sourceCount: number;
  contextCount: number;
}

interface Camera {
  scale: number;
}

const CAMERA_DEFAULT: Camera = { scale: 1 };
const CORE_ID = 'openjarvis-orchestrator';

/**
 * The semi-orbit is a stable capability map for the personal-safe profile.
 * It intentionally describes both capabilities currently available and the
 * private boundaries the user has not authorised yet.
 */
const SKILL_CATALOG = [
  { id: 'reasoning', label: 'RACIOCÍNIO', ready: true, detail: 'motor local' },
  { id: 'calculator', label: 'CÁLCULO', ready: true, detail: 'motor local' },
  { id: 'memory', label: 'MEMÓRIA', ready: false, detail: 'não configurada' },
  { id: 'knowledge', label: 'CONHECIMENTO', ready: false, detail: 'base não conectada' },
  { id: 'research', label: 'PESQUISA', ready: false, detail: 'rede bloqueada' },
  { id: 'files', label: 'ARQUIVOS', ready: false, detail: 'sem diretórios autorizados' },
  { id: 'obsidian', label: 'OBSIDIAN', ready: false, detail: 'aguardando autorização' },
] as const;

function catalogSkillId(tool: string) {
  const name = tool.toLowerCase();
  if (name === 'think' || name.includes('reason')) return 'reasoning';
  if (name.includes('calcul')) return 'calculator';
  if (name.includes('memory')) return 'memory';
  if (name.includes('knowledge') || name.includes('kg_')) return 'knowledge';
  if (name.includes('search') || name.includes('web') || name.includes('http')) return 'research';
  if (name.includes('file')) return 'files';
  if (name.includes('obsidian')) return 'obsidian';
  return null;
}

function compact(text: string, max = 25) {
  const trimmed = text.replace(/\s+/g, ' ').trim();
  return trimmed.length > max ? `${trimmed.slice(0, max - 1)}…` : trimmed || 'Sem conteúdo';
}

function toolCalls(messages: ChatMessage[]) {
  return messages.flatMap((message) => (message.toolCalls ?? []).map((call) => ({ call, message })));
}

function arcPosition(index: number, total: number) {
  const angle = total <= 1 ? 0 : -72 + (index / (total - 1)) * 144;
  const radians = (angle * Math.PI) / 180;
  // A compact right-hand rail leaves enough vertical separation for twelve
  // skills while keeping labels and status text inside the canvas.
  return { x: 775 + Math.cos(radians) * 76, y: 325 + Math.sin(radians) * 176 };
}

/**
 * Converts only data already held by the browser into graph data. A future
 * local knowledge connector can add `source` nodes here without changing the
 * camera, graph renderer, skills arc, or interaction model.
 */
function buildGraph(messages: ChatMessage[]): GraphModel {
  const visibleMessages = messages.slice(-14);
  const nodes: GraphNode[] = [{
    id: CORE_ID, kind: 'core', label: 'ORQUESTRADOR', detail: 'núcleo local', x: 500, y: 325, size: 20,
  }];
  const links: GraphLink[] = [];

  visibleMessages.forEach((message, index) => {
    const angle = -138 + (index / Math.max(visibleMessages.length - 1, 1)) * 276;
    const radians = (angle * Math.PI) / 180;
    const radius = 130 + (index % 3) * 45;
    const id = `context-${message.id}`;
    nodes.push({
      id,
      kind: 'context',
      label: message.role === 'user' ? 'SOLICITAÇÃO' : 'RESPOSTA',
      detail: compact(message.content),
      x: 500 + Math.cos(radians) * radius,
      y: 325 + Math.sin(radians) * (radius * 0.72),
      size: message.role === 'user' ? 6 : 5,
    });
    links.push({ source: CORE_ID, target: id, kind: 'context' });

    (message.researchSources ?? []).slice(0, 3).forEach((source, sourceIndex) => {
      const sourceId = `source-${message.id}-${source.ref}`;
      const sourceAngle = radians + (sourceIndex - 1) * 0.26;
      nodes.push({
        id: sourceId,
        kind: 'source',
        label: 'FONTE',
        detail: compact(source.title || source.sender || 'Fonte de pesquisa'),
        x: 500 + Math.cos(sourceAngle) * (radius + 85),
        y: 325 + Math.sin(sourceAngle) * ((radius + 85) * 0.72),
        size: 4,
      });
      links.push({ source: id, target: sourceId, kind: 'knowledge' });
    });
  });

  const calls = toolCalls(visibleMessages);
  const activeCalls = new Map<string, { call: ToolCallInfo; message: ChatMessage }>();
  calls.forEach(({ call, message }) => {
    const id = catalogSkillId(call.tool);
    if (id && !activeCalls.has(id)) activeCalls.set(id, { call, message });
  });

  SKILL_CATALOG.forEach((skill, index) => {
    const point = arcPosition(index, SKILL_CATALOG.length);
    const activeCall = activeCalls.get(skill.id);
    const state: SkillState = activeCall ? 'active' : skill.ready ? 'ready' : skill.id === 'obsidian' ? 'pending' : 'locked';
    const detail = activeCall ? `${activeCall.call.tool} · em uso` : skill.detail;
    const skillId = `skill-${skill.id}`;
    nodes.push({ id: skillId, kind: 'skill', label: skill.label, detail, x: point.x, y: point.y, size: 3.5, state });
    if (activeCall) links.push({ source: `context-${activeCall.message.id}`, target: skillId, kind: 'skill' });
  });

  return {
    nodes,
    links,
    skillCount: SKILL_CATALOG.length,
    activeSkillCount: activeCalls.size,
    readySkillCount: SKILL_CATALOG.filter((skill) => skill.ready).length,
    sourceCount: nodes.filter((node) => node.kind === 'source').length,
    contextCount: visibleMessages.length,
  };
}

export function OrchestratorPage() {
  const messages = useAppStore((state) => state.messages);
  const stream = useAppStore((state) => state.streamState);
  const graph = useMemo(() => buildGraph(messages), [messages]);
  const [camera, setCamera] = useState<Camera>(CAMERA_DEFAULT);
  const [selectedNodeId, setSelectedNodeId] = useState(CORE_ID);
  const selected = graph.nodes.find((node) => node.id === selectedNodeId) ?? graph.nodes[0];
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const constellationNodes = graph.nodes.filter((node) => node.kind !== 'skill');
  const skillNodes = graph.nodes.filter((node) => node.kind === 'skill');
  const constellationLinks = graph.links.filter((link) => link.kind !== 'skill');
  const skillLinks = graph.links.filter((link) => link.kind === 'skill');
  const selectedSkillId = selected?.kind === 'skill' ? selected.id.replace('skill-', '') : null;
  const selectedSkillCall = selectedSkillId
    ? toolCalls(messages).find(({ call }) => catalogSkillId(call.tool) === selectedSkillId)
    : undefined;

  const changeZoom = (delta: number) => setCamera((current) => ({
    ...current,
    scale: Math.min(2.8, Math.max(0.45, Number((current.scale + delta).toFixed(2)))),
  }));

  const handleWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    changeZoom(event.deltaY < 0 ? 0.12 : -0.12);
  };

  return (
    <div className="knowledge-page">
      <section className="knowledge-stage" aria-label="Grafo de conhecimento e skills">
        <div className="constellation-bg" aria-hidden="true" />
        <div className="graph-header-floating">
          <div><span>MAPA DE CONHECIMENTO</span><strong>{stream.isStreaming ? 'ORQUESTRANDO EM TEMPO REAL' : 'SESSÃO LOCAL'}</strong></div>
          <span className={stream.isStreaming ? 'is-live' : ''}><i />{stream.isStreaming ? 'grafo em atualização' : 'grafo navegável'}</span>
        </div>

        <aside className="graph-inspector-floating">
          <div className="floating-label"><Crosshair size={13} /> {selected?.kind === 'skill' ? 'SKILL EM FOCO' : 'SINAL EM FOCO'}</div>
          <strong>{selected?.label ?? 'ORQUESTRADOR'}</strong>
          <p>{selected?.detail ?? 'núcleo local'}</p>
          <div className="inspector-meta"><span>{selected?.kind === 'skill' ? 'skill' : selected?.kind === 'source' ? 'fonte de conhecimento' : selected?.kind === 'context' ? 'contexto da sessão' : 'núcleo local'}</span><span>local</span></div>
          <div className="skill-activity">
            <span>EXECUÇÃO NA SESSÃO</span>
            {selected?.kind !== 'skill' && <p>Selecione uma skill para acompanhar como ela foi usada.</p>}
            {selected?.kind === 'skill' && !selectedSkillCall && <p>Sem execução registrada nesta sessão.</p>}
            {selectedSkillCall && <>
              <strong className={`skill-call-status ${selectedSkillCall.call.status}`}>{selectedSkillCall.call.status === 'success' ? 'concluída' : selectedSkillCall.call.status === 'error' ? 'atenção necessária' : 'em execução'}</strong>
              <p>{selectedSkillCall.call.result ? compact(selectedSkillCall.call.result, 88) : 'Chamada registrada; aguardando saída resumida.'}</p>
            </>}
          </div>
        </aside>

        <div className="graph-source-floating">
          <Database size={15} />
          <div><strong>FONTES DE CONHECIMENTO</strong><span>{graph.sourceCount ? `${graph.sourceCount} fonte${graph.sourceCount === 1 ? '' : 's'} na sessão` : 'Nenhuma base conectada'}</span></div>
          <small>Obsidian: aguardando autorização</small>
        </div>

        <div className="graph-controls" aria-label="Controles de navegação do grafo">
          <button onClick={() => changeZoom(0.16)} title="Aproximar"><Plus size={17} /></button>
          <button onClick={() => changeZoom(-0.16)} title="Afastar"><Minus size={17} /></button>
          <button onClick={() => setCamera(CAMERA_DEFAULT)} title="Centralizar"><Maximize2 size={15} /></button>
          <span>{Math.round(camera.scale * 100)}%</span>
        </div>
        <div className="graph-gesture-hint"><Crosshair size={13} /> scroll para zoom · núcleo ancorado</div>

        <svg
          className="knowledge-canvas"
          viewBox="0 0 1000 650"
          role="application"
          aria-label="Grafo de conhecimento local: use a rolagem para aproximar ou afastar o núcleo ancorado"
          onWheel={handleWheel}
        >
          <defs>
            <radialGradient id="coreGlow"><stop offset="0%" stopColor="#1de5ff" stopOpacity=".4" /><stop offset="65%" stopColor="#0d7fb5" stopOpacity=".11" /><stop offset="100%" stopColor="#06111d" stopOpacity="0" /></radialGradient>
            <filter id="nodeGlow"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          </defs>
          <g transform={`translate(500 325) scale(${camera.scale}) translate(-500 -325)`}>
            <g className="constellation-motion">
              <circle className="constellation-aura" cx="500" cy="325" r="238" />
              <circle className="constellation-aura constellation-aura-inner" cx="500" cy="325" r="128" />
              {constellationLinks.map((link) => {
                const source = nodeById.get(link.source);
                const target = nodeById.get(link.target);
                if (!source || !target) return null;
                return <line key={`${link.source}-${link.target}`} className={`graph-link ${link.kind}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} />;
              })}
              {constellationNodes.map((node) => <GraphNode key={node.id} node={node} selected={node.id === selectedNodeId} onSelect={setSelectedNodeId} />)}
            </g>
          </g>
          <g className="skills-layer">
            <path className="skills-orbit" d="M 798 158 Q 904 325 798 492" />
            {skillLinks.map((link) => {
              const source = nodeById.get(link.source);
              const target = nodeById.get(link.target);
              if (!source || !target) return null;
              return <line key={`${link.source}-${link.target}`} className={`graph-link ${link.kind} static-skill-link`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} />;
            })}
            {skillNodes.map((node) => <GraphNode key={node.id} node={node} selected={node.id === selectedNodeId} onSelect={setSelectedNodeId} />)}
          </g>
        </svg>

        <div className="skills-arc-label"><Sparkles size={14} /><span>SKILLS</span><small>{graph.activeSkillCount ? `${graph.activeSkillCount} em uso` : `${graph.readySkillCount} prontas · ${graph.skillCount - graph.readySkillCount} protegidas`}</small></div>
        <div className="knowledge-legend"><span><i className="context" /> contexto</span><span><i className="source" /> conhecimento</span><span><i className="skill" /> skill</span><span><i className="core" /> orquestrador</span></div>
      </section>

      <footer className="graph-footer">
        <div><RotateCcw size={14} /><span>Constelação em rotação contínua · núcleo ancorado</span></div>
        <div><Box size={14} /><span>{graph.contextCount} contexto{graph.contextCount === 1 ? '' : 's'} · {graph.activeSkillCount} em uso · {graph.sourceCount} fonte{graph.sourceCount === 1 ? '' : 's'}</span></div>
      </footer>
    </div>
  );
}

function GraphNode({ node, selected, onSelect }: { node: GraphNode; selected: boolean; onSelect: (id: string) => void }) {
  const radius = node.kind === 'core' ? 23 : node.size;
  const labelOffset = node.kind === 'skill' ? 6 : 9;
  return (
    <g className={`graph-node ${node.kind} ${node.state ?? ''} ${selected ? 'selected' : ''}`} onClick={(event) => { event.stopPropagation(); onSelect(node.id); }} role="button" tabIndex={0} aria-label={`${node.label}: ${node.detail}`}>
      {node.kind === 'core' && <circle className="core-halo" cx={node.x} cy={node.y} r="72" fill="url(#coreGlow)" />}
      <circle className="node-ring" cx={node.x} cy={node.y} r={radius + (node.kind === 'skill' ? 2 : 2)} />
      <circle className="node-star" cx={node.x} cy={node.y} r={radius} filter={node.kind === 'core' || node.kind === 'skill' ? 'url(#nodeGlow)' : undefined} />
      <text className="node-label" x={node.x + radius + labelOffset} y={node.y - 2}>{node.label}</text>
      <text className="node-detail" x={node.x + radius + labelOffset} y={node.y + 8}>{node.detail}</text>
    </g>
  );
}
