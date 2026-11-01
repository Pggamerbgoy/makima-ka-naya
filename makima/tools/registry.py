import inspect
import functools
from typing import Dict, Any, Callable, List, Optional, get_type_hints

class ToolRegistry:
    """Dynamic auto-discovery and execution registry for Makima Python tools."""
    _instance: Optional["ToolRegistry"] = None

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(
        self,
        name: str,
        description: str,
        func: Callable,
        category: str = "general",
        is_destructive: bool = False,
        requires_elevation: bool = False,
    ):
        sig = inspect.signature(func)
        hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}
        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            param_type = "string"
            t = hints.get(param_name, str)
            if t == int:
                param_type = "integer"
            elif t == float:
                param_type = "number"
            elif t == bool:
                param_type = "boolean"
            elif t in (list, List):
                param_type = "array"

            parameters["properties"][param_name] = {
                "type": param_type,
                "description": f"Argument {param_name}",
            }
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(param_name)

        self.tools[name] = {
            "name": name,
            "description": description,
            "func": func,
            "category": category,
            "is_destructive": is_destructive,
            "requires_elevation": requires_elevation,
            "parameters": parameters,
            "enabled": True,
        }

    def tool(self, name: str, description: str, category: str = "general", is_destructive: bool = False):
        """Decorator for self-registering functions."""
        def decorator(f: Callable):
            self.register(name, description, f, category, is_destructive)
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return f(*args, **kwargs)
            return wrapper
        return decorator

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self.tools.get(name)

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self.tools.values())

    async def execute(self, name: str, **kwargs) -> Any:
        tool = self.tools.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found in registry.")
        if not tool.get("enabled", True):
            raise PermissionError(f"Tool '{name}' is currently disabled in system settings.")

        func = tool["func"]
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        return func(**kwargs)
