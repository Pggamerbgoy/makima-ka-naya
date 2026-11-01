from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator

class BaseProvider(ABC):
    """Abstract base provider for LLM API wire adapters."""
    def __init__(self, model_name: str, api_key: str = ""):
        self.model_name = model_name
        self.api_key = api_key

    @abstractmethod
    async def generate(self, messages: list, tools: list = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def stream(self, messages: list, tools: list = None) -> AsyncGenerator[str, None]:
        pass
