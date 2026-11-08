"""Chat model client: send messages to the LLM and stream its reply back.

A "chat" is a list of messages with roles:
- system:    standing instructions (how to behave)
- user:      what the person (or our app on their behalf) says
- assistant: what the model said earlier
The model replies with the next assistant message, generated one token at a time.
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class ChatError(Exception):
    pass


@dataclass
class ChatUsage:
    prompt_tokens: int  # tokens the model read
    answer_tokens: int  # tokens it wrote


@dataclass
class ChatChunk:
    """One piece of a streamed reply. The last chunk has `usage` set."""

    text: str
    usage: ChatUsage | None = None


class ChatModel(Protocol):
    model_name: str

    def stream(
        self, messages: list[dict[str, str]], options: dict | None = None
    ) -> AsyncIterator[ChatChunk]: ...


class OllamaChat:
    """Streams from Ollama's POST /api/chat. Ollama replies with one JSON object per line
    ("NDJSON"): {"message": {"content": "Hel"}, "done": false} ... {"done": true, ...}."""

    def __init__(
        self,
        base_url: str = settings.ollama_url,
        model_name: str = settings.chat_model,
        num_ctx: int = settings.chat_num_ctx,
        temperature: float = settings.chat_temperature,
        max_answer_tokens: int = settings.chat_max_answer_tokens,
        seed: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.model_name = model_name
        self.options: dict = {
            "num_ctx": num_ctx,
            "temperature": temperature,
            "num_predict": max_answer_tokens,
        }
        if seed is not None:
            self.options["seed"] = seed  # same seed + same prompt = same answer

    async def stream(
        self, messages: list[dict[str, str]], options: dict | None = None
    ) -> AsyncIterator[ChatChunk]:
        """Stream a reply. `options` overrides model settings for this call only,
        e.g. {"temperature": 0}."""
        body = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "options": {**self.options, **(options or {})},
            "keep_alive": "30m",  # keep the model in memory between questions
        }
        timeout = httpx.Timeout(settings.chat_timeout_seconds, connect=5.0)
        try:
            async with (
                httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client,
                client.stream("POST", "/api/chat", json=body) as resp,
            ):
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")
                    raise ChatError(f"Ollama returned {resp.status_code}: {detail}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise ChatError(f"Ollama error: {data['error']}")
                    text = data.get("message", {}).get("content", "")
                    if data.get("done"):
                        usage = ChatUsage(
                            data.get("prompt_eval_count", 0), data.get("eval_count", 0)
                        )
                        self._check_truncation(usage)
                        yield ChatChunk(text, usage)
                    elif text:
                        yield ChatChunk(text)
        except httpx.HTTPError as exc:
            raise ChatError(
                f"Could not reach the chat model at {self.base_url} ({self.model_name}): {exc}"
            ) from exc

    def _check_truncation(self, usage: ChatUsage) -> None:
        if usage.prompt_tokens >= self.options["num_ctx"] - 16:
            log.warning(
                "Prompt (%d tokens) filled the %d-token context window; it was probably "
                "truncated. Lower search k or raise CHAT_NUM_CTX.",
                usage.prompt_tokens,
                self.options["num_ctx"],
            )


async def complete(
    chat: ChatModel, messages: list[dict[str, str]], options: dict | None = None
) -> str:
    """Collect a whole reply (for short internal calls that don't need streaming)."""
    return "".join([chunk.text async for chunk in chat.stream(messages, options)])


def get_chat_model() -> ChatModel:
    """FastAPI dependency (tests swap in a fake that needs no Ollama)."""
    return OllamaChat()
