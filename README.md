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

## Phase 3: scripts, topics, dedup, resumable runner
- `app/templates/topics.json` is the topic bank (title, subject, category, key_points). Categories rotate
  least-recently-used first; a topic is skipped if it is >= `TOPIC_SIMILARITY_THRESHOLD` similar to anything used.
  When the bank runs out the job fails with a clear message: add more topics.
- Every script is checked (length, Tagalog ratio, duplicate title, duration). Hard failures make the router retry or
  fall back to the next provider. Soft issues (numbers not in your key points, no references) are saved as `warnings`.
  The checks cannot prove facts are true: review AI-written scripts, and prefer topics that carry key_points.
- Run the script stage: `python -m app.workers.daily_runner` (exit 0 done, 1 failed, 3 deferred/retry later).
  It stops at status `generating_audio` until Phase 4 exists. Re-running never regenerates a saved script.
- Keep `data/app.db` out of OneDrive/Dropbox-synced folders: sync clients can lock or corrupt SQLite files.
- New table `script` is created automatically on startup. Existing tables are unchanged.
