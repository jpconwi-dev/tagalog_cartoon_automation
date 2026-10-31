# Tagalog Cartoon Automation (Phase 1: core app)

## Run locally
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env      # set API_KEY to a long random string
    uvicorn app.main:app --reload
    # open http://localhost:8000/docs  (Authorize with X-API-Key)
    pytest -q

## Phase 1 endpoints
GET /health (public) · GET /api/status · GET /api/providers · POST /api/videos/generate · GET /api/jobs/{id} · POST /api/jobs/{id}/retry

## Safety defaults
FREE_ONLY=true, ALLOW_PAID_FALLBACK=false (app refuses to start if both are true), providers are only
"eligible" when credentials are set AND you flip `<PROVIDER>_FREE_VERIFIED=true` after checking its current terms.

## Phase 2: AI providers (checked 2026-11-01; re-verify before relying on any of this)
| Provider | Free terms found | Router behaviour |
|---|---|---|
| Cloudflare Workers AI | 10,000 neurons/day shared across models, resets 00:00 UTC; past it, calls fail. Some models are paid-only. | quota error -> cooldown, next provider |
| Gemini API | Free tier, no card; limits shown in AI Studio, not fixed in docs. Free-tier content may be used to improve Google products. | 429 -> backoff; "per day" quota -> cooldown |
| Hugging Face | Free accounts get $0.10 credits/month; after that HTTP 402. | 402 -> quota cooldown |
| xAI Grok | No confirmed standing free API (sources conflict; appears prepaid). | Off unless GROK_FREE_VERIFIED=true |

A provider is used only if credentials AND a model are set AND `<NAME>_FREE_VERIFIED=true`. Models are never
defaulted because they get deprecated; pick one from the provider's current catalog that works on the free tier.
`MAX_RETRIES_PER_PROVIDER=2` means 1 attempt + 2 retries. The template provider is always last.
