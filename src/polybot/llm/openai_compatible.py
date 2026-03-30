from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.polybot.llm.base import LLMAdapter


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"No valid JSON object found in model output: {text[:200]}")


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(self, model: str, api_key: str, base_url: str = "", force_json_mode: bool = True) -> None:
        self.model = model
        self.force_json_mode = force_json_mode
        if not api_key:
            raise ValueError(f"Missing API key for model {model}")
        self.client = OpenAI(api_key=api_key, base_url=base_url or None)

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None
        strategies = []
        if self.force_json_mode:
            strategies.append({"response_format": {"type": "json_object"}})
        strategies.append({})
        # Final repair strategy with compact output request.
        repair_messages = messages + [
            {
                "role": "user",
                "content": "Output final answer as one strict JSON object only, no prose.",
            }
        ]
        strategies.append({"messages": repair_messages, "response_format": {"type": "json_object"}})
        strategies.append({"messages": repair_messages})

        for strategy in strategies:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": strategy.get("messages", messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if "response_format" in strategy:
                kwargs["response_format"] = strategy["response_format"]
            try:
                resp = self.client.chat.completions.create(**kwargs)
                msg = resp.choices[0].message
                content = (msg.content or "").strip()
                if content:
                    return _extract_json_object(content)
                reasoning_content = getattr(msg, "reasoning_content", None)
                if reasoning_content:
                    try:
                        return _extract_json_object(str(reasoning_content))
                    except Exception as exc:
                        last_error = exc
                        continue
                last_error = ValueError("Model returned empty content and no parseable reasoning JSON")
            except Exception as exc:
                last_error = exc
                continue

        raise ValueError(f"Failed to parse JSON from model {self.model}: {last_error}")
