# UI Rules

Frontend conventions for `frontend/` (Vite + React 19). Architecture and folder
layout live in [frontend-architecture.md](frontend-architecture.md); this file is
the coding/styling rulebook.

## Components & code style

- **Arrow functions only.** `const App = () => { ... }`, never `function App() {}`.
  Applies to components, hooks, and utils.
- **No classes.** Use functions/closures. Error boundaries use the functional
  `react-error-boundary` wrapper, not a hand-written class. Normalized errors are
  plain `Error` objects (`Object.assign(new Error(msg), { status, data })`), not
  custom error classes.
- **One component per file**, named in `PascalCase.jsx`. Named exports for shared
  components; `OverviewPage`-style pages also named-exported.
- **Hooks** `useThing.js`/`useThing` (camelCase), **utils** `camelCase.js`.
- **No barrel `index.js` files** — import directly (avoids circular-import & HMR pain).
- **Context:** provider + `use*` hook co-located in one file per context
  (`AuthContext.jsx`, `ClientContext.jsx`). The `only-export-components` lint rule
  is off because of this.

## Formatting (Prettier)

- **Prettier owns formatting** — write code so the Prettier extension's output is
  the committed form (format-on-save, or `npm run format`). Don't hand-fight it.
- Config in `.prettierrc.json`: **tabs, tab width 4**, double quotes, semicolons,
  trailing commas, 80 print width.

## Styling (Tailwind v4)

- Tailwind v4 via `@tailwindcss/vite`. **No `tailwind.config.js`** — config is
  CSS-first in `src/index.css` under `@theme`.
- **Use semantic theme tokens, not raw colours.** `bg-primary`, `text-content`,
  `border-border`, `bg-success`, `font-display` — defined in `index.css`. Don't
  hardcode `bg-indigo-600`.
- Tokens cover **colour + typography only**. Spacing/radius/sizing use Tailwind's
  built-in scale (`p-4`, `rounded-lg`, `gap-6`). Don't add those to `@theme`.
- Token groups: brand (`primary`, `primary-hover`, `primary-soft`, `on-primary`),
  status (`success`/`warning`/`danger`/`info` + `-soft`), surfaces (`surface`,
  `card`, `border`, `muted`), text (`content`, `content-muted`, `content-subtle`),
  fonts (`font-sans`, `font-display`, `font-mono`).

## Data & errors

- **All HTTP goes through the `api` client** (`lib/axios.js`) — the single shared
  **axios** instance (base URL, Bearer token, request/response logging, error
  normalization in interceptors). Never call `fetch`/`axios` directly in a component.
- **Never fetch in a component.** Go through a feature's `api.js` (thin wrappers
  over the `api` client), consumed via a `useQuery` hook.
- The response interceptor unwraps `response.data`, so `await api.get(...)`
  returns the payload directly. Errors reject with `{ message, status, data }`.
- **Server data → React Query; app state → Context.** See architecture doc.
- **Query keys must include all inputs that scope the data** — at minimum the
  active client id and (for time-windowed endpoints) `days` from `useDateRange()`,
  so switching client/date range refetches. Don't pass `days` as a prop; read it
  from context in the feature hook.
- **Charts:** use `<EChart option={...} />` (`components/charts/`), never import
  `echarts` in a page directly. Keep the option object in the feature; the wrapper
  handles init/resize/theme.
- Three error layers, kept distinct:
  1. `ErrorBoundary` (react-error-boundary) — render crashes (wraps the page in `AppLayout`).
  2. `api` client interceptors (`lib/axios.js`) — normalize HTTP/network failures.
  3. `ErrorState` / `EmptyState` / `Loading` — per-section UI states.
- **Logging:** `import { logger } from "lib/logger"` — never bare `console.*`.
  Levels: `debug/info/warn/error` + `request/response` (API tracing). **Everything
  is silenced in production; in dev everything logs.**

## Env & config

- Frontend env lives in `.env` (gitignored; `.env.example` is committed). Vars must
  be `VITE_`-prefixed to be exposed. Read via `import.meta.env.VITE_*`.
- Primary nav is data-driven from `config/nav.js`; adding a page = one entry there
  + a route in `app/router.jsx` + a feature folder.
