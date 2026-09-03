"""OpenAI-compatible LLM client with schema-forced structured output.

Contract (AI_SYSTEM.md §3):
- Structured output is requested via a single `submit` tool definition
  (tool-calling is the most reliable JSON forcing on servers without
  `response_format`), with a fenced-JSON fallback for tool-less endpoints.
- Responses are validated against the caller's pydantic model; validation
  errors are fed back once for repair, then the call fails loudly.
- Every call is recorded in agent_runs (tokens, latency, status).
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.models import AgentRun

logger = logging.getLogger("secondbrain.llm")

T = TypeVar("T", bound=BaseModel)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class LLMError(Exception):
    pass


class LLMClient:
    """Live client against any OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.timeout = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries

    def available(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/models", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

    def structured(
        self,
        model: str,
        agent: str,
        purpose: str,
        system: str,
        user: str,
        schema_model: type[T],
        db=None,
        user_id=None,
    ) -> T:
        """One structured call: tool-forced if possible, fenced-JSON fallback, validate+repair."""
        schema = schema_model.model_json_schema()
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "submit",
                        "description": "Submit the structured result.",
                        "parameters": schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "submit"}},
        }
        prompt_hash = hashlib.sha256(f"{system}|{user}".encode()).hexdigest()[:16]
        run = _start_run(db, user_id, agent, purpose, model, prompt_hash)
        started = time.perf_counter()

        messages = payload["messages"]
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                body = self._post({**payload, "messages": messages})
                message = body["choices"][0]["message"]
                raw_json = self._extract_json(message)
                if raw_json is None:
                    raise LLMError("model returned no parseable structured output")
                result = schema_model.model_validate_json(raw_json)
                _finish_run(
                    run, db, "succeeded", started,
                    body.get("usage", {}),
                )
                return result
            except Exception as exc:  # validation or transport — one repair round
                last_error = exc
                repair = (
                    f"Your previous output was rejected: {exc}\n"
                    f"Respond again by calling the `submit` tool with valid JSON "
                    f"matching this schema exactly:\n{json.dumps(schema)[:4000]}"
                )
                messages = messages + [
                    {"role": "assistant", "content": str(exc)[:1000]},
                    {"role": "user", "content": repair},
                ]
        _finish_run(run, db, "failed", started, {}, error=str(last_error))
        raise LLMError(f"structured call failed after {self.max_retries + 1} attempts: {last_error}")

    @staticmethod
    def _extract_json(message: dict) -> str | None:
        tool_calls = message.get("tool_calls") or []
        for call in tool_calls:
            if call.get("function", {}).get("name") == "submit":
                return call["function"]["arguments"]
        content = message.get("content") or ""
        fenced = _JSON_FENCE.search(content)
        if fenced:
            return fenced.group(1)
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        return None


def _start_run(db, user_id, agent, purpose, model, prompt_hash):
    run = None
    if db is not None:
        run = AgentRun(
            user_id=user_id, agent=agent, purpose=purpose, model=model, prompt_hash=prompt_hash
        )
        db.add(run)
        db.commit()
    return run


def _finish_run(run, db, status, started, usage, error=None):
    if run is None:
        return
    run.status = status
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.input_tokens = usage.get("prompt_tokens")
    run.output_tokens = usage.get("completion_tokens")
    run.error = str(error)[:1000] if error else None
    if db is not None:
        db.commit()


class FakeLLMClient(LLMClient):
    """Test double: routes calls through a responder callback, no network."""

    def __init__(self, responder: Callable[[str, str, str], dict]):
        super().__init__(base_url="http://fake.test/v1", api_key=None)
        self.responder = responder
        self.calls: list[tuple[str, str, str]] = []

    def available(self) -> bool:
        return True

    def structured(self, model, agent, purpose, system, user, schema_model, db=None, user_id=None):
        self.calls.append((agent, purpose, user))
        payload = self.responder(agent, purpose, user)
        return schema_model.model_validate(payload)
