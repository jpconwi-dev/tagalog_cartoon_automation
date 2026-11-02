import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.security import redact
from app.schemas.content import ScenePlan, ScriptDoc, TopicRequest, VideoMetadata
from app.services import prompts
from app.services.providers.eligibility import check_eligibility
from app.services.providers.errors import (InvalidResponse, Misconfigured, ProviderError,
                                           QuotaExhausted, RateLimited, TransientError)

M = TypeVar("M", bound=BaseModel)


@dataclass
class HealthResult:
    ok: bool
    detail: str


def parse_json_model(raw: str, model: type[M]) -> M:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise InvalidResponse("response contains no JSON object")
    try:
        data = json.loads(text[start:end + 1])
        return model.model_validate(data)
    except (ValueError, ValidationError) as e:
        raise InvalidResponse(f"response failed validation: {str(e)[:300]}") from e


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers.get("retry-after", ""))
    except ValueError:
        return None


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self.timeout = settings.provider_timeout_seconds

    @abstractmethod
    async def _complete(self, system: str, prompt: str, max_tokens: int) -> str: ...

    # ---- HTTP helpers ----
    def classify(self, r: httpx.Response) -> ProviderError:
        snippet = redact(r.text[:200])
        code = r.status_code
        if code == 429:
            return RateLimited(f"{self.name} HTTP 429: {snippet}", _retry_after(r))
        if code == 402:
            return QuotaExhausted(f"{self.name} HTTP 402 (credits exhausted): {snippet}")
        if code in (401, 403):
            return Misconfigured(f"{self.name} HTTP {code} (auth/permission): {snippet}")
        if code == 408 or code >= 500:
            return TransientError(f"{self.name} HTTP {code}: {snippet}")
        return Misconfigured(f"{self.name} HTTP {code} (bad request/model): {snippet}")

    async def _post(self, url: str, headers: dict, body: dict) -> dict:
        client = self._client or httpx.AsyncClient()
        try:
            r = await client.post(url, headers=headers, json=body, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise TransientError(f"{self.name} request timed out") from e
        except httpx.HTTPError as e:
            raise TransientError(f"{self.name} network error: {type(e).__name__}") from e
        finally:
            if self._client is None:
                await client.aclose()
        if r.status_code >= 400:
            raise self.classify(r)
        try:
            data = r.json()
        except ValueError as e:
            raise InvalidResponse(f"{self.name} returned non-JSON body") from e
        if not isinstance(data, dict):
            raise InvalidResponse(f"{self.name} returned unexpected JSON shape")
        return data

    # ---- public interface (same for every provider) ----
    async def generate_script(self, req: TopicRequest) -> ScriptDoc:
        raw = await self._complete(prompts.SCRIPT_SYSTEM, prompts.script_prompt(req),
                                   self.settings.max_script_tokens)
        doc = parse_json_model(raw, ScriptDoc)
        limit = self.settings.max_video_duration_seconds * 1.15
        if doc.est_duration_seconds > limit:
            raise InvalidResponse(f"script too long ({doc.est_duration_seconds}s > {limit:.0f}s)")
        doc.provider = self.name
        doc.is_template = False
        return doc

    async def generate_scene_plan(self, script: ScriptDoc) -> ScenePlan:
        raw = await self._complete(prompts.SCENE_PLAN_SYSTEM, prompts.scene_plan_prompt(script),
                                   self.settings.max_script_tokens)
        plan = parse_json_model(raw, ScenePlan)
        if len(plan.scenes) != len(script.scenes):
            raise InvalidResponse("scene plan does not match number of script scenes")
        return plan

    async def generate_metadata(self, script: ScriptDoc) -> VideoMetadata:
        raw = await self._complete(prompts.METADATA_SYSTEM, prompts.metadata_prompt(script), 1200)
        return parse_json_model(raw, VideoMetadata)

    async def health_check(self, deep: bool = False) -> HealthResult:
        """Config check by default. deep=True spends one tiny request of free quota."""
        elig = check_eligibility(self.settings, self.name)
        if not elig.eligible:
            return HealthResult(False, elig.reason)
        if not deep:
            return HealthResult(True, "configured and eligible (not pinged)")
        try:
            await self._complete("Reply with the single word OK.", "ping", 8)
            return HealthResult(True, "ping succeeded")
        except ProviderError as e:
            return HealthResult(False, f"{e.kind}: {e}")
