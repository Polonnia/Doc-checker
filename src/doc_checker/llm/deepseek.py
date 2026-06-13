from __future__ import annotations

import json
import threading
import time
from typing import Any

import requests

from doc_checker.config import DeepSeekConfig


class DeepSeekClient:
    def __init__(self, cfg: DeepSeekConfig):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._stage_tokens: dict[str, dict[str, int]] = {}

    @property
    def enabled(self) -> bool:
        key = self._cfg.api_key.strip()
        return bool(key and key != "YOUR_DEEPSEEK_API_KEY")

    def _record_usage(self, stage: str, body: dict[str, Any]) -> None:
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)

        with self._lock:
            if stage not in self._stage_tokens:
                self._stage_tokens[stage] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            self._stage_tokens[stage]["prompt_tokens"] += prompt_tokens
            self._stage_tokens[stage]["completion_tokens"] += completion_tokens
            self._stage_tokens[stage]["total_tokens"] += total_tokens

    def get_stage_tokens(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                stage: {
                    "prompt_tokens": vals["prompt_tokens"],
                    "completion_tokens": vals["completion_tokens"],
                    "total_tokens": vals["total_tokens"],
                }
                for stage, vals in self._stage_tokens.items()
            }

    def chat_json(self, system_prompt: str, user_prompt: str, stage: str = "default") -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("DeepSeek API key is not configured")

        url = self._cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._cfg.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for attempt in range(self._cfg.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._cfg.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
                self._record_usage(stage, body)
                content = body["choices"][0]["message"]["content"]
                return json.loads(content)
            except Exception as exc:
                last_error = exc
                if attempt < self._cfg.max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                break

        raise RuntimeError(f"DeepSeek call failed: {last_error}")

    def chat_text(self, system_prompt: str, user_prompt: str, stage: str = "default") -> str:
        if not self.enabled:
            raise RuntimeError("DeepSeek API key is not configured")

        url = self._cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._cfg.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self._cfg.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        self._record_usage(stage, body)
        return body["choices"][0]["message"]["content"]
