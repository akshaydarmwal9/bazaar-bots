"""One small wrapper for every LLM provider: Groq, Gemini, or no LLM (templates).

Keys are read from environment variables (Codespaces secrets), never from files.
If a provider fails or hits a rate limit, the next one in `fallback_order` is tried.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from .config import load_llm_config


class LLM:
    def __init__(self, mode: Optional[str] = None) -> None:
        self.cfg = load_llm_config()
        self.mode = mode or os.getenv("BAZAAR_LLM") or self.cfg.get("default", "template")
        order = self.cfg.get("fallback_order", ["template"])
        self.order = [self.mode] + [p for p in order if p != self.mode] if self.mode != "template" else ["template"]
        self.temperature = float(self.cfg.get("temperature", 0.8))
        self.max_tokens = int(self.cfg.get("max_tokens", 400))
        self.calls = 0
        self.last_error: Optional[str] = None
        self._groq = None
        self._gemini = None

    # ---------- providers ----------
    def _key(self, provider: str) -> Optional[str]:
        env = self.cfg["providers"].get(provider, {}).get("env_key")
        return os.getenv(env) if env else None

    def _call_groq(self, system: str, user: str, max_tokens: int) -> str:
        if self._groq is None:
            from groq import Groq
            self._groq = Groq(api_key=self._key("groq"))
        model = self.cfg["providers"]["groq"]["model"]
        kwargs = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=max_tokens,
        )
        try:  # gpt-oss models are reasoning models: keep thinking short
            resp = self._groq.chat.completions.create(reasoning_effort="low", **kwargs)
        except TypeError:
            resp = self._groq.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()

    def _call_gemini(self, system: str, user: str, max_tokens: int) -> str:
        if self._gemini is None:
            from google import genai
            self._gemini = genai.Client(api_key=self._key("gemini"))
        from google.genai import types
        model = self.cfg["providers"]["gemini"]["model"]
        resp = self._gemini.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=self.temperature, max_output_tokens=max_tokens
            ),
        )
        return (resp.text or "").strip()

    # ---------- public ----------
    def available(self, provider: str) -> bool:
        return provider == "template" or bool(self._key(provider))

    def complete(self, system: str, user: str, max_tokens: Optional[int] = None) -> tuple[Optional[str], str]:
        """Return (text, provider_used). text is None when only templates are left."""
        max_tokens = max_tokens or self.max_tokens
        for provider in self.order:
            if provider == "template":
                return None, "template"
            if not self.available(provider):
                continue
            for attempt in range(2):
                try:
                    self.calls += 1
                    fn = self._call_groq if provider == "groq" else self._call_gemini
                    text = fn(system, user, max_tokens)
                    if text:
                        return text, provider
                    break
                except Exception as e:  # rate limit, network, bad model ID...
                    self.last_error = f"{provider}: {type(e).__name__}: {str(e)[:200]}"
                    if "429" in str(e) or "rate" in str(e).lower():
                        time.sleep(2 * (attempt + 1))
                        continue
                    break
        return None, "template"
