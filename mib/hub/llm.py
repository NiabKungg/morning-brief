"""Client for the local llama-server (OpenAI-compatible) running LFM3-1.7B."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from mib.common.timeutil import iso

log = logging.getLogger(__name__)

# LFM3 model-card defaults for chat/agents (temperature 0.1, top_k 50); a light repeat penalty because the
# outputs are JSON, where structural tokens repeat by design.
SAMPLING = {"temperature": 0.1, "top_k": 50, "repeat_penalty": 1.05}


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    finish_reason: str | None
    stats: dict


class LLM:
    def __init__(self, base_url: str, model: str) -> None:
        self.model = model
        self._http = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(900.0, connect=5.0))
        self._lock = asyncio.Lock()
        self.online = False
        self.ctx: int | None = None
        self.busy = False
        self.last: dict | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    def state(self) -> dict:
        return {"online": self.online, "model": self.model, "ctx": self.ctx, "busy": self.busy, "last": self.last}

    async def refresh(self) -> None:
        try:
            resp = await self._http.get("/health", timeout=3)
            self.online = resp.status_code == 200
            if self.online and self.ctx is None:
                props = (await self._http.get("/props", timeout=5)).json()
                self.ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        except httpx.HTTPError:
            self.online = False

    async def complete(self, messages: list[dict], *, grammar: str | None = None, max_tokens: int = 1024,
                       phase: str = "llm", on_text: Callable[[str], Awaitable[None]] | None = None) -> Completion:
        """Stream one chat completion (thinking disabled: LFM3 reasoning traces are too slow on a Pi 5)."""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
            **SAMPLING,
        }
        if grammar:
            body["grammar"] = grammar
        text, finish, timings = [], None, {}
        started = time.monotonic()
        async with self._lock:
            self.busy = True
            try:
                async with self._http.stream("POST", "/v1/chat/completions", json=body) as resp:
                    if resp.status_code != 200:
                        raise LLMError(f"llama-server HTTP {resp.status_code}: {(await resp.aread())[:300]!r}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        timings = chunk.get("timings") or timings
                        for choice in chunk.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                text.append(piece)
                                if on_text:
                                    await on_text(piece)
                            finish = choice.get("finish_reason") or finish
            except httpx.HTTPError as exc:
                self.online = False
                raise LLMError(f"llama-server unreachable: {exc}") from exc
            finally:
                self.busy = False
        stats = {
            "prompt_tokens": timings.get("prompt_n"),
            "cached_tokens": timings.get("cache_n"),
            "gen_tokens": timings.get("predicted_n"),
            "prompt_tps": round(timings.get("prompt_per_second") or 0, 1),
            "gen_tps": round(timings.get("predicted_per_second") or 0, 1),
            "ms": int((time.monotonic() - started) * 1000),
        }
        self.last = {"phase": phase, "prompt_tps": stats["prompt_tps"], "gen_tps": stats["gen_tps"], "at": iso()}
        return Completion("".join(text), finish, stats)
