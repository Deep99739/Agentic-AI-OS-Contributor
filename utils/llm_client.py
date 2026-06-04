"""
Model-agnostic LLM client using litellm.
Supports: Claude, GPT-4, Gemini, Ollama, and 100+ other providers via a single API.

litellm handles all provider-specific auth (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
automatically from environment variables.
"""

from utils.logger import log

try:
    import litellm

    litellm.set_verbose = False
    # Suppress litellm's internal logging noise
    litellm.suppress_debug_info = True
except ImportError:
    litellm = None


class LLMClient:
    """Unified LLM interface — call any model with the same API."""

    def __init__(self, config: dict):
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = config.get("max_tokens", 8192)

        if litellm is None:
            raise ImportError(
                "litellm is required. Install with: pip install litellm"
            )

    def chat(
        self,
        user_prompt: str,
        system_prompt: str = None,
        temperature: float = 0.0,
    ) -> str:
        """
        Send a chat completion request.

        Args:
            user_prompt: The main prompt / instruction.
            system_prompt: Optional system-level instruction.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            The model's text response.
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": user_prompt})

        prompt_chars = len(user_prompt) + (len(system_prompt) if system_prompt else 0)
        log.debug(f"LLM call: model={self.model}, ~{prompt_chars} chars, temp={temperature}")

        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=self.max_tokens,
            )
            content = response.choices[0].message.content
            log.debug(f"LLM response: {len(content)} chars")
            return content

        except Exception as e:
            log.error(f"LLM call failed: {e}")
            raise
