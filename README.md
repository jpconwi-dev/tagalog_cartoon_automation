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
