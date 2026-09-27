"""
Local Ollama client for ItDebugs.

Optimized for CPU-only machines with limited RAM and structured JSON output.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    """Raised when communication with Ollama fails."""


ROOT_CAUSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_cause": {
            "type": "string",
        },
        "file": {
            "type": ["string", "null"],
        },
        "line": {
            "type": ["integer", "null"],
        },
        "faulty_code": {
            "type": ["string", "null"],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "suggested_fix": {
            "type": ["string", "null"],
        },
    },
    "required": [
        "root_cause",
        "file",
        "line",
        "faulty_code",
        "confidence",
        "suggested_fix",
    ],
    "additionalProperties": False,
}


class OllamaClient:
    """Small dependency-free client for the Ollama chat API."""

    def __init__(
        self,
        model: str = "ibm/granite3.3:2b-instruct-q4_0",
        host: str = "http://localhost:11434",
        timeout: int = 180,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = True,
    ) -> str:
        """Send a compact structured request to Ollama."""

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": 160,
                "num_ctx": 2048,
            },
        }

        if json_mode:
            payload["format"] = ROOT_CAUSE_SCHEMA

        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                body = response.read().decode("utf-8")

        except urllib.error.URLError as exc:
            raise OllamaError(
                f"Could not connect to Ollama at {self.host}. "
                "Make sure Ollama is running."
            ) from exc

        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama request timed out after {self.timeout} seconds."
            ) from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaError(
                "Ollama returned invalid JSON."
            ) from exc

        message = result.get("message", {})
        content = message.get("content")

        if not isinstance(content, str):
            raise OllamaError(
                "Ollama response did not contain message.content."
            )

        return content

    def health_check(self) -> bool:
        """Return True when the Ollama server is reachable."""

        request = urllib.request.Request(
            f"{self.host}/api/tags",
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=10,
            ):
                return True
        except (urllib.error.URLError, TimeoutError):
            return False