from __future__ import annotations

from collections.abc import Iterator
from typing import Any
import json

import httpx

from .config import Settings
from .models import RetrievalHit


class OpenAICompatibleLlmClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.llm_api_base_url and settings.llm_model)
        self._client = httpx.Client(timeout=settings.llm_timeout_s)

    def close(self) -> None:
        self._client.close()

    def _build_messages(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        context_blocks: list[str] = []
        for idx, hit in enumerate(hits, start=1):
            payload = hit.payload
            context_blocks.append(
                "\n".join(
                    [
                        f"[Source {idx}]",
                        f"course_id: {payload.get('course_id')}",
                        f"major_code: {payload.get('major_code')}",
                        f"semester: {payload.get('semester')}",
                        f"chunk_type: {payload.get('chunk_type')}",
                        f"title_en: {payload.get('title_en')}",
                        f"text: {hit.text}",
                    ]
                )
            )
        context = "\n\n".join(context_blocks) if context_blocks else "No retrieval context found."

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are an FPT University curriculum and syllabus assistant. "
                    "Use the recent conversation for short-term memory and continuity. "
                    "Answer from the provided retrieval context first; do not invent facts not supported by it. "
                    "If the retrieved context is insufficient, say that clearly and suggest a better query. "
                    "When the user asks a follow-up like 'mon do', 'ky do', or 'what about that one', resolve it using recent chat history. "
                    "Keep answers natural and conversational, like a polished chat assistant."
                ),
            }
        ]

        for item in history or []:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

        user_prompt = (
            f"Current user question:\n{query}\n\n"
            f"Retrieved context:\n{context}\n\n"
            "Write the best possible grounded answer. If useful, summarize first and then add bullet points."
        )
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    def answer(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None = None,
    ) -> str:
        if not self.enabled:
            return (
                "LLM is not configured. Set LLM_API_BASE_URL, "
                "LLM_API_KEY, and LLM_MODEL in .env to enable answer synthesis."
            )

        response = self._client.post(
            f"{self.settings.llm_api_base_url.rstrip('/')}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.settings.llm_model,
                "messages": self._build_messages(query, hits, history=history),
                "temperature": 0.2,
                "stream": False,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        choices = payload.get("choices", [])
        if not choices:
            return "LLM returned no choices."
        message = choices[0].get("message", {})
        return message.get("content", "LLM returned empty content.")

    def answer_stream(
        self,
        query: str,
        hits: list[RetrievalHit],
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        if not self.enabled:
            yield (
                "LLM is not configured. Set LLM_API_BASE_URL, "
                "LLM_API_KEY, and LLM_MODEL in .env to enable answer synthesis."
            )
            return

        with self._client.stream(
            "POST",
            f"{self.settings.llm_api_base_url.rstrip('/')}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.settings.llm_model,
                "messages": self._build_messages(query, hits, history=history),
                "temperature": 0.2,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                line = line[5:].strip()
                if line == "[DONE]":
                    break
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
