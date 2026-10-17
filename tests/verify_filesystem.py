"""
Live verification script for Phase 2 Step 6: Safe Filesystem & SAGA Rollback.
Comprehensive adversarial testing covering:
  1. Isolated workspace setup & dynamic path overrides.
  2. Safe file writes (new file, parent dir creation, overwrite guard).
  3. Safe file reads (content integrity, non-existent, directory read rejection).
  4. Safe file edits (target matching, replacement, error on non-match).
  5. Directory listing (file/dir types, size, internal .snapshots exclusion, recursive).
  6. Boundary clamping & directory traversal blocking (relative, absolute, root deletion).
  7. SAGA snapshotting & cryptographic SHA256 integrity verification.
  8. SAGA rollbacks (edit rollback, specific snapshot ID, delete rollback, corruption check).
  9. ToolRegistry dynamic execution & schema auto-synthesis.
"""

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import get_registry, reset_registry
from makima.tools.filesystem import (
    BoundaryTraversalError,
    SagaRollbackManager,
    delete_file,
    edit_file,
    get_workspace_dir,
    list_directory,
    read_file,
    resolve_safe_path,
    rollback_file,
    set_workspace_dir,
    write_file,
)


# ---------------------------------------------------------------------------
# Test 1: Dynamic Workspace Resolution & Override
# ---------------------------------------------------------------------------

def test_workspace_resolution(tmp_dir: Path):
    print("\n[TEST 1] Testing dynamic workspace resolution and overrides...")
    orig_ws = get_workspace_dir()
    assert orig_ws is not None

    # Apply override
    set_workspace_dir(tmp_dir)
    assert get_workspace_dir().resolve() == tmp_dir.resolve()

    # Safe path resolution
    resolved = resolve_safe_path("nested/test.txt")
    assert resolved == (tmp_dir / "nested" / "test.txt").resolve()
    assert resolved.is_relative_to(tmp_dir.resolve())

    print("  [PASS] Dynamic workspace resolution and path clamping operational.")


# ---------------------------------------------------------------------------
# Test 2: File Write Operations & Overwrite Protection
# ---------------------------------------------------------------------------

def test_file_write_operations(tmp_dir: Path):
    print("\n[TEST 2] Testing file write operations and overwrite protection...")

    # 1. Write new file with auto parent dir creation
    res1 = write_file("docs/notes.txt", "Initial documentation content.\nLine 2.")
    assert "notes.txt" in res1
    target = tmp_dir / "docs" / "notes.txt"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "Initial documentation content.\nLine 2."

    # 2. Overwrite attempt without overwrite=True must raise FileExistsError
    try:
        write_file("docs/notes.txt", "New illegal content", overwrite=False)
        assert False, "Expected FileExistsError when overwrite=False"
    except FileExistsError as e:
        assert "already exists" in str(e)

    # Content must remain unchanged
    assert target.read_text(encoding="utf-8") == "Initial documentation content.\nLine 2."

    # 3. Overwrite with overwrite=True must succeed
    res2 = write_file("docs/notes.txt", "Replaced documentation content.", overwrite=True)
    assert "overwrote" in res2.lower()
    assert target.read_text(encoding="utf-8") == "Replaced documentation content."

    # 4. Attempting to write over an existing directory must raise IsADirectoryError
    try:
        write_file("docs", "Writing to dir", overwrite=True)
        assert False, "Expected IsADirectoryError when writing over directory"
    except IsADirectoryError:
        pass

    print("  [PASS] File writes, parent dir synthesis, and overwrite guards functioning.")


# ---------------------------------------------------------------------------
# Test 3: File Read Operations
# ---------------------------------------------------------------------------

def test_file_read_operations(tmp_dir: Path):
    print("\n[TEST 3] Testing file read operations...")

    # 1. Read existing file
    content = read_file("docs/notes.txt")
    assert content == "Replaced documentation content."

    # 2. Non-existent file raises FileNotFoundError
    try:
        read_file("nonexistent.txt")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError as e:
        assert "nonexistent.txt" in str(e)

    # 3. Reading a directory raises IsADirectoryError
    try:
        read_file("docs")
        assert False, "Expected IsADirectoryError when reading directory"
    except IsADirectoryError:
        pass

    print("  [PASS] File read validation and error handling confirmed.")


# ---------------------------------------------------------------------------
# Test 4: File Edit Operations
# ---------------------------------------------------------------------------

def test_file_edit_operations(tmp_dir: Path):
    print("\n[TEST 4] Testing file edit operations...")

    # Write target file
    write_file("config.cfg", "timeout=30\nmode=dev\ntimeout=30\n", overwrite=True)

    # 1. Edit single occurrence (replace_all=False)
    edit_res = edit_file("config.cfg", "mode=dev", "mode=production")
    assert "Successfully edited" in edit_res
    content = read_file("config.cfg")
    assert "mode=production" in content
    assert "mode=dev" not in content

    # 2. Target text not found raises ValueError
    try:
        edit_file("config.cfg", "nonexistent_key=true", "bar")
        assert False, "Expected ValueError when target text is missing"
    except ValueError as e:
        assert "not found" in str(e).lower()

    # 3. Edit with replace_all=True replaces all instances
    edit_all_res = edit_file("config.cfg", "timeout=30", "timeout=60", replace_all=True)
    assert "replaced 2 of 2" in edit_all_res
    content_all = read_file("config.cfg")
    assert content_all.count("timeout=60") == 2
    assert "timeout=30" not in content_all

    print("  [PASS] Exact text replacement and replace_all options verified.")


# ---------------------------------------------------------------------------
# Test 5: Directory Listing Operations
# ---------------------------------------------------------------------------

def test_directory_listing_operations(tmp_dir: Path):
    print("\n[TEST 5] Testing directory listing operations...")

    # Create additional files and subdirectories
    write_file("src/app.py", "print('hello')", overwrite=True)
    write_file("README.md", "# Test Workspace", overwrite=True)

    # 1. List workspace root
    items = list_directory(".")
    names = [item["name"] for item in items]
    assert "README.md" in names
    assert "docs" in names
    assert "src" in names
    assert "config.cfg" in names

    # Internal .snapshots directory must be hidden
    assert ".snapshots" not in names

    # Check directory type metadata
    docs_entry = next(i for i in items if i["name"] == "docs")
    assert docs_entry["type"] == "directory"
    assert docs_entry["size_bytes"] == 0

    readme_entry = next(i for i in items if i["name"] == "README.md")
    assert readme_entry["type"] == "file"
    assert readme_entry["size_bytes"] > 0
    assert "modified_at" in readme_entry

    # 2. List subfolder
    sub_items = list_directory("docs")
    sub_names = [i["name"] for i in sub_items]
    assert "notes.txt" in sub_names

    # 3. Recursive listing
    rec_items = list_directory(".", recursive=True)
    rec_paths = [i["path"] for i in rec_items]
    assert any("docs/notes.txt" in p.replace("\\", "/") for p in rec_paths)
    assert any("src/app.py" in p.replace("\\", "/") for p in rec_paths)

    # 4. Error cases
    try:
        list_directory("missing_folder")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass

    try:
        list_directory("README.md")
        assert False, "Expected NotADirectoryError"
    except NotADirectoryError:
        pass

    print("  [PASS] Directory listing, recursive discovery, and metadata verified.")


# ---------------------------------------------------------------------------
# Test 6: Adversarial Boundary Clamping & Directory Traversal Blocking
# ---------------------------------------------------------------------------

def test_boundary_traversal_blocking(tmp_dir: Path):
    print("\n[TEST 6] Testing adversarial boundary clamping & traversal blocking...")

    outside_targets = [
        "../outside.txt",
        "../../outside.txt",
        "../../../system32/calc.exe",
        "docs/../../outside.txt",
        "nested/../../../../etc/passwd",
        os.path.abspath(str(tmp_dir.parent / "escape.txt")),
    ]

    for bad_path in outside_targets:
        # Read attempt
        try:
            read_file(bad_path)
            assert False, f"Boundary traversal read bypassed for '{bad_path}'!"
        except (BoundaryTraversalError, PermissionError) as e:
            assert "Security Boundary Violation" in str(e) or "outside" in str(e)

        # Write attempt
        try:
            write_file(bad_path, "evil payload", overwrite=True)
            assert False, f"Boundary traversal write bypassed for '{bad_path}'!"
        except (BoundaryTraversalError, PermissionError) as e:
            assert "Security Boundary Violation" in str(e) or "outside" in str(e)

        # Edit attempt
        try:
            edit_file(bad_path, "a", "b")
            assert False, f"Boundary traversal edit bypassed for '{bad_path}'!"
        except (BoundaryTraversalError, PermissionError) as e:
            assert "Security Boundary Violation" in str(e) or "outside" in str(e)

        # Delete attempt
        try:
            delete_file(bad_path)
            assert False, f"Boundary traversal delete bypassed for '{bad_path}'!"
        except (BoundaryTraversalError, PermissionError) as e:
            assert "Security Boundary Violation" in str(e) or "outside" in str(e)

        # List attempt
        try:
            list_directory(bad_path)
            assert False, f"Boundary traversal list bypassed for '{bad_path}'!"
        except (BoundaryTraversalError, PermissionError) as e:
            assert "Security Boundary Violation" in str(e) or "outside" in str(e)

    # Traversal test on workspace root deletion
    try:
        delete_file(".")
        assert False, "Deleting workspace root was not blocked!"
    except BoundaryTraversalError:
        pass

    print("  [PASS] All directory traversal and boundary escape vectors strictly blocked.")


# ---------------------------------------------------------------------------
# Test 7: SAGA Snapshotting & Checksum Integrity
# ---------------------------------------------------------------------------

def test_saga_snapshotting(tmp_dir: Path):
    print("\n[TEST 7] Testing SAGA snapshotting and SHA256 integrity...")
    manager = SagaRollbackManager.get_instance()

    # Snapshots should have been taken by previous writes and edits
    snapshots = manager.list_snapshots()
    assert len(snapshots) > 0, "Expected snapshots in .snapshots directory"

    # Verify snapshot properties
    snap_dir = tmp_dir / ".snapshots"
    assert snap_dir.is_dir()

    for s in snapshots:
        assert s.snapshot_id is not None
        assert s.file_path is not None
        assert s.timestamp > 0
        assert s.iso_time is not None

        meta_json = snap_dir / f"{s.snapshot_id}.json"
        assert meta_json.is_file(), f"Missing metadata file for {s.snapshot_id}"

        if s.file_existed:
            assert len(s.sha256) == 64  # Valid SHA256 hex string
            snap_file = snap_dir / f"{s.snapshot_id}.snap"
            assert snap_file.is_file(), f"Missing payload file for {s.snapshot_id}"

            # Verify checksum matches disk payload exactly
            data = snap_file.read_bytes()
            assert hashlib.sha256(data).hexdigest() == s.sha256

    print(f"  [PASS] Verified {len(snapshots)} SAGA snapshots with exact SHA256 integrity.")


# ---------------------------------------------------------------------------
# Test 8: SAGA Rollback Operations
# ---------------------------------------------------------------------------

def test_saga_rollback_operations(tmp_dir: Path):
    print("\n[TEST 8] Testing SAGA rollback operations...")

    # 1. Rollback an edit
    test_file = "service.py"
    write_file(test_file, "def start():\n    return 'v1'\n", overwrite=True)
    v1_content = read_file(test_file)

    # Perform edit
    edit_file(test_file, "'v1'", "'v2_modified'")
    assert "v2_modified" in read_file(test_file)

    # Rollback latest change
    roll_res = rollback_file(test_file)
    assert "Successfully rolled back" in roll_res
    assert read_file(test_file) == v1_content
    assert hashlib.sha256(v1_content.encode("utf-8")).hexdigest() in roll_res

    # 2. Multi-step edits and rollback to specific snapshot ID
    manager = SagaRollbackManager.get_instance()
    write_file("pipeline.yaml", "step: init\n", overwrite=True)
    edit_file("pipeline.yaml", "step: init", "step: process")
    snap_before_step1 = manager.list_snapshots("pipeline.yaml")[0].snapshot_id

    edit_file("pipeline.yaml", "step: process", "step: finalize")
    assert "step: finalize" in read_file("pipeline.yaml")

    # Roll back to latest snapshot (pre-finalize -> "step: process")
    rollback_file("pipeline.yaml")
    assert "step: process" in read_file("pipeline.yaml")

    # Roll back specifically to snap_before_step1 (which recorded "step: init")
    rollback_file("pipeline.yaml", snapshot_id=snap_before_step1)
    assert "step: init" in read_file("pipeline.yaml")

    # 3. Rollback a deleted file
    ephemeral = "ephemeral.txt"
    ephemeral_data = "Crucial business secret that must be recovered"
    write_file(ephemeral, ephemeral_data, overwrite=True)

    del_res = delete_file(ephemeral)
    assert "Successfully deleted" in del_res
    assert not (tmp_dir / ephemeral).exists()

    # Rollback deletion
    roll_del_res = rollback_file(ephemeral)
    assert "Successfully rolled back" in roll_del_res
    assert (tmp_dir / ephemeral).is_file()
    assert read_file(ephemeral) == ephemeral_data

    # 4. Snapshot data tampering detection
    corrupt_file = "tamper_target.txt"
    write_file(corrupt_file, "Original untouched content", overwrite=True)
    edit_file(corrupt_file, "Original", "Modified")

    latest_snap = manager.list_snapshots(corrupt_file)[0]
    snap_payload = tmp_dir / ".snapshots" / f"{latest_snap.snapshot_id}.snap"
    assert snap_payload.is_file()

    # Corrupt payload byte
    snap_payload.write_bytes(b"TAMPERED_BYTE_CORRUPTION")

    try:
        rollback_file(corrupt_file, snapshot_id=latest_snap.snapshot_id)
        assert False, "Rollback should fail when snapshot payload SHA256 is tampered with!"
    except ValueError as e:
        assert "integrity failure" in str(e).lower() or "checksum mismatch" in str(e).lower()

    print("  [PASS] SAGA edit rollbacks, target snapshot IDs, delete recovery, and tamper checks verified.")


# ---------------------------------------------------------------------------
# Test 9: ToolRegistry Integration & Schema Synthesis
# ---------------------------------------------------------------------------

async def test_registry_integration(tmp_dir: Path):
    print("\n[TEST 9] Testing ToolRegistry integration and dynamic schema synthesis...")
    reg = get_registry()

    fs_tools = ["read_file", "write_file", "edit_file", "delete_file", "list_directory", "rollback_file"]
    for t_name in fs_tools:
        assert t_name in reg, f"Tool '{t_name}' not found in registry!"
        tool_obj = reg[t_name]

        # Verify OpenAI schema generation
        schema = tool_obj.to_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == t_name
        assert len(fn["description"]) > 0
        assert "parameters" in fn
        assert "properties" in fn["parameters"]

        # Verify Gemini declaration generation
        gemini_schema = tool_obj.to_schema(format="gemini")
        assert gemini_schema["name"] == t_name
        assert "parameters" in gemini_schema
        assert gemini_schema == tool_obj.to_gemini_dict()

    # Execute tool via registry
    dyn_write = await reg.execute("write_file", {
        "path": "registry_test.txt",
        "content": "Executed via ToolRegistry engine!",
        "overwrite": True,
    })
    assert "Successfully" in dyn_write

    dyn_read = await reg.execute("read_file", {
        "path": "registry_test.txt",
    })
    assert dyn_read == "Executed via ToolRegistry engine!"

    print("  [PASS] All 6 filesystem tools fully integrated with ToolRegistry execution and schemas.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 6: SAFE FILESYSTEM & SAGA ROLLBACK TEST SUITE")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        tmp_dir = Path(temp_dir_str).resolve()
        try:
            test_workspace_resolution(tmp_dir)
            test_file_write_operations(tmp_dir)
            test_file_read_operations(tmp_dir)
            test_file_edit_operations(tmp_dir)
            test_directory_listing_operations(tmp_dir)
            test_boundary_traversal_blocking(tmp_dir)
            test_saga_snapshotting(tmp_dir)
            test_saga_rollback_operations(tmp_dir)
            await test_registry_integration(tmp_dir)
        finally:
            set_workspace_dir(None)
            SagaRollbackManager.reset_instance()

    print("\n" + "=" * 75)
    print("ALL FILESYSTEM & SAGA ROLLBACK TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
