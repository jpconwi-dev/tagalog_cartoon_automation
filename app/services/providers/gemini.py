import httpx
from app.services.providers.base import LLMProvider
from app.services.providers.errors import InvalidResponse, ProviderError, QuotaExhausted


class GeminiProvider(LLMProvider):
    name = "gemini"

    def classify(self, r: httpx.Response) -> ProviderError:
        # Heuristic: per-day quota violations mention "PerDay" in the quota id.
        if r.status_code == 429 and "perday" in r.text.lower().replace("_", "").replace(" ", ""):
            return QuotaExhausted("gemini daily free quota exhausted (HTTP 429)")
        return super().classify(r)

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        s = self.settings
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_model}:generateContent"
        # Key goes in a header, never in the URL, so it cannot leak into logs.
        headers = {"x-goog-api-key": s.gemini_api_key, "Content-Type": "application/json"}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
        }
        data = await self._post(url, headers, body)
        if data.get("promptFeedback", {}).get("blockReason"):
            raise InvalidResponse("gemini blocked the prompt")
        cands = data.get("candidates") or []
        if not cands:
            raise InvalidResponse("gemini returned no candidates")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            raise InvalidResponse(f"gemini returned no text (finishReason={cands[0].get('finishReason')})")
        return text
