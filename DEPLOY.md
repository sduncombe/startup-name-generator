# Deployment (standalone Python)

> **Production:** Namegen ships on [seanduncombe.com/apps/namegen](https://seanduncombe.com/apps/namegen) as part of `duncombe-web` (Nitro/TS). Use this guide only if you want to self-host the Python reference app.

This app is independent of `duncombe-web`. Deploy it from
`github.com/sduncombe/startup-name-generator` only when you want a separate instance.

## Public security rules

| Rule | Public value |
|---|---|
| `ALLOW_SERVER_LLM_KEYS` | `false` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY` / `GEMINI_API_KEY` | **unset** |
| `DOMAIN_API_KEY` / `DOMAIN_API_SECRET` | **unset** (use RDAP) |
| AI | BYOK only (browser sessionStorage → ephemeral header) |

## DigitalOcean App Platform

1. Create a new App from the `startup-name-generator` GitHub repo.
2. Use the `Dockerfile` (port `8000`).
3. Set env vars from `.env.example` public section. Confirm paid keys are empty.
4. Attach a persistent volume at `/data` so SQLite (`DATABASE_PATH=/data/runs.db`) survives deploys.
5. Set `PUBLIC_APP_URL` to your app’s HTTPS URL (the default DO hostname is fine).
6. Optional custom domain is yours to configure; Sean’s live product no longer depends on `names.seanduncombe.com`.

Reference spec: `deploy/digitalocean-app.yaml`.

## Docker (any host)

```bash
docker build -t startup-name-generator .
docker run --rm -p 8000:8000 \
  -e ALLOW_SERVER_LLM_KEYS=false \
  -e PUBLIC_APP_URL=https://your-host.example \
  -v sn-data:/data \
  startup-name-generator
```

## Private self-host (optional)

If you run a private instance and want server-side keys:

```env
ALLOW_SERVER_LLM_KEYS=true
ANTHROPIC_API_KEY=...
```

Never enable this on a public BYOK deployment.

## Website integration

`duncombe-web` hosts the production UI/API at `/apps/namegen` and lists the tool under **Apps** with:

- Launch → `https://seanduncombe.com/apps/namegen`
- View Source → `https://github.com/sduncombe/startup-name-generator`
