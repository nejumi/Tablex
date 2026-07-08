# 0122 Native marimo Profile

Date: 2026-07-09

Scope: backend native marimo session startup for two registered Home Credit notebooks. This is not a browser waterfall trace; frontend iframe and asset-loading timings still need B-grade evidence.

Environment:

- Python: `.venv/bin/python`
- marimo: `0.23.11`
- Data dir: `data/`

Artifacts measured:

- `art_19452d019824`: Home Credit data understanding notebook
- `art_e4f7e6ee90e8`: Home Credit model diagnostics notebook

Method:

- Stop any existing session for the artifact.
- Call `start_or_get_native_marimo_session`.
- Wait for HTTP readiness with `wait_for_native_marimo_session_ready(timeout_seconds=20)`.
- Call `start_or_get_native_marimo_session` again for the same artifact to measure reopen/reuse.
- Stop the session after the measurement.

Results:

| artifact | notebook | cold start call | cold ready wait | cold ready | reopen reused | reopen call | reopen ready wait | reopen ready |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| `art_19452d019824` | data understanding | 873 ms | 1023 ms | yes | yes | 901 ms | 15 ms | yes |
| `art_e4f7e6ee90e8` | model diagnostics | 867 ms | 1017 ms | yes | yes | 909 ms | 12 ms | yes |

Interpretation:

- Backend native marimo readiness for these two notebooks is below the J8 target: cold open is about 1.9 seconds and warm readiness is effectively immediate.
- The measured backend path does not explain reports of extremely slow UI opening by itself.
- The next likely bottlenecks are browser-side iframe/module loading, stale proxy recovery, and notebooks that do heavy top-level data loading or crash/restart repeatedly.
- The reopen call itself took about 900 ms even though readiness was immediate. This should be rechecked under a browser trace before optimizing; it may be request overhead or one-time marimo page work rather than Python session startup.

Next evidence required:

- B: Playwright/browser timing for opening a prewarmed notebook link from Chat, Leaderboard, and Notebooks.
- B: Browser network/error capture for the previously observed `run-page-*.js` failure class.
- U/B: authoring-contract checks that discourage top-level full-data loads in Codex-authored notebooks.

## Browser timing update: Leaderboard prewarm path

Date: 2026-07-09

Change measured:

- Leaderboard result-notebook links now trigger background native marimo prewarm with `wait_ready=false` when the links become visible.
- Existing Notebooks-tab prewarm also uses `wait_ready=false`, so background prewarm acknowledges quickly and does not hold the UI path open while marimo becomes ready.

Browser evidence:

- After reloading Home Credit Test5 on the Leaderboard tab, Playwright network records showed background prewarm calls:
  - `POST /api/analysis-notebooks/art_19452d019824/marimo-session?wait_ready=false => 200`
  - `POST /api/analysis-notebooks/art_e4f7e6ee90e8/marimo-session?wait_ready=false => 200`
- Opening the `Model comparison` result notebook from Leaderboard after prewarm:
  - Measured click-to-native-iframe time: **1,431 ms**
  - Native iframe: `/api/marimo-sessions/mos_df10a23e802c/proxy/`
  - Browser console errors: **0**
  - Screenshot: `docs/evidence/playwright/0122_j8_leaderboard_prewarmed_open.png`

Interpretation:

- The primary Home Credit Leaderboard-to-notebook path is now below the J8 prewarmed target of 3 seconds.
- The previously observed false proxy-readiness 503 class was not reproduced in this path after the proxy readiness probe removal.
- Remaining measurement gaps are cold browser open from a fresh backend with no prewarm, Chat-link open timing, and authoring checks for notebooks that perform full-data top-level loads.
