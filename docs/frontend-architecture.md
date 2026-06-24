# Frontend Architecture

Structure and the decisions behind it for `frontend/`. Coding/styling rules are
in [ui-rules.md](ui-rules.md); what each page shows is in
[dashboard-views.md](dashboard-views.md).

## Stack

- **Vite 8 + React 19**, `oxlint` (lint) + **Prettier** (format: tabs, width 4).
- **Tailwind v4** (`@tailwindcss/vite`, CSS-first `@theme` in `index.css`).
- **react-router-dom v7** — routing.
- **@tanstack/react-query v5** — server-state cache.
- **axios** — single shared client instance `api` (`lib/axios.js`).
- **ECharts** — charts, wrapped in `components/charts/EChart.jsx`.
- **react-error-boundary** — functional render-crash boundary (no classes).
- **Context API** — app-owned client state (auth, active client, date range).

## Folder structure (feature-first hybrid)

```
src/
  main.jsx                 # createRoot
  App.jsx                  # <Providers><RouterProvider/></Providers> — wiring only
  index.css                # @import "tailwindcss" + @theme tokens

  app/                     # app-level wiring
    queryClient.js         # QueryClient + global staleTime default
    providers.jsx          # composes all providers (QueryClient > Auth > Client > DateRange)
    router.jsx             # route table (mirrors config/nav.js)

  lib/                     # framework-agnostic, NO React
    axios.js               # shared axios instance `api` + interceptors (token/log/errors/401)
    logger.js              # leveled logger + request/response; silenced in prod
    format.js              # INR currency / number / date formatters
    constants.js           # storage keys, presets, default days/page size, event names

  config/
    nav.js                 # primary nav list — drives Sidebar + routes

  context/                 # global client-state (provider + hook co-located)
    AuthContext.jsx        # token + user; AuthProvider + useAuth
    ClientContext.jsx      # active client switcher; ClientProvider + useClient
    DateRangeContext.jsx   # global `?days=` window; DateRangeProvider + useDateRange

  components/
    ui/                    # domain-agnostic primitives (Button, Card)
    feedback/              # ErrorBoundary, ErrorState, EmptyState, Loading, PagePlaceholder
    charts/                # EChart wrapper + ECharts theme (mirrors index.css tokens)
    auth/                  # LoginModal (login UI; opened from the landing page)

  layout/                  # app shell: AppLayout, Navbar, Sidebar, Footer, DateRangePicker

  routes/                  # non-feature pages + guards: LandingPage, NotFoundPage,
                           #   RequireAuth, RequireAdmin, RedirectIfAuth

  features/                # ONE folder per dashboard page (= per question)
    overview/              # reference impl: api.js + hooks.js + OverviewPage + components/
    analytics/ products/ inventory/ ads/ competition/ scorecard/ settings/
```

## Key decisions

- **Feature-first, not type-first.** Each dashboard page (per dashboard-views.md)
  is a self-contained `features/<x>/` folder owning its `api.js`, `hooks.js`,
  page, and `components/`. Globals (`ui`, `layout`, the two contexts) stay shared.
  Rationale: everything for one feature is in one place; delete = delete the folder.
- **State split:** Context owns *what the app owns* (auth token, current user,
  active client, date range). React Query owns *what the backend owns* (every
  dashboard fetch). They coexist: `ClientContext`/`DateRangeContext` hold the
  active client id and `days`; feature `useQuery` hooks put both in their
  `queryKey`, so switching client **or** date range auto-refetches.
- **Global date range:** `DateRangeContext` holds `days` (presets 7/30/90,
  persisted to localStorage), shown as a Navbar picker. Backend takes only
  `?days=`, so the range is a day-count, not arbitrary from/to. Feature hooks read
  `useDateRange()` rather than taking a `days` prop.
- **`staleTime` = 5 min global default** (`app/queryClient.js`). Data is ~daily
  scraped; override per-query when fresher is needed, or use `refetchInterval`
  for polling. Background refetches don't flip `isLoading` — no spinner flash.
- **Data flow per page:** component → feature `hooks.js` (`useQuery`) → feature
  `api.js` → shared `api` client (`lib/axios.js`) → backend `/api/clients/{clientId}/...`.
- **HTTP via one axios instance** `api` (`lib/axios.js`). Interceptors attach the
  Bearer token, trace requests/responses (dev), unwrap `response.data`, and reject
  with a normalized `{ message, status, data }`. Base URL from `VITE_API_BASE_URL`.
- **Auth:** JWT in `localStorage`, attached by the `api` client as `Bearer`.
  `RequireAuth` guards the app shell (Overview lives at `/overview`). The only
  public route is `/` (marketing landing), behind `RedirectIfAuth` which bounces
  logged-in users to `/overview`. **Login is a modal** (`components/auth/LoginModal`)
  opened from the landing page — there is no `/login` route. A logged-out hit to a
  protected route redirects to `/` with the attempted path as `from`; the landing
  page auto-opens the modal and returns the user there after sign-in. No public
  signup (accounts provisioned via CLI).
- **Roles:** the JWT/`/auth/me` carry `role` (`admin` | `member`), exposed as
  `isAdmin` from `useAuth()`. The Sidebar hides `adminOnly` nav items from
  members and `RequireAdmin` guards admin-only routes (e.g. `/settings`) — the
  backend's `require_admin` is the real enforcement.
- **Session expiry (401):** the axios response interceptor, on a 401 *with* a
  stored token, clears it and fires `AUTH_EXPIRED_EVENT` on `window`.
  `AuthContext` listens, ends the session, and `RequireAuth` redirects to
  `/login`. (Event bus because interceptors live outside React.) A 401 from the
  login attempt itself is excluded — `LoginPage` shows it inline.
- **Charts:** Apache **ECharts**, wrapped in `components/charts/EChart.jsx` (thin
  wrapper over core `echarts` — no `echarts-for-react`, which lags React 19).
  Themed from the index.css tokens via `charts/theme.js`. Chosen for native
  heatmap/scatter support the catalog needs. (When charts ship, switch to modular
  `echarts/core` imports to trim bundle.)

## Adding a page

1. Add an entry to `config/nav.js` (label, path, icon).
2. Create `features/<name>/` with `<Name>Page.jsx` (+ `api.js`/`hooks.js` when it
   fetches).
3. Register the route in `app/router.jsx` under the `AppLayout` children.
