# CLAUDE.md

## What This Is

NasTech HUD Web UI — the browser version of nastech-hud (TUI consciousness monitor). FastAPI backend + React frontend. Reads from `~/.nastech/` to display agent state.

## Running

```bash
# Full stack (production)
./install.sh && nastech-hudui

# Development
nastech-hudui --dev              # backend with auto-reload on :3001
cd frontend && npm run dev      # frontend dev server on :5173
```

Requires Python 3.11+ and Node 18+. Backend depends on nastech-hud package for collectors.

## Architecture

```
backend/main.py         FastAPI app, CORS, static files
backend/api/*.py        One route file per data domain
backend/api/serialize.py  Dataclass → JSON conversion
backend/static/         Built frontend (copied from frontend/dist)
frontend/src/           React + Vite + TypeScript + Tailwind
frontend/src/hooks/     Theme system (useTheme), SWR fetching (useApi)
frontend/src/components/ One panel component per tab/data source
frontend/src/index.css  Theme CSS variables, panel system, effects
```

**Data flow:** nastech_hud.collectors → FastAPI endpoints → SWR fetch → React panels

## Key Patterns

- Backend imports nastech_hud.collectors directly — no data logic duplication
- 4 themes as CSS custom properties on `[data-theme]` attribute
- Panel component with title-in-border pattern
- SWR for data fetching with configurable refresh intervals
- Keyboard shortcuts (1-9 tabs, t theme, r refresh)

## API Endpoints

All under `/api/`:
state, memory, sessions, skills, cron, projects, health, profiles, patterns, corrections, agents, timeline
