"""
Verification script for Step 11: Dynamic Markdown Skills Engine.
Tests:
  1. YAML frontmatter parsing and Skill dataclass serialization.
  2. Multi-directory skills scanning (<name>/SKILL.md and <name>.md).
  3. Skill search by query string and tag filtering.
  4. System prompt section generation and token estimation budgeting.
  5. Dynamic @tool save_learned_skill execution and live cache reloading.
  6. ToolRegistry integration and auto-discovery.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.skills import Skill, SkillsLoader, get_skills_loader, save_learned_skill
from makima.tools import ToolRegistry, get_registry, reset_registry


# ---------------------------------------------------------------------------
# Test 1: Frontmatter Parsing & Skill Serialization
# ---------------------------------------------------------------------------

def test_frontmatter_parsing_and_model():
    print("\n[TEST 1] Testing YAML frontmatter parsing and Skill model serialization...")

    loader = SkillsLoader()

    # 1. Standard YAML frontmatter markdown
    sample_md = """---
name: code_review_pro
description: Guidelines for adversarial code review.
tags: [review, security, python]
version: 2.1.0
---

# Code Review Process
1. Inspect callee and callers.
2. Verify dynamic path expansion.
3. Check error handling.
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(sample_md)
        tf_path = Path(tf.name)

    try:
        skill = loader._parse_file(tf_path)
        assert skill is not None
        assert skill.name == "code_review_pro"
        assert skill.description == "Guidelines for adversarial code review."
        assert skill.tags == ["review", "security", "python"]
        assert skill.version == "2.1.0"
        assert "1. Inspect callee and callers." in skill.body

        # Serialization round-trip
        md_text = skill.to_markdown()
        assert "name: code_review_pro" in md_text
        assert "1. Inspect callee and callers." in md_text

        # Prompt entry formatting
        prompt_entry = skill.to_prompt_entry()
        assert "### Skill: code_review_pro" in prompt_entry
        assert "**Tags**: review, security, python" in prompt_entry
    finally:
        tf_path.unlink(missing_ok=True)

    # 2. Markdown without frontmatter (fallback extraction)
    no_front_md = """# Rust Async Patterns
Always use tokio or async-std with bounded channels.
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(no_front_md)
        tf_path = Path(tf.name)

    try:
        skill_fallback = loader._parse_file(tf_path)
        assert skill_fallback is not None
        assert skill_fallback.name == "rust_async_patterns"
        assert "bounded channels" in skill_fallback.body
    finally:
        tf_path.unlink(missing_ok=True)

    print("  [PASS] Frontmatter parsing, fallbacks, and serialization validated.")


# ---------------------------------------------------------------------------
# Test 2: Multi-Directory Skills Loading & Resolution
# ---------------------------------------------------------------------------

def test_directory_scanning():
    print("\n[TEST 2] Testing multi-directory skills scanning and resolution...")

    with tempfile.TemporaryDirectory(prefix="makima_skills_test_") as tmpdir:
        base_dir = Path(tmpdir)

        # 1. Directory-based skill: <name>/SKILL.md
        skill1_dir = base_dir / "git_atomic_commits"
        skill1_dir.mkdir()
        (skill1_dir / "SKILL.md").write_text("""---
name: git_atomic_commits
description: Enforce small, single-purpose git commits.
tags: [git, vcs]
---
Make sure each commit touches one logical unit of change.
""", encoding="utf-8")

        # 2. File-based skill: <name>.md
        (base_dir / "python_clean_code.md").write_text("""---
name: python_clean_code
description: Writing clean, idiomatic modern Python.
tags: [python, standards]
---
Use type hints, descriptive naming, and clean context managers.
""", encoding="utf-8")

        # 3. Nested folder skill: nested/<name>/SKILL.md
        nested_dir = base_dir / "cloud" / "docker_deploy"
        nested_dir.mkdir(parents=True)
        (nested_dir / "SKILL.md").write_text("""---
name: docker_deploy
description: Docker container build and deployment steps.
tags: [docker, devops]
---
Always use multi-stage builds and non-root users.
""", encoding="utf-8")

        loader = SkillsLoader(skills_dir=base_dir)
        skills = loader.load_all()

        assert len(skills) == 3, f"Expected 3 skills, got {len(skills)}"
        assert "git_atomic_commits" in skills
        assert "python_clean_code" in skills
        assert "docker_deploy" in skills

        # Exact and case-insensitive retrieval
        assert loader.get_skill("git_atomic_commits") is not None
        assert loader.get_skill("GIT_ATOMIC_COMMITS") is not None
        assert loader.get_skill("docker_deploy").tags == ["docker", "devops"]

        print(f"  [PASS] Successfully discovered and loaded {len(skills)} skills across all layouts.")


# ---------------------------------------------------------------------------
# Test 3: Search & Tag Filtering
# ---------------------------------------------------------------------------

def test_search_and_filtering():
    print("\n[TEST 3] Testing skill search queries and tag filtering...")

    with tempfile.TemporaryDirectory(prefix="makima_skills_search_") as tmpdir:
        base_dir = Path(tmpdir)

        (base_dir / "skill_a.md").write_text("""---
name: database_migrations
description: Postgres and Alembic database migration guides.
tags: [database, sql, postgres]
---
Always test downward migrations in staging before production.
""", encoding="utf-8")

        (base_dir / "skill_b.md").write_text("""---
name: redis_caching
description: High throughput caching with Redis and Valkey.
tags: [cache, redis, performance]
---
Set explicit TTLs for all cached session keys.
""", encoding="utf-8")

        loader = SkillsLoader(skills_dir=base_dir)

        # 1. Text query match in description
        res_sql = loader.search_skills(query="postgres")
        assert len(res_sql) == 1
        assert res_sql[0].name == "database_migrations"

        # 2. Text query match in body
        res_ttl = loader.search_skills(query="session keys")
        assert len(res_ttl) == 1
        assert res_ttl[0].name == "redis_caching"

        # 3. Tag filtering
        res_perf = loader.search_skills(tags=["performance"])
        assert len(res_perf) == 1
        assert res_perf[0].name == "redis_caching"

        # 4. Combined query and tag
        res_combined = loader.search_skills(query="redis", tags=["cache"])
        assert len(res_combined) == 1

        # 5. Non-matching query
        res_empty = loader.search_skills(query="nonexistent_framework")
        assert len(res_empty) == 0

        print("  [PASS] Search by name/body/description and tag filtering operational.")


# ---------------------------------------------------------------------------
# Test 4: System Prompt Section Generation
# ---------------------------------------------------------------------------

def test_system_prompt_generation():
    print("\n[TEST 4] Testing system prompt section synthesis...")

    with tempfile.TemporaryDirectory(prefix="makima_skills_prompt_") as tmpdir:
        base_dir = Path(tmpdir)

        (base_dir / "skill_prompt_1.md").write_text("""---
name: security_auditing
description: Security verification guidelines.
tags: [security]
---
Verify zero hardcoded credentials.
""", encoding="utf-8")

        (base_dir / "skill_prompt_2.md").write_text("""---
name: testing_strategy
description: Testing guidelines.
tags: [testing]
---
Ensure Callee + All Callers Mandate.
""", encoding="utf-8")

        loader = SkillsLoader(skills_dir=base_dir)
        prompt_sec = loader.build_system_prompt_section()

        assert "## Active Learned Skills" in prompt_sec
        assert "### Skill: security_auditing" in prompt_sec
        assert "### Skill: testing_strategy" in prompt_sec
        assert "Verify zero hardcoded credentials." in prompt_sec

        # Budgeted character/token capping test
        capped_sec = loader.build_system_prompt_section(max_tokens_estimate=15)
        # Should fit at most the first entry or empty
        assert len(capped_sec) < len(prompt_sec)

        print("  [PASS] System prompt section synthesized cleanly with budget constraints.")


# ---------------------------------------------------------------------------
# Test 5: Dynamic @tool save_learned_skill Execution & Live Reload
# ---------------------------------------------------------------------------

async def test_save_learned_skill_tool():
    print("\n[TEST 5] Testing @tool save_learned_skill execution and live reloading...")

    with tempfile.TemporaryDirectory(prefix="makima_skills_tool_") as tmpdir:
        base_dir = Path(tmpdir)

        # Initialize global loader pointed to temp directory
        loader = get_skills_loader(skills_dir=base_dir, reset=True)
        assert len(loader.load_all()) == 0

        # Discover skills tools in isolated ToolRegistry
        reg = ToolRegistry(name="test_skills_reg")
        count = reg.discover("makima.skills")
        assert "save_learned_skill" in reg

        # 1. Invalid skill name rejection
        invalid_res = await reg.execute("save_learned_skill", {
            "name": "Invalid Name with Spaces!!",
            "description": "desc",
            "instructions": "steps",
        })
        assert invalid_res["success"] is False
        assert "Invalid skill name" in invalid_res["error"]

        # 2. Valid skill synthesis
        valid_res = await reg.execute("save_learned_skill", {
            "name": "circuit_breaker_recovery",
            "description": "Procedure for half-open circuit breaker probing.",
            "instructions": "1. Wait for cooldown jitter.\n2. Dispatch probe request.\n3. Close breaker on 200 OK.",
            "tags": ["network", "resilience"],
        })
        assert valid_res["success"] is True
        saved_path = Path(valid_res["path"])
        assert saved_path.exists()
        assert saved_path.name == "SKILL.md"
        assert saved_path.parent.name == "circuit_breaker_recovery"

        # 3. Verify loader cache is reloaded and skill is immediately searchable
        reloaded_skill = loader.get_skill("circuit_breaker_recovery")
        assert reloaded_skill is not None
        assert reloaded_skill.name == "circuit_breaker_recovery"
        assert reloaded_skill.tags == ["network", "resilience"]
        assert "Wait for cooldown jitter." in reloaded_skill.body

        print(f"  [PASS] Synthesized skill written to {saved_path} and instantly queryable in cache.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 70)
    print("MAKIMA v2 — STEP 11: DYNAMIC MARKDOWN SKILLS ENGINE VERIFICATION")
    print("=" * 70)

    test_frontmatter_parsing_and_model()
    test_directory_scanning()
    test_search_and_filtering()
    test_system_prompt_generation()
    await test_save_learned_skill_tool()

    print("\n" + "=" * 70)
    print("ALL DYNAMIC SKILLS ENGINE TESTS PASSED (EXIT CODE 0)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
