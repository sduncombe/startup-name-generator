# Startup Name Generator

Open-source utility that generates pronounceable product and company names, scores them, runs a heuristic radio (spell-after-hearing) test, checks domains via RDAP, and optionally uses **your own** AI provider key (BYOK).

> **Not part of duncombe-web.** This repository is standalone. [seanduncombe.com](https://seanduncombe.com) only links to the deployed app.

## Product experience

Designed around effortlessness (Apple HIG *principles*, not Apple’s look): one primary action, progressive disclosure, sensible defaults, and content-first results.

Ask what you’re building → **Generate**. Optional brand details and Advanced stay collapsed. The app infers keywords/tone, then runs scoring, radio test, domains, and conflicts with live progress (“Generating names…”, “Checking domains…”, …).

Results dominate the page: naming directions first, then a tight comparison table. Filter with search or **Usable only**.

## Features (always free / local)

- Pronounceable local name generation (descriptive, compound, invented, modified stems)
- Deterministic scoring (weights in `config/scoring.yaml`)
- Heuristic radio test (pronunciation, alternate spellings, pass/fail)
- Deterministic conflict heuristics + RDAP domain checks
- Favorites, filtering, sorting, saved sessions, CSV export

## Optional AI (Bring Your Own Key)

AI is used only for **creative naming directions and brainstorm names**. Scoring, domains, conflicts, radio, and pronunciation stay code-only.

Supported providers: OpenAI, Anthropic, xAI, Gemini.

Security model:

- Keys live in **browser `sessionStorage`** only for the tab session
- Sent to this app’s server in **`X-LLM-*` headers** for that request only (never in the URL)
- **Never** written to SQLite, logs, analytics, or source
- **Clear key** removes the session entry
- Public deployment has **no** host API keys and `ALLOW_SERVER_LLM_KEYS=false`

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Leave paid keys empty for public-mode local testing
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

```bash
pip install pytest httpx
pytest -q
```

## Deploy

See [DEPLOY.md](./DEPLOY.md) for DigitalOcean / Docker and the `names.seanduncombe.com` custom domain plan.

## Layout

```
app/           FastAPI + services
config/        YAML vocab, scoring, syllables, blocklist
static/        HTML/CSS/JS UI
tests/         Pytest (BYOK + local generation)
deploy/        Hosting reference specs
Dockerfile
LICENSE        MIT
```

## License

MIT — see [LICENSE](./LICENSE).
