import json
import httpx
from app.services.providers.base import LLMProvider
from app.services.providers.errors import InvalidResponse, ProviderError, QuotaExhausted


class CloudflareProvider(LLMProvider):
    name = "cloudflare"

    def classify(self, r: httpx.Response) -> ProviderError:
        body = r.text.lower()
        # Heuristic: Cloudflare reports an exhausted daily allocation as an error mentioning it.
        if r.status_code in (429, 403) and ("allocation" in body or "neuron" in body):
            return QuotaExhausted(f"cloudflare daily free allocation used up (HTTP {r.status_code})")
        return super().classify(r)

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        s = self.settings
        url = (f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}"
               f"/ai/run/{s.cloudflare_model}")
        headers = {"Authorization": f"Bearer {s.cloudflare_api_token}", "Content-Type": "application/json"}
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "max_tokens": max_tokens}
        data = await self._post(url, headers, body)
        if data.get("success") is False:
            raise InvalidResponse(f"cloudflare reported failure: {str(data.get('errors'))[:200]}")
        result = data.get("result")
        text = None
        if isinstance(result, dict):
            text = result.get("response")
            if text is None and result.get("choices"):
                text = result["choices"][0].get("message", {}).get("content")
        if isinstance(text, (dict, list)):
            text = json.dumps(text, ensure_ascii=False)
        if not isinstance(text, str) or not text.strip():
            raise InvalidResponse("cloudflare returned no text")
        return text
