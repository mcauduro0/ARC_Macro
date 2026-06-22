# Phase F5 — mobile/responsive Shell + component tests + e2e scaffolding

The fifth and final frontend increment: the Mesa shell goes responsive, the primitives the five screens depend
on get a real test net, and Playwright e2e is scaffolded ready-to-run. Every nav area is now a real screen.

## What was built

**Responsive Mesa (`mesa.css`, `Shell.tsx`):**
- Under a 760px breakpoint the desk collapses: the left rail becomes a horizontal, scrollable tab bar (active
  indicator flips from left-border to bottom-border), the top bar wraps instead of clipping, and wide
  ledger/risk tables scroll horizontally **inside their panel** (`display:block; overflow-x:auto`) rather than
  blowing out the viewport. Main padding tightens. The Shell now tags the layout (`mesa-shellbody` /
  `mesa-nav` / `mesa-navinner` / `mesa-topbar` / `mesa-main`) so the rules are pure CSS — no JS, no new state.

**Component tests (`client/src/arc/__tests__/components.test.tsx`, 13):**
- The Mesa primitives are rendered with **`react-dom/server` (`renderToStaticMarkup`)**, so the tests run in the
  existing **node** vitest environment with **zero new dependencies** — no jsdom, no RTL. They lock the
  contract the screens rely on: `Pos` sign-colouring + em-dash-for-null + digit/sign options, `Pct` ×100 + %,
  `actionTag` OPERATE/HALT/warmup mapping, `Tag`/`Dot` kind classes, `ReadinessTag` state, and `AccrualBar`
  value/total + zero state + 100% clamp.
- `vitest.config.ts` now uses `@vitejs/plugin-react` (already a devDep) to transform the `.tsx` tests and
  includes `client/**/*.test.tsx` + `shared/**/*.test.ts`. Server `.ts` tests are untouched.

**Playwright e2e scaffolding (`playwright.config.ts`, `e2e/smoke.spec.ts`, `test:e2e` script):**
- A resilient smoke spec (shell chrome + the 7-area nav + the prime-directive honesty banner *or* the
  bridge-offline panel + routing to Holdout/Macro) — tolerant of the bridge being offline.
- **Why scaffolded, not wired into CI:** the repo pins `pnpm@10.4.1` and the local store rejects ad-hoc adds
  (`ERR_PNPM_VIRTUAL_STORE_DIR_MAX_LENGTH_DIFF`), so adding `@playwright/test` (or RTL/jsdom) would risk a
  lockfile the frozen-lockfile CI install rejects for the whole repo. So `e2e/` + `playwright.config.ts` are
  **excluded from tsconfig and from the vitest run** (they never touch `pnpm check` or the CI gate), and enable
  with one command: `pnpm add -D @playwright/test && pnpm exec playwright install chromium && pnpm test:e2e`.

## A note on RTL vs SSR (honest substitution)
The plan said "RTL/jsdom". In this environment adding those deps is unsafe (pinned-pnpm/virtual-store), so the
component tests use `react-dom/server` SSR rendering instead — equivalent assertion value for these stateless
presentational primitives, and **CI-safe with no dependency changes**. If/when the toolchain is unpinned, RTL +
jsdom can be added and these tests ported with minimal change.

## Verified
- `pnpm check` (tsc) — green (e2e/playwright/`*.test.tsx` excluded by convention).
- `pnpm test` (vitest) — **402 passed** (22 files; +13 new component tests). No dependency added (only a
  `test:e2e` script), so the lockfile is unchanged and the CI frozen-lockfile install stays valid.

## Status — the platform is feature-complete across the nav
Command · Co-pilot · Holdout · Risk · Macro · Research · Ledger are all real Mesa screens on the autonomy
bridge, honest by construction (no pre-verdict Sharpe/DSR; macro fields real-or-null), now responsive and
test-covered. See [[arc-macro-frontend-plan]].
