"""Provider wire adapters."""
from .gemini import GeminiAdapter
from .openai_compatible import OpenAICompatibleAdapter

__all__ = ["GeminiAdapter", "OpenAICompatibleAdapter"]
