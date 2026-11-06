# Moat (competitor research agent)

Agent that takes a company name (+ optional URL), researches its competitors, verifies them independently, asks a human to approve, then writes a sourced Markdown report. Core promise: **traceability, not intelligence**. The model will sometimes be wrong; the system catches it, shows its work, and stops rather than guesses.

Two front ends share the pipeline: **Moat**, the web app with accounts (`moat_app.py`, `views/`, `backend/`, `runner.py`, `index.py`), and the **demo** (`app.py`), a single Streamlit page with no accounts, still what Docker and Streamlit Cloud run.

**Design/UI work → read `DESIGN.md` first (§0 for small changes). Don't invent styles.**
**Brainstorming / product decisions / "why is it like this?" → read `DECISIONS.md`. Skip it for routine edits.**

## Stack
Python 3.11+ (`pyproject.toml`, used only by Vercel, says 3.12+) · Gemini (`google-genai`) · Tavily search, Firecrawl optional · Pydantic · Tenacity · Streamlit (one exact version, pinned the same in `requirements.txt`, `requirements-web.txt` and `pyproject.toml`; a test checks) · SQLAlchemy (SQLite local, Postgres prod) · Google sign-in via Streamlit's native OIDC (`st.login`). No agent framework.
Config: everything is read from the environment or `.env`. Only `GEMINI_API_KEY` and `TAVILY_API_KEY` are also bridged from `st.secrets` (`moat_app.py`). `DATABASE_URL` (unset = local `data/cra.db`; on Vercel, unset stops the boot); `FREE_RUNS` (1); `UNLIMITED_EMAILS` (allow list, runs on our keys with no cap; unset = nobody, and no address belongs in the code); `DAILY_RUNS_PER_USER` (3), `DAILY_RUNS_GLOBAL` (150); `OPERATOR_NAME`, `CONTACT_EMAIL`, `JURISDICTION` (legal pages); `CRA_DEV_AUTH=1` local-only sign-in bypass; `KEY_VAULT_SECRET` (parked with own keys, see Hard rules). Google sign-in: `[auth]` block in `.streamlit/secrets.toml` locally (template: `.streamlit/secrets.toml.example`), environment variables on Vercel. **Every Vercel variable is listed in one place: README, Deployment, Vercel.**

## Run
```
pip install -r requirements.txt -r requirements-web.txt   # everything, including the web layer
python main.py                                   # CLI
streamlit run moat_app.py --server.port 4000     # Moat (dev port 4000, which the redirect URI expects)
streamlit run app.py                             # the demo (needs only requirements.txt)
python -m unittest discover -s tests             # full suite: no keys, no network. Web tests skip if their packages are missing
python tests/test_backend.py                     # accounts + usage limits alone
python run_eval.py [CaseName]                    # regression evals (live API; spends quota)
```
UI-only work: set placeholder `GEMINI_API_KEY`/`TAVILY_API_KEY` and `CRA_DEV_AUTH=1` (renders everything from localhost; Research fails at the API). Landing, legal and account pages need no keys. `/app` does: it imports the pipeline, and `config.py` builds one Gemini and one Tavily client from those two variables at import, so without them `/app` raises `KeyError`.

## Pipeline (same steps from every front end)
identify → research (tool loop) → verify (separate call) → checks → human review → report
`pipeline.py` LLM steps · `tools.py` per-run search/extract tools + source ledger writes · `retrieval.py` providers (Tavily, Firecrawl, hybrid) + benchmark-only disk cache · `runstate.py` one run's own state · `evaluate.py` deterministic checks · `report.py` Markdown · `schemas.py` Pydantic outputs · `prompts.py` all prompt text · `config.py` clients (built once at import), model, retry · `memory.py` + `recall.py` opt-in run ledger (`MEMORY_PATH`) · `failures.py` demo error messages + secret bridge · `eval_cases.py` + `run_eval.py` regression cases · `main.py` CLI · `app.py` demo.
Web layer: `moat_app.py` Streamlit router · `index.py` Vercel ASGI entry · `runner.py` background research job · `views/` pages (`landing`, `tool` at `/app`, `account`, `privacy`, `terms`; `onboarding.py` = 2 questions; `auth.py` = sign-in + consent gate; `chrome.py` = left rail + footer; `session.py` = cached user) · `backend/` accounts, usage limits, jobs (no Streamlit) · `legal/*.md` Terms + Privacy text · parked: `backend/vault.py`, `keycheck.py`.
The web runner is not yet level with the CLI and demo: it does not use memory, and it has no "considered but not comparable" section, so a run where nothing verifies stops without a report.
Tests: `tests/web_setup.py` must be imported before `backend/` (throwaway database) · `test_backend.py`, `test_runner.py`, `test_moat_app.py` (real pages via AppTest), `test_vercel_entry.py` (index.py in separate processes) · `test_ui_bundle.py`, `test_dependencies.py` · `test_streamlit_flow.py` (the demo via AppTest) · the rest test the pipeline.

## Files: read vs. skip
| Task | Read |
|---|---|
| UI / look & feel | `moat_app.py`, `DESIGN.md`, `ui/components.css`, `design-system/spacing.css` |
| Prompt/behavior | `prompts.py`, `pipeline.py`, `eval_cases.py` |
| Verification/checks | `evaluate.py`, `schemas.py` |
| Report format | `report.py`, `example-report.md` (sample output only) |
| Login / accounts / limits | `views/auth.py`, `index.py`, `backend/*.py`, `tests/test_backend.py`, `tests/test_vercel_entry.py` |
| Landing page | `ui/landing.html`, `ui/landing.css`, `static/landing.js`, `views/landing.py`, `.impeccable.md` (design context), DESIGN.md section 15. Icons: edit `design-system/gen-icons.js` (generates `ui/icons.css`). Fonts: `static/fonts/`. Images: `static/img/` (no photos in use; CREDITS.md before adding one) |
| Legal copy | `legal/*.md` |
| **Skip** | `venv/`, `design-system/node_modules/`, `design-system/tokens/*.json` (use `tokens.css`, or grep one name), `assets/` (demo.gif is 6 MB), `static/vendor/` (vendored GSAP), `benchmarks/cache/`, `.git/` |

`design-system/` = Ant Design v6 tokens (generated by `extract.js`/`gen-css.js`/`gen-docs.js`) + our `spacing.css` + `gen-icons.js`. **Applied to the UI** by `node design-system/build-ui.js`, which generates `.streamlit/config.toml` and `ui/app.css`. **Never edit those two**; edit `build-ui.js`, `spacing.css` or the `ui/*.css` sheets it bundles, then rebuild (a test fails if the bundle is stale). **Light mode only for now.** Look = sharp system, DESIGN.md section 16 (`ui/neon.css`, bundled after the component sheets, then only `ui/motion.css`): zero radius, hairlines, Inter + JetBrains Mono.

## Hard rules
- **Only `moat_app.py`, `views/` and the separate demo `app.py` use Streamlit's page API;** `index.py` imports only `streamlit.starlette`. Pipeline, evaluate, report, tools, `runner.py` and `backend/` stay UI-agnostic so every front end shares them.
- UI changes never edit `pipeline.py`, `evaluate.py`, `prompts.py`, `tools.py`, `schemas.py`.
- No app-wide top bar: sign-in/consent/onboarding show only their column, signed-in pages use the left rail (`chrome.sidebar`). The public pages have their own header: landing's nav, and a brand bar on legal. Never read the user from the database on every rerun; use `views/session.py` (`refresh()` after a change).
- Protected pages call `auth.require_user()` first. Before the pipeline, a run on a free run calls `usage.try_consume()` and `users.consume_free_run()`; allow-listed accounts skip both. The daily count is never refunded. The free run is refunded at most once per job, only after a service problem (`runner._fail`, `jobs.fail_once`), never when a company can't be identified or researched.
- `CRA_DEV_AUTH=1` works only when host, origin and client are all local and no proxy header is present (`config.dev_auth_allowed`, checked on every use, failing closed). Still never set it in production.
- Landing rules: no `<` character in any CSS (the sanitizer drops the whole style block), no inline SVG (CSS masks instead), no CDN scripts (vendored under `static/vendor/`), page must be complete without JS, competitors named in plain text with no company logos. Every claim must match the code, including the free-run limit. Details in DESIGN.md section 13 and M4.
- Store only: users, onboarding answers, daily usage, free runs used, and `research_jobs` (a user's 10 most recent researches: working state and report text, each deleted on request and on account deletion; after 24 h it is never served, and it is erased on read or at the next cleanup, which runs when anyone starts a job or loads a signed-in page; there is no scheduler). No API keys: the first connection of this version erases any saved earlier. Reports are not kept beyond that; if that changes, update `legal/privacy.md` in the same change. A retired column that held personal data goes in `backend/db.py` `RETIRED_COLUMNS`, which erases it on the next connection.
- Own API keys are hidden. `backend/vault.py` and `keycheck.py` stay, but no page or job may reach them (a test checks). No text may say a user's own keys are used.
- Report download in Moat = `static/download.js` (browser Blob). Never `st.download_button` there (breaks across Vercel instances); the demo uses it, on one server. Motion rules: DESIGN.md section 17.
- Moat's research never runs inside a Streamlit page: Vercel WebSockets last under a minute and a run takes 30-90 s. `views/tool.py` starts a job (`runner.py`, background thread) and reads `backend/jobs.py`. The demo does run in the page. Every run uses the clients in `config.py`; per-run keys do not exist yet.
- Free run: `FREE_RUNS` (1) per user for life, on our keys. After that research isn't available to them, and the page says so plainly.
- The disk response cache is off unless a benchmark turns it on: real runs always read the live web, and a read-only disk must not break them.
- Legal text change ⇒ bump `LEGAL_VERSION` in `backend/config.py` (forces re-consent). The Privacy Policy must match what we actually collect and send.
- Prompt or pipeline change ⇒ run `run_eval.py`; gates must pass. Gates = stable assertions; observations = may vary (live web), never gate on them.
- Identity unclear ⇒ stop and explain; never guess. Verifier gets the target's *scale* but not the researcher's *reasoning*.
- Sources tracked in code (tools record fetched URLs); model-cited URLs not in that record are fabricated and stripped.
- Verdicts pair to competitors by index, never by name.
- Retry only 429/5xx/transport errors, and not a daily quota that can't clear; never 404.
- Never commit keys. `.env` is gitignored; `.dockerignore` must keep it out of images.

## Conventions
Python, type hints, Pydantic for every structured LLM output. Comments explain *why* (each safeguard maps to an observed failure). Prompts live only in `prompts.py`. UI: mobile-first, WCAG AA, 8px grid, no inline styles, no dark patterns (these override any generic React/Tailwind defaults: this repo is Python/Streamlit).

## Deploy
Moat, production: Vercel (`index.py` ASGI entry, redirects sign-in and sign-out to `/app`, `pyproject.toml`, `vercel.json`, `.vercelignore`), https://moatcra.vercel.app, deploy with `vercel deploy --prod --yes`. Env vars and the redirect URI: README, Deployment, Vercel. Production needs `DATABASE_URL` (boot stops without it) and `STREAMLIT_SERVER_COOKIE_SECRET` equal to `AUTH_COOKIE_SECRET`. The disk is read-only.
The demo, not Moat: Docker on Render (`Dockerfile` installs only `requirements.txt` and runs `app.py`; binds `0.0.0.0`, honors `$PORT`) and Streamlit Community Cloud (main file `app.py`; `failures.bridge_secrets` copies `st.secrets` to the environment before the pipeline is imported). `.streamlit/config.toml` applies to the demo too.
