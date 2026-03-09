"""OpenAI LLM agent implementation.

Supports both standard chat completions and streaming responses
for low-latency voice AI applications.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from voxtra.ai.llm.base import AgentResponse, BaseAgent
from voxtra.config import LLMConfig
from voxtra.exceptions import LLMError

logger = logging.getLogger("voxtra.ai.llm.openai")


class OpenAIAgent(BaseAgent):
    """OpenAI-based LLM agent for voice conversations.

    Requires the `openai` package::

        pip install voxtra[openai]

    Configuration::

        ai:
          llm:
            provider: openai
            api_key: "your-api-key"
            model: "gpt-4o"
            temperature: 0.7
            system_prompt: "You are a helpful voice assistant."
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    async def connect(self) -> None:
        """Initialize the OpenAI async client."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise LLMError(
                "openai is required for OpenAIAgent. "
                "Install with: pip install voxtra[openai]"
            )

        if not self.config.api_key:
            raise LLMError("OpenAI API key is required")

        self._client = AsyncOpenAI(api_key=self.config.api_key)
        logger.info("OpenAI agent connected (model=%s)", self.config.model)

    async def respond(
        self,
        text: str,
        *,
        history: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
    ) -> AgentResponse:
        """Generate a complete response using OpenAI chat completions."""
        if self._client is None:
            raise LLMError("OpenAIAgent not connected. Call connect() first.")

        messages = self._build_messages(text, history=history, system_prompt=system_prompt)

        try:
            response = await self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            content = response.choices[0].message.content or ""
            self.add_to_history("user", text)
            self.add_to_history("assistant", content)

            return AgentResponse(
                text=content,
                finish_reason=response.choices[0].finish_reason or "",
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            )

        except Exception as exc:
            logger.error("OpenAI completion failed: %s", exc)
            raise LLMError(f"LLM completion failed: {exc}") from exc

    async def respond_stream(
        self,
        text: str,
        *,
        history: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens from OpenAI for low-latency TTS."""
        if self._client is None:
            raise LLMError("OpenAIAgent not connected. Call connect() first.")

        messages = self._build_messages(text, history=history, system_prompt=system_prompt)

        try:
            stream = await self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=True,
            )

            full_response = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield token

            self.add_to_history("user", text)
            self.add_to_history("assistant", full_response)

        except Exception as exc:
            logger.error("OpenAI streaming failed: %s", exc)
            raise LLMError(f"LLM streaming failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Close the OpenAI client."""
        self._client = None
        logger.info("OpenAI agent disconnected")

    def _build_messages(
        self,
        text: str,
        *,
        history: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        """Build the messages array for the OpenAI API."""
        messages: list[dict[str, str]] = []

        # System prompt
        prompt = system_prompt or self.config.system_prompt
        if prompt:
            messages.append({"role": "system", "content": prompt})

        # Conversation history
        conv_history = history if history is not None else self._conversation_history
        messages.extend(conv_history)

        # Current user message
        messages.append({"role": "user", "content": text})

        return messages
