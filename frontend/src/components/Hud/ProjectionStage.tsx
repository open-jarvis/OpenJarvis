import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { X } from 'lucide-react';
import type { HudCard } from '../../lib/hud/tool-cards';
import { HudPanel } from './HudPanels';

function CardBody({ card }: { card: HudCard }) {
  switch (card.kind) {
    case 'metric':
      return <p className="hud-card-metric">{card.value}</p>;
    case 'list':
      return (
        <ol className="hud-card-list">
          {card.items.map((item) => (
            <li key={`${item.title}-${item.url ?? ''}`}>
              {item.url ? (
                // El enlace viene de internet: se abre aparte y sin acceso a esta página.
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.title}
                </a>
              ) : (
                <span>{item.title}</span>
              )}
              {item.snippet && <p>{item.snippet}</p>}
            </li>
          ))}
        </ol>
      );
    case 'code':
      return (
        <>
          {card.code && <pre className="hud-card-code">{card.code}</pre>}
          <pre className="hud-card-output">{card.output || '(sin salida)'}</pre>
        </>
      );
    case 'document':
      return (
        <div className="hud-card-document">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{card.markdown}</ReactMarkdown>
        </div>
      );
    case 'text':
      return <p className="hud-card-text">{card.body}</p>;
  }
}

interface ProjectionStageProps {
  cards: HudCard[];
  onDismiss: (id: string) => void;
}

/** Zona donde Jarvis "muestra cosas": una tarjeta por resultado, la más reciente arriba. */
export function ProjectionStage({ cards, onDismiss }: ProjectionStageProps) {
  return (
    <HudPanel title="Proyección" className="hud-projection">
      {cards.length === 0 ? (
        <p className="hud-empty">Aquí aparecerá lo que Jarvis consulte o calcule.</p>
      ) : (
        cards.map((card) => (
          <article key={card.id} className={`hud-card${card.failed ? ' is-failed' : ''}`}>
            <header className="hud-card-header">
              <span className="hud-card-source">{card.source}</span>
              <span className="hud-card-title">{card.title}</span>
              <button
                type="button"
                className="hud-icon-button"
                onClick={() => onDismiss(card.id)}
                aria-label={`Cerrar tarjeta ${card.title}`}
              >
                <X size={14} />
              </button>
            </header>
            <CardBody card={card} />
          </article>
        ))
      )}
    </HudPanel>
  );
}
