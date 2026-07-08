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

