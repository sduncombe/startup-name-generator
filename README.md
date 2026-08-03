# Namegen

Open-source brand name generator for companies, apps, podcasts, nonprofits, communities, and personal brands. It generates pronounceable names, scores them, runs a heuristic radio (spell-after-hearing) test, checks domains via RDAP, screens trademarks, and optionally uses **your own** AI provider key (BYOK).

> **Not part of duncombe-web.** This repository is standalone. [seanduncombe.com](https://seanduncombe.com) only links to the deployed app.

## Product experience

Designed around effortlessness (Apple HIG *principles*, not Apple’s look): one primary action, progressive disclosure, sensible defaults, and content-first results.

Ask **What problem are you solving?** → **Generate**. Optional brand preferences (naming style, primary language, audience, liked brands, avoid) and Advanced stay collapsed. Every preference changes generation or scoring: language shapes phonotactics, audience and liked brands shift tone and style traits, and avoid actively penalizes matching names. The app then runs scoring, radio test, domains, conflicts, and trademark screening with live progress.

Naming style defaults to **Brandable**: inventeds, abstracts, evocatives, and light compounds (Stripe / Notion / Slack energy), not SEO-style product phrases. Switch to Balanced or Descriptive under Brand preferences when you want more literal names.

Results dominate the page: naming directions first, then a tight comparison table. Filter with search or **Usable only**.

## Features (always free / local)

- Pronounceable local name generation (descriptive, compound, invented, modified stems)
- Deterministic scoring (weights in `config/scoring.yaml`)
- Heuristic radio test (pronunciation, alternate spellings, pass/fail)
- Deterministic conflict heuristics + RDAP domain checks
- Built-in trademark screening with a simple Low / Medium / High risk indicator
- Favorites, filtering, sorting, saved sessions, CSV export

## Trademark screening

Every generated name is automatically screened for trademark risk as the final pipeline step. The screening is fully deterministic, no AI involved:

- **Exact match** against registered wordmarks (highest severity)
- **Similar spelling** via Levenshtein distance and Jaro-Winkler similarity (Livora vs. Livorah)
- **Phonetic similarity** via Soundex and a phonetic-key algorithm (Homio vs. Homeo)
- **Nice class weighting**: a similar mark in your industry matters far more than one in an unrelated class. Likely classes are inferred from your brief.

Each name gets a risk indicator with a plain-language explanation:

- **Low**: no similar live marks found
- **Medium**: a similar live trademark exists in the same industry
- **High**: an exact live trademark exists; consider another name

### Data source: sample data by default, USPTO bulk data for production

The engine is data-source agnostic. Out of the box it loads `config/trademarks.sample.yaml`, a tiny sample dataset (a few dozen famous marks) that exists only so contributors can clone the repository and immediately run the app. **It is not a trademark database** and the UI says so whenever the sample dataset is active.

For production-quality screening, import the official USPTO bulk trademark data (the USPTO’s Trademark Search system has no public REST API, and its keyed TSDR API only supports lookup by serial number, so real-time register queries aren’t possible without scraping, which this project avoids):

1. Download “Trademark applications” XML files (e.g. `apc*.zip`) from the [USPTO bulk data portal](https://data.uspto.gov/). No account needed.
2. Convert them into the screening dataset format:

```bash
python tools/import_uspto.py apc*.zip -o data/uspto-trademarks.json
```

3. Point the app at the imported dataset:

```bash
TRADEMARK_DATA_PATH=data/uspto-trademarks.json uvicorn app.main:app
```

The importer is deterministic and offline: it streams the XML, keeps wordmarks with their status (Live / Pending / Dead, mapped from official USPTO status codes) and Nice classes, dedupes, and writes JSON or YAML. `--classes 9,42` restricts to specific Nice classes; `--include-dead` keeps dead marks. Any file in the same format works; the engine does not care where the data comes from.

Trademark screening is provided as an informational tool only and is not legal advice. Always consult a qualified trademark attorney before adopting a brand.

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

MIT. See [LICENSE](./LICENSE).
