"""
Model-agnostic LLM client using litellm.
Supports: Claude, GPT-4, Gemini, Ollama, and 100+ other providers via a single API.

Features:
- API key rotation: automatically cycles through multiple keys to avoid rate limits
- Smart retry: extracts retryDelay from API error responses, separates rate-limit vs server-error counters
- Model fallback: if primary model fails, automatically tries fallback model
- Provider auto-detection: reads GEMINI_API_KEY, GEMINI_API_KEY_2, etc. from environment

litellm handles all provider-specific auth automatically from environment variables.
"""

import os
import re
import time
import itertools

from utils.logger import log

try:
    import litellm

    litellm.set_verbose = False
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None


def _collect_api_keys() -> list:
    """
    Collect all available API keys from environment variables.
    Supports: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, etc.
    Returns list of (key_name, key_value) tuples.
    """
    keys = []
    base = os.environ.get("GEMINI_API_KEY")
    if base:
        keys.append(("GEMINI_API_KEY", base))
    for i in range(2, 10):
        k = os.environ.get(f"GEMINI_API_KEY_{i}")
        if k:
            keys.append((f"GEMINI_API_KEY_{i}", k))
    return keys


class LLMClient:
    """Unified LLM interface — call any model with the same API.
    
    Supports API key rotation for Gemini models and automatic model fallback.
    """

    def __init__(self, config: dict):
        self.model = config.get("model", "gemini/gemini-2.5-flash")
        self.max_tokens = config.get("max_tokens", 8192)
        self.default_system_prompt = config.get("system_prompt", None)

        # Fallback model chain: if primary fails, try these in order
        self.fallback_models = config.get("fallback_models", [])
        if not self.fallback_models:
            # Auto-configure fallbacks based on primary model
            if "gemini-2.5" in self.model:
                self.fallback_models = ["gemini/gemini-1.5-flash"]
            elif "groq" in self.model:
                self.fallback_models = ["gemini/gemini-1.5-flash"]

        if litellm is None:
            raise ImportError(
                "litellm is required. Install with: pip install litellm"
            )

        # Set up API key rotation for Gemini models
        self._api_keys = []
        self._key_cycle = None
        if "gemini" in self.model.lower():
            self._api_keys = _collect_api_keys()
            if self._api_keys:
                self._key_cycle = itertools.cycle(self._api_keys)
                log.info(f"Loaded {len(self._api_keys)} Gemini API keys for rotation")

    def _get_next_api_key(self):
        """Get the next API key from the rotation pool."""
        if self._key_cycle:
            name, key = next(self._key_cycle)
            log.debug(f"Using API key: {name}")
            return key
        return None

    def chat(
        self,
        user_prompt: str,
        system_prompt: str = None,
        temperature: float = 0.0,
        max_retries: int = 5,
    ) -> str:
        """
        Send a chat completion request with automatic retry and fallback.
        """
        # Try primary model first
        try:
            return self._call_with_retries(
                self.model, user_prompt, system_prompt, temperature, max_retries
            )
        except Exception as primary_error:
            # Try fallback models
            for fb_model in self.fallback_models:
                log.warning(f"Primary model failed. Trying fallback: {fb_model}")
                try:
                    return self._call_with_retries(
                        fb_model, user_prompt, system_prompt, temperature, max_retries=3
                    )
                except Exception as fb_error:
                    log.warning(f"Fallback {fb_model} also failed: {fb_error}")
                    continue

            # All models failed
            raise primary_error

    def _call_with_retries(
        self,
        model: str,
        user_prompt: str,
        system_prompt: str = None,
        temperature: float = 0.0,
        max_retries: int = 5,
    ) -> str:
        """Make an LLM call with smart retry logic."""
        messages = []

        effective_system = system_prompt if system_prompt is not None else self.default_system_prompt
        if effective_system:
            messages.append({"role": "system", "content": effective_system})

        messages.append({"role": "user", "content": user_prompt})

        prompt_chars = len(user_prompt) + (len(effective_system) if effective_system else 0)
        log.debug(f"LLM call: model={model}, ~{prompt_chars} chars, temp={temperature}")

        keys_tried = 0
        total_keys = len(self._api_keys) if self._api_keys else 1
        rate_limit_retries = 0
        server_error_retries = 0
        max_rate_retries = max_retries
        max_server_retries = max_retries

        for attempt in range(max_retries * 2 + 1):  # Total attempt budget
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": self.max_tokens,
                }

                # Rotate API key for Gemini models
                if "gemini" in model.lower():
                    api_key = self._get_next_api_key()
                    if api_key:
                        kwargs["api_key"] = api_key

                response = litellm.completion(**kwargs)
                content = response.choices[0].message.content
                log.debug(f"LLM response: {len(content)} chars")
                return content

            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = any(
                    kw in error_str
                    for kw in ["rate limit", "429", "quota", "resource exhausted", "too many"]
                )
                is_server_error = any(
                    kw in error_str
                    for kw in ["503", "unavailable", "500", "internal", "high demand"]
                )

                if is_rate_limit and rate_limit_retries < max_rate_retries:
                    rate_limit_retries += 1
                    keys_tried += 1

                    # Try next key immediately if we haven't tried all
                    if keys_tried < total_keys:
                        log.warning(f"Rate limited on key. Rotating to next key ({keys_tried}/{total_keys})...")
                        continue

                    # All keys exhausted — wait
                    keys_tried = 0
                    delay_match = re.search(r'retry.*?(\d+\.?\d*)\s*s', error_str)
                    if delay_match:
                        wait_time = int(float(delay_match.group(1))) + 5
                    else:
                        wait_time = 45 * rate_limit_retries
                    log.warning(f"All keys rate limited. Waiting {wait_time}s (retry {rate_limit_retries}/{max_rate_retries})...")
                    time.sleep(wait_time)
                    continue

                if is_server_error and server_error_retries < max_server_retries:
                    server_error_retries += 1
                    # Exponential backoff: 15, 30, 60, 90, 120s
                    wait_time = min(15 * (2 ** (server_error_retries - 1)), 120)
                    log.warning(f"Server error. Waiting {wait_time}s (retry {server_error_retries}/{max_server_retries})...")
                    time.sleep(wait_time)
                    continue

                log.error(f"LLM call failed: {e}")
                raise
