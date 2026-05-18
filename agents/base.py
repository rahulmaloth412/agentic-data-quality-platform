"""Base agent class with Gemini API integration, retry, and structured output."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import structlog
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from configs.settings import get_settings

logger = structlog.get_logger(__name__)


class BaseAgent:
    """Base class for all DQ platform agents with Gemini API integration."""

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._name = agent_name
        self._system_prompt = system_prompt
        self._model = model or settings.gemini.model
        self._max_tokens = max_tokens or settings.gemini.max_tokens
        self._client = genai.Client(api_key=settings.gemini.api_key)
        self._log = logger.bind(agent=agent_name)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    async def _call_claude(
        self,
        prompt: str,
        context: Optional[dict[str, Any]] = None,
        stream: bool = False,
    ) -> str:
        """Call Gemini API and return the text response."""
        content = prompt
        if context:
            context_str = json.dumps(context, indent=2, default=str)
            content = f"Context:\n{context_str}\n\n{prompt}"

        self._log.info("calling_gemini", model=self._model, prompt_preview=prompt[:100])
        start = time.monotonic()

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                max_output_tokens=self._max_tokens,
            ),
        )

        duration = time.monotonic() - start
        self._log.info("gemini_response_received", duration_seconds=round(duration, 2))
        return response.text

    async def _call_claude_json(
        self, prompt: str, context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Call Gemini and parse JSON from the response."""
        raw = await self._call_claude(prompt, context)
        return self._extract_json(raw)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract and parse the first JSON object or array from text."""
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        import re
        json_block = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if json_block:
            try:
                return json.loads(json_block.group(1))
            except json.JSONDecodeError:
                pass

        obj_match = re.search(r"\{[\s\S]*\}", text)
        if obj_match:
            try:
                return json.loads(obj_match.group())
            except json.JSONDecodeError:
                pass

        arr_match = re.search(r"\[[\s\S]*\]", text)
        if arr_match:
            try:
                result = json.loads(arr_match.group())
                return {"items": result}
            except json.JSONDecodeError:
                pass

        self._log.error("json_parse_failed", raw_text=text[:500])
        return {"error": "Failed to parse JSON from Gemini response", "raw": text[:500]}
