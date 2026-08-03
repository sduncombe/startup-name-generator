# Namegen (Python reference)

Open-source brand name generator for companies, apps, podcasts, nonprofits, communities, and personal brands. It generates pronounceable names, scores them, runs a heuristic radio (spell-after-hearing) test, checks domains via RDAP, screens trademarks, and optionally uses **your own** AI provider key (BYOK).

## Live product

The production app now runs **on seanduncombe.com**:

**[https://seanduncombe.com/apps/namegen](https://seanduncombe.com/apps/namegen)**

That version is a Nitro/TypeScript port inside [`duncombe-web`](https://github.com/sduncombe/duncombe-web). This repository remains the MIT-licensed Python/FastAPI reference and a self-hostable standalone deploy.

## Product experience

Ask **What are you naming?** and **What problem are you solving?** → **Generate**. Optional brand preferences (naming philosophy, primary language, audience, liked brands, avoid) and Advanced stay collapsed. Naming philosophies: **Invented**, **Real Words**, **Compound**, **Descriptive**.

Results dominate the page: naming directions first, then a tight comparison table. Filter with search or **Usable only**.

## Features (always free / local)

- Pronounceable local name generation (descriptive, compound, invented, evocative, suggestive, real words)
- Deterministic scoring (weights in `config/scoring.yaml`)
- Heuristic radio test (pronunciation, alternate spellings, pass/fail)
- Deterministic conflict heuristics + RDAP domain checks
- Built-in trademark screening with a simple Low / Medium / High risk indicator
- Favorites, filtering, sorting, saved sessions, CSV export

## Trademark screening

Every generated name is automatically screened for trademark risk as the final pipeline step. The screening is fully deterministic, no AI involved:

- **Exact match** against registered wordmarks (highest severity)
- **Similar spelling** via Levenshtein distance and Jaro-Winkler similarity
- **Phonetic similarity** via Soundex and a phonetic-key algorithm
- **Nice class weighting**: a similar mark in your industry matters far more than one in an unrelated class

Default deploy ships a **sample** trademark dataset for demo only. Import USPTO bulk data for real screening (see below / `tools/import_uspto.py`).

## BYOK AI (optional)

Public mode never uses host LLM keys. Paste your own Anthropic / OpenAI / xAI / Gemini key in Advanced; it stays in `sessionStorage` and is sent only as ephemeral `X-LLM-*` headers.

## Quick start (standalone Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000

## Tests

```bash
pip install pytest httpx
pytest -q
```

## Deploy (standalone)

See [DEPLOY.md](./DEPLOY.md) for Docker / DigitalOcean self-hosting. The old `names.seanduncombe.com` plan is retired in favor of the on-site app.

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

MIT. See [LICENSE](./LICENSE).
