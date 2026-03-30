from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMAdapter(ABC):
    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        raise NotImplementedError
