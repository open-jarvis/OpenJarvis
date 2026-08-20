# Showcase screenshots

This directory holds the hero screenshot for each Showcase entry in `docs/showcase/`. Convention is one file per entry, named to match the entry's slug:

| Entry | Screenshot path |
|---|---|
| `docs/showcase/morning-brief.md` | `morning-brief.png` |
| `docs/showcase/persistent-memory.md` | `persistent-memory.png` |
| `docs/showcase/cost-savings.md` | `cost-savings.png` |
| `docs/showcase/discord-companion.md` | `discord-companion.png` |
| `docs/showcase/coding-assistant.md` | `coding-assistant.png` |

## Conventions

| | |
|---|---|
| Format | PNG, sRGB, no alpha channel |
| Size | 1600×1000 (4:2.5 — wider than 16:9, so screenshots don't get letterboxed in the docs grid) |
| File size | Under 400 KB after `pngquant --quality 70-90 --speed 1` |
| Loading | All `<img>` and `<figure>` tags in showcase pages use `loading=lazy` — these images are below the fold on the gallery page |

## What to redact

- Real email addresses
- API keys, OAuth tokens, anything starting with `sk-`, `ghp_`, `xox`, `eyJ`
- Personal phone numbers
- Conversation partners' faces or full names (unless they've signed off)
- File paths that include other people's home directories

## What to keep

- Model names ("llama3.1:8b", "qwen2.5:14b") — they're informative
- Timestamps — proves the screenshot is recent
- Dollar amounts on the leaderboard — the whole point
- Emoji reactions, your own first name, your own avatar

## Placeholder PNGs

This directory ships with no images on the initial PR. The Showcase pages reference image paths that don't exist yet — MkDocs will render a broken-image placeholder, and the figcaption still conveys what should be there. Real screenshots arrive in follow-up PRs as Showcase entries are populated with each contributor's actual setup.

If you're contributing the first real entry, drop your PNG at `docs/assets/showcase/<your-slug>.png` in the same PR that adds your markdown page. The image filename must match the slug used in the showcase page's `<img>` reference.

## Regenerating screenshots in bulk

A future enhancement (tracked as PR #3 in the showcase-tier roadmap) will add `scripts/showcase/regen_screenshots.py` — a Playwright-driven pipeline that boots a demo `jarvis serve` against a sealed config and captures fresh screenshots for every showcase entry on each release tag. Until that lands, screenshots are contributed manually by each Showcase author.
