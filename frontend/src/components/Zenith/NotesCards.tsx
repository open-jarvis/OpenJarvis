import { useCallback, useEffect, useMemo, useState } from 'react';
import { Skyline } from './ZenArt';
import { IconBookmark } from './icons';
import { lifeApi, localDay, weekOf, type JournalEntry } from './lifeApi';
import { QUOTE_FILTERS, quotesFor, type QuoteCategory } from './zenMath';

const SCENES = ['sea', 'mountain', 'city'] as const;
const QUOTES_SHOWN = 4;

export function QuotesCard() {
  const [filter, setFilter] = useState<'all' | QuoteCategory | 'saved'>('all');
  const [saved, setSaved] = useState<string[]>([]);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    lifeApi.bookmarks().then((r) => setSaved(r.quotes)).catch(() => undefined);
  }, []);

  const toggle = async (text: string) => {
    const on = !saved.includes(text);
    setSaved((s) => (on ? [...s, text] : s.filter((q) => q !== text)));
    await lifeApi.bookmark(text, on).catch(() => undefined);
  };

  const list = filter === 'saved'
    ? quotesFor('all').filter((q) => saved.includes(q.text))
    : quotesFor(filter);

  return (
    <section className="zen-card zen-quotes" id="zen-quotes" aria-label="Quotes">
      <header className="zen-card__bar"><span className="zen-eyebrow">Quotes</span></header>
      <div className="zen-filters" role="tablist">
        {[...QUOTE_FILTERS, 'saved' as const].map((f) => (
          <button key={f} type="button" role="tab" aria-selected={filter === f} className={filter === f ? 'is-active' : ''} onClick={() => setFilter(f)}>
            {f}
          </button>
        ))}
      </div>
      <ul className="zen-quote-list">
        {list.length === 0 && <li className="zen-empty">Bookmark a quote to keep it here.</li>}
        {(showAll ? list : list.slice(0, QUOTES_SHOWN)).map((q, i) => (
          <li key={q.text} className="zen-quote">
            <Skyline scene={SCENES[i % SCENES.length]} figure={i % 2 === 0} className="zen-quote__art" />
            <span className="zen-quote__mark" aria-hidden="true">“</span>
            <p>{q.text}</p>
            <button type="button" className={`zen-quote__save ${saved.includes(q.text) ? 'is-on' : ''}`} aria-pressed={saved.includes(q.text)} aria-label="Bookmark quote" onClick={() => void toggle(q.text)}>
              <IconBookmark filled={saved.includes(q.text)} />
            </button>
          </li>
        ))}
      </ul>
      {list.length > QUOTES_SHOWN && (
        <div className="zen-row" style={{ justifyContent: 'center' }}>
          <button type="button" className="zen-link zen-more" onClick={() => setShowAll((s) => !s)}>
            {showAll ? 'Show fewer' : `Show all ${list.length}`}
          </button>
        </div>
      )}
    </section>
  );
}

const WEEKDAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function JournalCard({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [anchor, setAnchor] = useState(() => new Date());
  const [selected, setSelected] = useState(() => localDay());
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [draft, setDraft] = useState('');
  const days = useMemo(() => weekOf(anchor), [anchor]);
  const start = localDay(days[0]);
  const end = localDay(days[6]);

  const load = useCallback(() => {
    lifeApi.journal(start, end).then((r) => setEntries(r.entries)).catch(() => undefined);
  }, [start, end]);
  useEffect(load, [load, refreshKey]);

  const shift = (weeks: number) => {
    const d = new Date(anchor);
    d.setDate(d.getDate() + weeks * 7);
    setAnchor(d);
  };

  const save = async () => {
    if (!draft.trim()) return;
    await lifeApi.addJournal(draft, selected).catch(() => undefined);
    setDraft('');
    load();
    onChanged();
  };
  const remove = async (id: string) => {
    await lifeApi.deleteJournal(id).catch(() => undefined);
    load();
    onChanged();
  };

  const dayEntries = entries.filter((e) => e.day === selected);
  const today = localDay();
  const month = days[3].toLocaleDateString([], { month: 'long', year: 'numeric' });

  return (
    <section className="zen-card zen-journal" id="zen-journal" aria-label="Journal">
      <header className="zen-card__bar"><span className="zen-eyebrow">Journal</span></header>
      <div className="zen-cal">
        <div className="zen-cal__head">
          <button type="button" aria-label="Previous week" onClick={() => shift(-1)}>‹</button>
          <span>{month}</span>
          <button type="button" aria-label="Next week" onClick={() => shift(1)}>›</button>
        </div>
        <div className="zen-cal__days">
          {days.map((d, i) => {
            const key = localDay(d);
            const has = entries.some((e) => e.day === key);
            return (
              <button key={key} type="button" className={`${key === selected ? 'is-selected' : ''} ${key === today ? 'is-today' : ''}`} onClick={() => setSelected(key)} aria-pressed={key === selected}>
                <small>{WEEKDAY[i]}</small>
                <b>{d.getDate()}</b>
                {has && <i aria-label="has an entry" />}
              </button>
            );
          })}
        </div>
      </div>
      <div className="zen-entries">
        <span className="zen-eyebrow">{selected === today ? "Today's entry" : new Date(`${selected}T12:00:00`).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}</span>
        {dayEntries.map((e) => (
          <article key={e.id} className="zen-entry">
            <p>{e.text}</p>
            <footer>
              <time>{new Date(e.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
              <button type="button" className="zen-link" onClick={() => void remove(e.id)}>Delete</button>
            </footer>
          </article>
        ))}
        <form className="zen-entry-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="How did today go? (or tell Jarvis: “write in my journal…”)" aria-label="Journal entry" maxLength={5000} rows={3} />
          <button type="submit" className="zen-btn zen-btn--solid" disabled={!draft.trim()}>Save entry</button>
        </form>
      </div>
    </section>
  );
}
