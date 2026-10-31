from app.services.providers.base import LLMProvider
from app.services.providers.errors import InvalidResponse


class OpenAICompatProvider(LLMProvider):
    """Chat-completions style endpoint shared by Hugging Face, xAI and local servers."""

    def _endpoint(self) -> tuple[str, str, str]:
        """Return (base_url, api_key, model)."""
        raise NotImplementedError

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        base, key, model = self._endpoint()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "max_tokens": max_tokens, "temperature": 0.7,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        data = await self._post(f"{base.rstrip('/')}/chat/completions", headers, body)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise InvalidResponse(f"{self.name} response has no choices[0].message.content") from e
        if not isinstance(text, str) or not text.strip():
            raise InvalidResponse(f"{self.name} returned empty text")
        return text


class HuggingFaceProvider(OpenAICompatProvider):
    name = "huggingface"

    def _endpoint(self):
        s = self.settings
        return s.huggingface_base_url, s.huggingface_api_key, s.huggingface_model


class GrokProvider(OpenAICompatProvider):
    name = "grok"

    def _endpoint(self):
        s = self.settings
        return s.grok_base_url, s.grok_api_key, s.grok_model


class LocalProvider(OpenAICompatProvider):
    name = "local"

    def _endpoint(self):
        s = self.settings
        return s.local_base_url, "", s.local_model
