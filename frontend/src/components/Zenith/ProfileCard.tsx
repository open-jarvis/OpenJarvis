import { useState, type ReactNode } from 'react';
import { Emblem } from './ZenArt';
import { lifeApi, type LifeSummary } from './lifeApi';

export interface NavItem {
  id: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  badge?: number;
}

const initialsOf = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('') || 'J';

export function ProfileCard({
  summary,
  nav,
  active,
  onChanged,
}: {
  summary: LifeSummary | null;
  nav: NavItem[];
  active: string;
  onChanged: () => void;
}) {
  const profile = summary?.profile ?? { name: 'Commander', motto: 'Focus • Discipline • Freedom' };
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(profile.name);
  const [motto, setMotto] = useState(profile.motto);

  const save = async () => {
    await lifeApi.updateProfile(name, motto).catch(() => undefined);
    setEditing(false);
    onChanged();
  };

  return (
    <section className="zen-card zen-profile" aria-label="Profile">
      <header className="zen-card__bar">
        <span className="zen-eyebrow">My profile</span>
      </header>
      <div className="zen-profile__avatar">
        <Emblem initials={initialsOf(profile.name)} />
      </div>
      {editing ? (
        <form className="zen-profile__edit" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Your name" maxLength={40} />
          <input value={motto} onChange={(e) => setMotto(e.target.value)} aria-label="Your motto" maxLength={80} />
          <div className="zen-row">
            <button type="submit" className="zen-btn zen-btn--solid">Save</button>
            <button type="button" className="zen-btn" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          className="zen-profile__name"
          onClick={() => { setName(profile.name); setMotto(profile.motto); setEditing(true); }}
          title="Edit your name and motto"
        >
          <strong>{profile.name}</strong>
          <span>{profile.motto}</span>
        </button>
      )}
      <div className="zen-level" title={`${summary?.level_progress ?? 0}/100 XP to the next level`}>
        <span>Level {summary?.level ?? 1}</span>
        <i style={{ width: `${summary?.level_progress ?? 0}%` }} />
      </div>
      <dl className="zen-stats">
        <div><dt>Days</dt><dd>{summary?.stats.days ?? 0}</dd></div>
        <div><dt>Habits</dt><dd>{summary?.stats.habits ?? 0}</dd></div>
        <div><dt>Focus hrs</dt><dd>{(summary?.stats.focus_hours ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 })}</dd></div>
      </dl>
      <nav className="zen-nav" aria-label="Sections">
        {nav.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`zen-nav__item ${item.id === active ? 'is-active' : ''}`}
            onClick={item.onSelect}
          >
            <span className="zen-nav__icon">{item.icon}</span>
            <span className="zen-nav__label">{item.label}</span>
            {item.badge ? <span className="zen-badge">{item.badge}</span> : null}
            <span className="zen-nav__chev" aria-hidden="true">›</span>
          </button>
        ))}
      </nav>
    </section>
  );
}
