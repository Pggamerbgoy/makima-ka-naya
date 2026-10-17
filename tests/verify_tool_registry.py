"""
Live verification script for Phase 1 Step 5: Dynamic Tool Registry & Auto-Discovery.
Tests:
  1. @tool decorator variations (bare, parameterized, instance-bound, async).
  2. Dynamic Pydantic v2 JSON schema auto-synthesis (types, defaults, required, docstrings, enums).
  3. Tool execution engine (sync via thread pool, async coroutine, argument coercion, positional-only).
  4. [TOOL_FAILED: name] fallback generator with intelligent alternatives hints.
  5. Auto-discovery scanner with pkgutil and filesystem inspection across nested subpackages.
  6. Registry lifecycle, tag filtering, and isolation.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import (
    Tool,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    get_registry,
    reset_registry,
    tool,
)


# ---------------------------------------------------------------------------
# Test 1: Decorator Variations & Registration
# ---------------------------------------------------------------------------

async def test_decorator_variations():
    print("\n[TEST 1] Testing @tool decorator variations and metadata binding...")
    reset_registry()
    reg = get_registry()

    # 1. Bare decorator without parentheses
    @tool
    def bare_add(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    assert getattr(bare_add, "__makima_tool__", False) is True
    assert getattr(bare_add, "__tool_name__", "") == "bare_add"
    assert "bare_add" in reg
    assert reg["bare_add"].name == "bare_add"
    assert reg["bare_add"].is_async is False

    # 2. Decorator with empty parentheses
    @tool()
    def paren_sub(x: float, y: float = 1.0) -> float:
        """Subtract y from x."""
        return x - y

    assert "paren_sub" in reg
    assert reg["paren_sub"].name == "paren_sub"

    # 3. Parameterized decorator with custom name, description, and tags
    @tool(name="custom_multiply", description="Multiplies numbers securely", tags=["math", "arithmetic"])
    async def async_mult(factor_a: int, factor_b: int) -> int:
        await asyncio.sleep(0.01)
        return factor_a * factor_b

    assert "custom_multiply" in reg
    assert reg["custom_multiply"].name == "custom_multiply"
    assert reg["custom_multiply"].description == "Multiplies numbers securely"
    assert reg["custom_multiply"].tags == ["math", "arithmetic"]
    assert reg["custom_multiply"].is_async is True

    # 4. Custom isolated registry instance decorator
    isolated_reg = ToolRegistry(name="isolated")

    @isolated_reg.tool(name="isolated_echo", tags=["debug"])
    def echo_message(msg: str) -> str:
        return f"Echo: {msg}"

    assert "isolated_echo" in isolated_reg
    assert "isolated_echo" not in reg  # Not leaked to global registry

    print("  [PASS] All decorator variations correctly register and isolate metadata.")


# ---------------------------------------------------------------------------
# Test 2: Dynamic Schema Auto-Synthesis (Pydantic v2)
# ---------------------------------------------------------------------------

class PriorityEnum(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


async def test_dynamic_schema_synthesis():
    print("\n[TEST 2] Testing dynamic Pydantic v2 JSON schema auto-synthesis...")
    reset_registry()
    reg = get_registry()

    @tool(name="create_task", tags=["tasks"])
    def create_task(
        title: str,
        priority: PriorityEnum = PriorityEnum.MEDIUM,
        tags: Optional[List[str]] = None,
        retries: int = 3,
        mode: Literal["sync", "async"] = "sync",
    ) -> Dict[str, Any]:
        """Create a scheduled task.

        Args:
            title: The title of the task to be created.
            priority: Execution priority level.
            tags: List of optional category tags.
            retries: Number of retry attempts on failure.
            mode: Task dispatch mode.
        """
        return {"title": title, "priority": priority}

    tool_obj = reg["create_task"]
    openai_schema = tool_obj.to_dict()
    gemini_schema = tool_obj.to_gemini_dict()

    # Verify OpenAI format
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "create_task"
    assert "Create a scheduled task." in openai_schema["function"]["description"]

    # Verify parameters schema
    params = openai_schema["function"]["parameters"]
    assert params["type"] == "object"
    props = params["properties"]

    # Check title (required, string, with docstring description)
    assert props["title"]["type"] == "string"
    assert props["title"]["description"] == "The title of the task to be created."

    # Check required fields: title has no default -> must be in required
    assert "required" in params
    assert "title" in params["required"]

    # Fields with defaults (priority, retries, tags, mode) must NOT be in required
    assert "retries" not in params["required"]
    assert "priority" not in params["required"]
    assert "tags" not in params["required"]
    assert "mode" not in params["required"]

    # Check retries default and type
    assert props["retries"]["type"] == "integer"
    assert props["retries"]["default"] == 3

    # Check Enum and Literal definitions
    assert "mode" in props
    assert props["mode"]["enum"] == ["sync", "async"]

    # Verify Gemini schema
    assert gemini_schema["name"] == "create_task"
    assert gemini_schema["parameters"]["type"] == "object"
    assert "title" in gemini_schema["parameters"]["properties"]

    # Verify registry.get_schemas()
    all_schemas = reg.get_schemas(format="openai")
    assert len(all_schemas) == 1
    assert all_schemas[0]["function"]["name"] == "create_task"

    print("  [PASS] Dynamic schema synthesis matches OpenAI and Gemini specifications.")


# ---------------------------------------------------------------------------
# Test 3: Tool Execution (Sync, Async, Coercion, Positional-Only)
# ---------------------------------------------------------------------------

async def test_tool_execution():
    print("\n[TEST 3] Testing dynamic tool execution (sync, async, coercion, positional-only)...")
    reset_registry()
    reg = get_registry()

    # 1. Sync tool with thread pool execution
    @tool
    def sync_compute(base: int, exponent: int = 2) -> int:
        return base ** exponent

    # Execute with exact types
    result_sync = await reg.execute("sync_compute", {"base": 3, "exponent": 3})
    assert result_sync == 27

    # Type coercion: string "4" should be coerced to integer 4
    result_coerced = await reg.execute("sync_compute", {"base": "4", "exponent": 2})
    assert result_coerced == 16

    # Default argument application
    result_default = await reg.execute("sync_compute", {"base": 5})
    assert result_default == 25

    # 2. Async tool
    @tool
    async def async_fetch_data(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        await asyncio.sleep(0.02)
        return {"status": 200, "url": url, "timeout": timeout}

    result_async = await reg.execute("async_fetch_data", {"url": "https://example.com/api"})
    assert result_async["status"] == 200
    assert result_async["url"] == "https://example.com/api"
    assert result_async["timeout"] == 5.0

    # 3. Extra argument handling (ignored safely if function does not accept **kwargs)
    result_extra = await reg.execute("sync_compute", {"base": 2, "exponent": 4, "hallucinated_param": "ignore_me"})
    assert result_extra == 16

    # 4. Positional-only parameter support
    @tool
    def pos_only_tool(prefix: str, /, suffix: str = "end") -> str:
        return f"{prefix}-{suffix}"

    result_pos = await reg.execute("pos_only_tool", {"prefix": "start", "suffix": "finish"})
    assert result_pos == "start-finish"

    # 5. Raw JSON string argument support
    json_arg_str = '{"base": 10, "exponent": 2}'
    result_json = await reg.execute("sync_compute", json_arg_str)
    assert result_json == 100

    print("  [PASS] Sync, async, coerced, positional-only, and JSON arguments execute flawlessly.")


# ---------------------------------------------------------------------------
# Test 4: Error Handling & [TOOL_FAILED: name] Fallback Generator
# ---------------------------------------------------------------------------

async def test_error_fallback_handling():
    print("\n[TEST 4] Testing [TOOL_FAILED: name] fallback generator and alternative hints...")
    reset_registry()
    reg = get_registry()

    @tool(tags=["math", "calc"])
    def safe_divide(numerator: float, denominator: float) -> float:
        """Divide two numbers."""
        if denominator == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return numerator / denominator

    @tool(tags=["math", "calc"])
    def safe_multiply(a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    @tool(tags=["math", "basic"])
    def safe_add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    # 1. Runtime exception -> Fallback returned with [TOOL_FAILED: name] and alternatives
    fallback_res = await reg.execute("safe_divide", {"numerator": 10, "denominator": 0})
    assert isinstance(fallback_res, str)
    assert fallback_res.startswith("[TOOL_FAILED: safe_divide]")
    assert "ZeroDivisionError: Cannot divide by zero" in fallback_res
    assert "Suggested alternatives:" in fallback_res
    assert "safe_multiply" in fallback_res or "safe_add" in fallback_res

    # 2. Argument validation error (missing required parameter)
    missing_param_res = await reg.execute("safe_divide", {"numerator": 10})
    assert isinstance(missing_param_res, str)
    assert missing_param_res.startswith("[TOOL_FAILED: safe_divide]")
    assert "ValidationError" in missing_param_res or "denominator" in missing_param_res

    # 3. Argument validation error (incompatible type)
    invalid_type_res = await reg.execute("safe_divide", {"numerator": 10, "denominator": "not_a_number"})
    assert isinstance(invalid_type_res, str)
    assert invalid_type_res.startswith("[TOOL_FAILED: safe_divide]")
    assert "ValidationError" in invalid_type_res

    # 4. Unregistered tool execution -> Fallback with nearest match
    unregistered_res = await reg.execute("safe_divider", {"x": 1})
    assert isinstance(unregistered_res, str)
    assert unregistered_res.startswith("[TOOL_FAILED: safe_divider]")
    assert "ToolNotFoundError" in unregistered_res or "not registered" in unregistered_res
    # Should suggest 'safe_divide' by similarity!
    assert "safe_divide" in unregistered_res

    # 5. catch_errors=False should raise directly
    try:
        await reg.execute("safe_divide", {"numerator": 10, "denominator": 0}, catch_errors=False)
        assert False, "Expected ToolExecutionError when catch_errors=False"
    except ToolExecutionError as exc:
        assert "ZeroDivisionError" in str(exc)

    try:
        await reg.execute("non_existent_tool", {}, catch_errors=False)
        assert False, "Expected ToolNotFoundError when catch_errors=False"
    except ToolNotFoundError:
        pass

    print("  [PASS] [TOOL_FAILED: name] fallback correctly delivers structured errors & alternative hints.")


# ---------------------------------------------------------------------------
# Test 5: Auto-Discovery Scanner
# ---------------------------------------------------------------------------

async def test_auto_discovery_scanner():
    print("\n[TEST 5] Testing auto-discovery scanner with pkgutil and nested subpackages...")
    
    # 1. First test discovering current makima.tools package
    reg = ToolRegistry(name="test_makima_tools")
    discovered_makima = reg.discover("makima.tools")
    assert isinstance(discovered_makima, int)

    # 2. Build a mock dynamic package structure in a temporary directory
    temp_dir = tempfile.mkdtemp(prefix="makima_discovery_test_")
    try:
        pkg_root = Path(temp_dir) / "dyn_tools"
        pkg_root.mkdir()
        (pkg_root / "__init__.py").write_text("# Dyn tools root package\n")

        # Top-level tool module
        mod1_path = pkg_root / "math_tools.py"
        mod1_path.write_text("""
from makima.tools import tool

@tool(name="dyn_square", tags=["math", "dyn"])
def dyn_square(n: int) -> int:
    '''Calculates the square of n.'''
    return n * n
""")

        # Nested subpackage
        subpkg = pkg_root / "network"
        subpkg.mkdir()
        (subpkg / "__init__.py").write_text("# Network subpackage\n")

        mod2_path = subpkg / "ping_tools.py"
        mod2_path.write_text("""
from makima.tools import tool

@tool(name="dyn_ping", tags=["network", "dyn"])
async def dyn_ping(host: str) -> str:
    '''Pings a host.'''
    return f"pong:{host}"
""")

        # Directory without __init__.py (filesystem walk verification)
        no_init_dir = pkg_root / "system"
        no_init_dir.mkdir()
        mod3_path = no_init_dir / "info.py"
        mod3_path.write_text("""
from makima.tools import tool

@tool(name="dyn_system_id", tags=["system", "dyn"])
def dyn_system_id() -> str:
    '''Returns mock system id.'''
    return "makima-v2-node"
""")

        # Add temp_dir to sys.path
        sys.path.insert(0, str(temp_dir))

        # Create isolated registry and discover
        dyn_reg = ToolRegistry(name="dyn_test")
        count = dyn_reg.discover("dyn_tools")

        assert count >= 3, f"Expected at least 3 tools discovered, found {count}"
        assert "dyn_square" in dyn_reg
        assert "dyn_ping" in dyn_reg
        assert "dyn_system_id" in dyn_reg

        # Test execution of discovered tools
        sq_res = await dyn_reg.execute("dyn_square", {"n": 9})
        assert sq_res == 81

        ping_res = await dyn_reg.execute("dyn_ping", {"host": "localhost"})
        assert ping_res == "pong:localhost"

        sys_res = await dyn_reg.execute("dyn_system_id", {})
        assert sys_res == "makima-v2-node"

        print(f"  [PASS] Auto-discovery successfully scanned package, nested subpackage, and filesystem modules ({count} tools).")
    finally:
        if str(temp_dir) in sys.path:
            sys.path.remove(str(temp_dir))
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 6: Tag Filtering, Lifecycle & Isolation
# ---------------------------------------------------------------------------

async def test_lifecycle_and_filtering():
    print("\n[TEST 6] Testing registry lifecycle, tag filtering, and isolation...")
    reset_registry()
    reg = get_registry()

    @tool(tags=["fs", "storage"])
    def read_doc(path: str) -> str:
        return f"content of {path}"

    @tool(tags=["fs", "write"])
    def write_doc(path: str, data: str) -> bool:
        return True

    @tool(tags=["net"])
    def fetch_url(url: str) -> str:
        return "html"

    # Filter by single tag
    fs_tools = reg.list_names(tags=["fs"])
    assert set(fs_tools) == {"read_doc", "write_doc"}

    # Filter by multiple tags
    storage_or_net = reg.list_names(tags=["storage", "net"])
    assert set(storage_or_net) == {"read_doc", "fetch_url"}

    # Schema export filtered by tag
    fs_schemas = reg.get_schemas(format="openai", tags=["fs"])
    assert len(fs_schemas) == 2
    schema_names = {s["function"]["name"] for s in fs_schemas}
    assert schema_names == {"read_doc", "write_doc"}

    # Unregister
    removed = reg.unregister("fetch_url")
    assert removed is not None
    assert "fetch_url" not in reg
    assert len(reg) == 2

    # Clear
    reg.clear()
    assert len(reg) == 0

    print("  [PASS] Registry lifecycle, unregistration, and tag filtering operational.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 70)
    print("MAKIMA v2 — STEP 5: TOOL REGISTRY & AUTO-DISCOVERY TEST SUITE")
    print("=" * 70)

    await test_decorator_variations()
    await test_dynamic_schema_synthesis()
    await test_tool_execution()
    await test_error_fallback_handling()
    await test_auto_discovery_scanner()
    await test_lifecycle_and_filtering()

    print("\n" + "=" * 70)
    print("ALL TOOL REGISTRY & AUTO-DISCOVERY TESTS PASSED (EXIT CODE 0)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
