# Ads UI — Handoff

**Date:** 09-Sep-2026 · **Branch:** `feature/campaign-ui-dhriti` (off `origin/dev`)
**Scope:** the two Ads pages and the nav that reaches them. UI and user flow only.
**Companion:** [campaign-manager.md](campaign-manager.md) is the engine reference. Read its
budget and bid sections before changing anything the wizard writes.

---

## TL;DR

1. **Two new pages, both under a new `AdsBeta` nav group:** *Insights*
   (`/ads/insights`) and *Ad Automation* (`/ads/automation`).
2. **No engine change, no schema change, no migration.** Every call these pages make
   already existed and is already used by the current Campaign Manager.
3. **The existing `/ads` page and Campaign Manager v2 is untouched** and stay
   reachable exactly as before.
4. **The theme file was deliberately NOT changed.** which is the one decision a
   reviewer most needs to understand.
5. **Nothing is committed.** The working tree carries the whole change.

---

## 1. What shipped, and where

| Page | Route | Feature folder |
|---|---|---|
| Insights | `/ads/insights` | `frontend/src/features/ads-insights/` |
| Ad Automation | `/ads/automation` (and `/automations`) | `frontend/src/features/automations/` |

**Insights** is a new view over the same ads data the `/ads` page reads: a KPI strip with
period-over-period comparison, a spend/revenue trend, a budget-split donut, and four
sortable tables (campaigns, keywords, categories, share of voice). Campaign rows carry a
seven-day budget-utilisation strip, colour-coded, opening a per-day breakdown on click.
Every table exports to CSV.

**Ad Automation** is a new UI over the Campaign Manager v2 engine: a three-step wizard for
creating and editing a campaign or keyword automation, a list of everything scheduled with
its actions summarised in plain English, and an Execution Logs modal with type and status
filters. Safety checks run as the schedule is built and are stated on the summary before
anything is saved.

**Navigation.** `config/nav.js` gained an `AdsBeta` group with two children. Sidebar
entries can now declare `children`; an entry without them renders exactly as before. The
plain `Ads` entry is unchanged and still points at `/ads`.

---

## 2. ⚠️ The theme file is deliberately unchanged

**`frontend/src/index.css` was not modified.** `--color-primary` is still indigo `#4f46e5`
and is still the app's UI action colour, exactly as its comment in that file says.

The Ads pages are styled with the **`brand` token group that already existed** in that file
(`--color-brand: #f42a34` and its hover, deep, soft and on-brand steps). Nothing was added
to the theme and nothing was redefined.

**Why it was left alone.** Switching `--color-primary` to brand red would repaint every
page in the product in one commit: Overview, Analytics, Products, Inventory, Competition,
Scorecard, Reports, Settings, plus both Campaign Manager pages. The brand rollout is being
done **one surface at a time**, and Ads is the first. Keeping the theme file untouched means
this branch changes only the pages it claims to change, and every other page renders today
exactly as it did before.

**What that means for whoever picks this up.** The brand palette is currently *applied*
per-surface rather than *defined* centrally for the whole product. When the rollout reaches
the remaining pages, the right move is to consolidate: promote the brand palette to the
central theme, retire the parallel `primary` group, and delete the per-surface application.
Until then, expect Ads to look brand-red and the rest of the product to look indigo, and
know that this is intentional rather than drift.

**The chart palettes are the same story, and they are the larger half of that job.** There
are three, all maintained by hand because ECharts cannot read CSS variables:

| Where | Leads with | Validated for colour-vision separation? |
|---|---|---|
| `components/charts/theme.js` | `#4f46e5` indigo | no |
| `components/charts/options.js` | `#4f46e5` indigo | no |
| `features/ads-insights/chartOptions.js` | `#f42a34` brand | **yes** |

The Insights palette is the only one that has been run through a validator (worst adjacent
pair ΔE 15.0 deutan, 21.4 normal, all at or above 3:1 contrast; the numbers are recorded in
the file). The two older palettes also put success green, warning amber and danger red in
**series** slots, which collides with their reserved status meaning. So the eventual
migration is not a colour swap: the Insights palette should become the app palette, move
into `theme.js` and `options.js`, and the status hues should come out of the series slots.
`features/ads-insights/chartOptions.js` is the file that then merges into
`components/charts/options.js`.

---

## 3. File inventory

### New, untracked

| Path | Size |
|---|---|
| `frontend/src/features/ads-insights/` | 16 files, 3,931 lines |
| `frontend/src/features/automations/` | 31 files, 6,920 lines |
| `frontend/src/components/ui/HoverHint.jsx` | 95 lines — the shared hover panel |
| `frontend/src/components/ui/InfoTooltip.jsx` | 25 lines — the ⓘ built on it |
| `frontend/src/components/ui/Select.jsx` | 177 lines — styled dropdown replacing native `<select>` |
| `frontend/src/lib/exportTable.js` | 69 lines — client-side CSV export |

Both features follow the layout documented in
[frontend-architecture.md](frontend-architecture.md): `api.js` for HTTP, `hooks.js` for
React Query, `components/` for rendering, and pure logic in a module at the feature root
(`automations/automation.js`, `ads-insights/buBands.js`, `ads-insights/chartOptions.js`).

### Modified, tracked — all additive

| File | Change |
|---|---|
| `config/nav.js` | the `AdsBeta` group; no existing entry altered |
| `app/router.jsx` | +2 imports, +3 routes |
| `layout/Sidebar.jsx` | a `NavGroup` branch that runs only for items declaring `children` |
| `components/ui/Button.jsx` | the `brand` variant inverts to a solid fill on hover |
| `components/ui/DataTable.jsx` | generic client-side column sorting, off by default |
| `components/ui/ViewToggle.jsx` | a `size` prop; `lg` for a page's one primary control |
| `components/charts/EChart.jsx` | registered `GraphicComponent`; the ResizeObserver now ignores no-op resizes, which is what lets build-in animations run |
| `docs/frontend-architecture.md` | wrote down where pure logic lives |

`components/ui/DataTable.jsx`, `ViewToggle.jsx` and `EChart.jsx` are shared, so those three
changes reach other pages. All are additive and defaulted off; the EChart change fixes
animations everywhere rather than altering any chart's configuration.

---

## 4. What was deliberately not touched

- **The engine.** `backend/campaign_manager/` has no change of any kind. No new endpoint,
  no payload change, no table, no migration.
- **`/ads`.** The existing Ads page is byte-identical.
- **Campaign Manager v1 and v2.** Both stay in the codebase and v2 stays in the rail as
  "Campaign Manager". It is the page in production use, and it stays until the new page has
  created, edited and stopped a real automation against the live backend.
- **`index.css`.** See §2.

---

## 5. Engine contract — do not guess these

Read from `backend/app/schemas/campaign_manager.py`. Three traps, all of which have bitten
before:

1. **Bid rules say `stop_*` where budget rules say `end_*`** (`stop_time`/`stop_date` vs
   `end_time`/`end_date`). Get it wrong and the field is silently dropped.
2. **`state` vs `status`.** `state` is stored lifecycle (active/paused/stopped); `status` is
   computed per window (running/scheduled/ended). The list shows `status`; the toggle
   writes `state`.
3. **Every timing key must be sent, with an explicit `null` for empty.** The API uses
   `exclude_unset`, so an omitted key means "unchanged" and a cleared field keeps its old
   value. A `stop_date` that could not be cleared once took an automation dark silently.

Submit paths, both in `AutomationWizard.jsx`: a campaign automation creates the budget
schedule first and then adds each additional window to it, because the schedule must exist
before a rule can hang off it. A keyword automation is a single `createBidRule`.

Two behaviours worth knowing, both from the engine and both surfaced in the UI: an empty
`days` list means **every day**, and a window only pauses the campaign at its end when
`stop_after_window` is set.

---

## 6. Known gaps and follow-ups

**Verification status.** Both pages render against a live backend with no console errors,
and the wizard has been walked end to end. **No automation has been created or saved
through the new wizard against the live backend** — every walk stopped before Create and
Save, on instruction, so that no live automation was created or modified during
development. That is the first thing to do on pickup.

| # | Item | Notes |
|---|---|---|
| 1 | Three dead files in `automations/components/` | `RankAgentBanner.jsx`, `AdvertiserField.jsx`, `KeywordCombobox.jsx`, 266 lines, imported by nothing. Leftovers from wizard iterations. |
| 2 | Two tooltip primitives | `automations/components/Tooltip.jsx` and `components/ui/HoverHint.jsx` solve the same problem the same way. One should absorb the other. |
| 3 | `ads-insights` imports from other features | `export * from "../ads/api"` and `"../ads/hooks"`, four components from `../ads/components/`, one from `../../analytics/hooks`. This breaks the rule written in `frontend-architecture.md`. The fix is promotion: the shared components move to `components/ui/`, and `ads-insights` declares its own API wrappers the way `automations/api.js` does. |
| 4 | v2 and the new page no longer share a query cache | Key namespaces are separate (`cm2-*` vs `auto-*`), `staleTime` is 5 minutes and `refetchOnWindowFocus` is off, so a rule created on one page can be invisible on the other for up to five minutes while both exist. |
| 5 | Write mode is inferred | The page infers whether writes are armed from the last run's `dry_run`, and labels it as inferred, because no endpoint exposes `live_armed`. One field on an existing endpoint would fix it properly. |
| 6 | `AutomationWizard.jsx` is 774 lines | Against a repo ceiling of about 420. Splittable. |
| 7 | Guard rails not built | A weekly spend ceiling and a max change per day were scoped and deferred. |

**Pre-existing, not from this work:** `frontend/vite.config.js:8` sets
`cacheDir: "C:/vite-cache"`, a hardcoded Windows path committed in `1f360ce`. On macOS and
Linux this creates a literal `frontend/C:/` directory, currently 16 MB, which is **not
gitignored**, so `git add .` would commit it. Deleting the line restores Vite's default of
`node_modules/.vite`, which is already ignored.

---

## 7. Running it

```bash
cd frontend && npm install && npm run dev     # :5173
cd backend  && uvicorn app.main:app --reload  # :8000
```

Log in, then open **AdsBeta → Insights** and **AdsBeta → Ad Automation**.

State at handoff: `npx vite build` green, `npx oxlint src` zero errors, and every file this
branch touches passes `npx prettier --check`. Note that roughly 68 files elsewhere in
`src/` do not pass Prettier and never have; that drift predates this work and was left
alone so the diff stays about the feature.
