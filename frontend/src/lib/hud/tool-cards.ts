/**
 * Traduce lo que hizo el agente (una llamada a herramienta o una respuesta)
 * en el modelo de una tarjeta para la zona de proyección del HUD.
 */

export interface ToolCallOutcome {
  id: string;
  timestamp: number;
  tool: string;
  args: Record<string, unknown>;
  result: string;
  success: boolean;
  /** Segundos que tardó la herramienta. */
  latency?: number;
}

export interface SearchItem {
  title: string;
  url?: string;
  snippet?: string;
}

interface CardBase {
  id: string;
  timestamp: number;
  /** Nombre de la herramienta que originó la tarjeta, o "respuesta". */
  source: string;
  title: string;
  failed?: boolean;
}

export type HudCard =
  | (CardBase & { kind: 'metric'; value: string })
  | (CardBase & { kind: 'list'; items: SearchItem[] })
  | (CardBase & { kind: 'code'; code: string; output: string })
  | (CardBase & { kind: 'text'; body: string })
  | (CardBase & { kind: 'document'; markdown: string });

const MAX_BODY_CHARS = 1200;
const MAX_LABEL_CHARS = 60;
/** A partir de esta longitud conviene leer la respuesta además de oírla. */
const LONG_ANSWER_CHARS = 600;

/** Herramientas de razonamiento interno: no producen nada que mostrar. */
const SILENT_TOOLS = new Set(['think']);
const CODE_TOOLS: Record<string, string> = {
  code_interpreter: 'code',
  shell_exec: 'command',
  docker_shell_exec: 'command',
};
/** Argumento que mejor resume cada llamada, en orden de preferencia. */
const MAIN_ARGUMENT_KEYS = [
  'query',
  'expression',
  'location',
  'command',
  'code',
  'path',
  'url',
  'content',
];

function truncate(text: string, maxChars: number): string {
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text;
}

function mainArgument(args: Record<string, unknown>): string {
  for (const key of MAIN_ARGUMENT_KEYS) {
    const value = args[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

/** Etiqueta corta de una llamada para el registro de actividad. */
export function describeToolCall(tool: string, args: Record<string, unknown>): string {
  const argument = mainArgument(args).replace(/\s+/g, ' ');
  return argument ? `${tool} · ${truncate(argument, MAX_LABEL_CHARS)}` : tool;
}

/** "9315.0" se muestra como "9315"; lo que no es un número se deja igual. */
function formatNumber(raw: string): string {
  const trimmed = raw.trim();
  return /^-?\d+(\.\d+)?$/.test(trimmed) ? String(Number(trimmed)) : trimmed;
}

/** Solo se enlazan direcciones web: el resultado viene de internet y no es confiable. */
function safeUrl(raw: string): string | undefined {
  return /^https?:\/\//i.test(raw) ? raw : undefined;
}

/** web_search devuelve bloques "### título / Source: url / Summary: texto". */
function parseSearchResults(result: string): SearchItem[] {
  return result
    .split(/^###\s+/m)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const [title, ...lines] = block.split('\n');
      const field = (name: string) =>
        lines.find((line) => line.startsWith(`${name}:`))?.slice(name.length + 1).trim();
      const source = field('Source');
      return {
        title: title.trim(),
        url: source ? safeUrl(source) : undefined,
        snippet: field('Summary'),
      };
    });
}

/** Devuelve la tarjeta de una llamada terminada, o null si no hay nada que proyectar. */
export function buildToolCard(outcome: ToolCallOutcome): HudCard | null {
  const { id, timestamp, tool, args, result, success } = outcome;
  if (SILENT_TOOLS.has(tool)) return null;

  const base: CardBase = {
    id,
    timestamp,
    source: tool,
    title: mainArgument(args) || tool,
    failed: success ? undefined : true,
  };
  const textCard: HudCard = {
    ...base,
    kind: 'text',
    title: tool,
    body: truncate(result, MAX_BODY_CHARS),
  };
  // Un fallo se muestra tal cual: el mensaje de error es lo útil.
  if (!success) return textCard;

  if (tool === 'calculator') {
    return { ...base, kind: 'metric', value: formatNumber(result) };
  }
  if (tool === 'web_search') {
    const items = parseSearchResults(result);
    return items.length > 0 ? { ...base, kind: 'list', items } : textCard;
  }
  if (tool in CODE_TOOLS) {
    const code = args[CODE_TOOLS[tool]];
    return {
      ...base,
      kind: 'code',
      title: tool,
      code: typeof code === 'string' ? code : '',
      output: truncate(result, MAX_BODY_CHARS),
    };
  }
  return textCard;
}

/** Proyecta la respuesta cuando trae código, tablas o es larga para solo oírla. */
export function buildAnswerCard(
  id: string,
  answer: string,
  timestamp: number,
  /** La orden que originó la respuesta; sirve de título. */
  title: string,
): HudCard | null {
  const hasCode = answer.includes('```');
  const hasTable = /^\|.+\|\s*$/m.test(answer);
  if (!hasCode && !hasTable && answer.length < LONG_ANSWER_CHARS) return null;
  return {
    id,
    timestamp,
    source: 'respuesta',
    title,
    kind: 'document',
    markdown: answer,
  };
}
