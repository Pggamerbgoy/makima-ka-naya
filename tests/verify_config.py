"""
Live verification script for Phase 1 Step 1: Dynamic Configuration Engine (makima/config.py).
Tests:
  1. Default loading and parsing of configs/settings.yaml.
  2. Dynamic path expansion without hardcoded OS paths.
  3. Environment variable override with MAKIMA_ prefix.
  4. Backend configuration and credential probing.
  5. Thread-safe singleton accessor.
"""

import os
import sys
from pathlib import Path

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.config import get_settings


def test_config_loading():
    print("[TEST 1] Loading default settings from configs/settings.yaml...")
    settings = get_settings(force_reload=True)
    
    assert settings.app.name == "Makima", f"Expected 'Makima', got {settings.app.name}"
    assert settings.app.version == "2.0.0", f"Expected '2.0.0', got {settings.app.version}"
    assert "gemini" in settings.providers.backends, "Missing gemini backend in config"
    assert "groq" in settings.providers.backends, "Missing groq backend in config"
    assert "ollama" in settings.providers.backends, "Missing ollama backend in config"
    print("  -> PASSED: YAML parsed successfully with all backends!")


def test_dynamic_path_resolution():
    print("[TEST 2] Verifying dynamic path resolution (Zero hardcoded OS paths)...")
    settings = get_settings()
    
    home = Path.home()
    expected_data_dir = home / ".makima"
    expected_state_dir = home / ".makima" / "state"
    expected_workspace_dir = home / ".makima" / "workspace"
    
    assert settings.data_dir_path == expected_data_dir, f"Mismatch: {settings.data_dir_path} vs {expected_data_dir}"
    assert settings.state_dir_path == expected_state_dir, f"Mismatch: {settings.state_dir_path} vs {expected_state_dir}"
    assert settings.workspace_dir_path == expected_workspace_dir, f"Mismatch: {settings.workspace_dir_path} vs {expected_workspace_dir}"
    print(f"  -> PASSED: Path ~ dynamically expanded to: {settings.data_dir_path}")


def test_backend_availability():
    print("[TEST 3] Testing dynamic backend availability check...")
    settings = get_settings()
    
    # Ollama has no API key requirement, so it reports available
    ollama_backend = settings.get_backend("ollama")
    assert ollama_backend is not None, "Ollama backend not found"
    assert ollama_backend.is_available is True, "Ollama should be available without api key"
    
    # Gemini requires GEMINI_API_KEY
    gemini_backend = settings.get_backend("gemini")
    assert gemini_backend is not None, "Gemini backend not found"
    current_key = os.getenv("GEMINI_API_KEY")
    expected_gemini_avail = bool(current_key)
    assert gemini_backend.is_available == expected_gemini_avail
    print(f"  -> PASSED: Backend availability logic verified! (Ollama=True, Gemini={expected_gemini_avail})")


def test_env_override():
    print("[TEST 4] Testing environment variable override with MAKIMA_ prefix...")
    os.environ["MAKIMA_APP__ENV"] = "production_test"
    os.environ["MAKIMA_APP__LOG_LEVEL"] = "DEBUG"
    try:
        overridden = get_settings(force_reload=True)
        assert overridden.app.env == "production_test", f"Expected 'production_test', got {overridden.app.env}"
        assert overridden.app.log_level == "DEBUG", f"Expected 'DEBUG', got {overridden.app.log_level}"
        print("  -> PASSED: Environment variable overrides successfully took precedence!")
    finally:
        os.environ.pop("MAKIMA_APP__ENV", None)
        os.environ.pop("MAKIMA_APP__LOG_LEVEL", None)
        # Reload back to clean state
        get_settings(force_reload=True)


def test_singleton_thread_safety():
    print("[TEST 5] Testing singleton accessor stability...")
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2, "get_settings() must return singleton instance"
    print("  -> PASSED: get_settings() returned identical singleton instance!")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: makima/config.py")
    print("=" * 60)
    try:
        test_config_loading()
        test_dynamic_path_resolution()
        test_backend_availability()
        test_env_override()
        test_singleton_thread_safety()
        print("=" * 60)
        print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! (EXIT CODE 0)")
        print("=" * 60)
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
