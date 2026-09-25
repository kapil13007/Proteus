"""Groq chat-completions client, tuned for the free tier.

Plain HTTPS against Groq's OpenAI-compatible endpoint: no framework, so every
request parameter that affects latency or cost is visible right here.

  * strict JSON-schema output   -> the reply always parses; no "fix your JSON" retries
  * reasoning_effort = low      -> gpt-oss spends few hidden reasoning tokens on a
                                   translation task (measured: ~145 per call)
  * one request at a time       -> the free tier allows 8K tokens/minute, so
                                   parallel calls would only collect 429s
  * 429 handling                -> waits exactly as long as Groq's retry-after says
"""
import json
import threading
import time

import httpx

from app.config import settings


class LlmError(Exception):
    pass


_slot = threading.BoundedSemaphore(1)
_MAX_WAIT_SEC = 30.0


class GroqClient:
    provider = "groq"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float, reasoning_effort: str):
        self.model = model
        self._key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout
        self._effort = reasoning_effort
        self._strict_ok = True  # flips off if the model rejects json_schema mode

    def complete_json(self, system: str, user: str, schema: dict, name: str, max_tokens: int) -> tuple[dict, dict]:
        """Returns (parsed JSON reply, usage dict)."""
        body = {
            "model": self.model,
            "temperature": 0,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = self._effort
            body["include_reasoning"] = False

        with _slot:
            data, latency_ms = self._post_with_retries(body, schema, name)

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "length":
            raise LlmError("LLM reply was cut off (max tokens reached)")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LlmError(f"LLM reply was not valid JSON: {content[:200]}") from e

        u = data.get("usage") or {}
        usage = {
            "calls": 1,
            "promptTokens": u.get("prompt_tokens", 0),
            "completionTokens": u.get("completion_tokens", 0),
            "cachedTokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
            "reasoningTokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
            "latencyMs": latency_ms,
        }
        return parsed, usage

    def _post_with_retries(self, body: dict, schema: dict, name: str) -> tuple[dict, int]:
        headers = {"Authorization": f"Bearer {self._key}"}
        last_error = "unknown error"
        for attempt in range(4):
            body["response_format"] = (
                {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
                if self._strict_ok else {"type": "json_object"})
            started = time.perf_counter()
            try:
                resp = httpx.post(self._url, json=body, headers=headers, timeout=self._timeout)
            except httpx.HTTPError as e:
                last_error = f"network error: {e}"
                time.sleep(min(2 ** attempt, 8))
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            if resp.status_code == 200:
                return resp.json(), latency_ms
            detail = resp.text[:300]
            if resp.status_code == 429:
                wait = float(resp.headers.get("retry-after") or 2 ** attempt)
                last_error = f"rate limited (429), waited {wait:.0f}s"
                time.sleep(min(wait, _MAX_WAIT_SEC))
                continue
            if resp.status_code >= 500:
                last_error = f"Groq {resp.status_code}: {detail}"
                time.sleep(min(2 ** attempt, 8))
                continue
            if resp.status_code == 400 and self._strict_ok and ("response_format" in detail or "json_schema" in detail):
                self._strict_ok = False  # this model has no strict mode: fall back to JSON mode
                continue
            if resp.status_code == 401:
                raise LlmError("Groq rejected the API key (401) — check GROQ_API_KEY in backend/.env")
            raise LlmError(f"Groq {resp.status_code}: {detail}")
        raise LlmError(f"LLM call failed after retries: {last_error}")


def get_client() -> GroqClient | None:
    """None when no key is configured: the pipeline still runs every deterministic step."""
    if not settings.groq_api_key:
        return None
    return GroqClient(settings.groq_api_key, settings.groq_model, settings.groq_base_url,
                      settings.llm_timeout_sec, settings.groq_reasoning_effort)


def list_price_usd(usage: dict) -> float:
    """What the tokens would cost at Groq's published prices (the free tier bills $0)."""
    cached = usage.get("cachedTokens", 0)
    fresh = max(usage.get("promptTokens", 0) - cached, 0)
    return (fresh * settings.groq_price_per_1m_input
            + cached * settings.groq_price_per_1m_cached_input
            + usage.get("completionTokens", 0) * settings.groq_price_per_1m_output) / 1_000_000
