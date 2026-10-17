"""
tests/verify_vector_search.py — Step 10.3 Verification
Tests VectorSearchEngine: fastembed + sqlite-vec on-device semantic search.
All tests run in ':memory:' mode — zero disk writes.
"""

import asyncio
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(coro):
    return asyncio.run(coro)


PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"{tag} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(ok)


# ---------------------------------------------------------------------------
# Suite 1: Import & instantiation
# ---------------------------------------------------------------------------
def test_import():
    try:
        from makima.memory.vector_search import VectorSearchEngine
        record("Import VectorSearchEngine", True)
        return VectorSearchEngine
    except Exception as e:
        record("Import VectorSearchEngine", False, str(e))
        return None


# ---------------------------------------------------------------------------
# Suite 2: Package-level export
# ---------------------------------------------------------------------------
def test_package_export():
    try:
        from makima.memory import VectorSearchEngine  # noqa: F401
        record("VectorSearchEngine exported from makima.memory", True)
    except Exception as e:
        record("VectorSearchEngine exported from makima.memory", False, str(e))


# ---------------------------------------------------------------------------
# Suite 3: Connect + document_count = 0 on empty store
# ---------------------------------------------------------------------------
def test_connect_empty(VectorSearchEngine):
    async def _run():
        try:
            engine = VectorSearchEngine(db_path=":memory:")
            await engine.connect()
            count = await engine.document_count()
            await engine.close()
            record("Connect and empty count=0", count == 0, f"count={count}")
        except Exception as e:
            record("Connect and empty count=0", False, str(e))

    run(_run())


# ---------------------------------------------------------------------------
# Suite 4: add_document + document_count
# ---------------------------------------------------------------------------
def test_add_document(VectorSearchEngine):
    async def _run():
        try:
            engine = VectorSearchEngine(db_path=":memory:")
            await engine.connect()
            await engine.add_document("doc:1", "Python async event loop coroutines")
            await engine.add_document("doc:2", "Machine learning gradient descent optimizer")
            await engine.add_document("doc:3", "Windows registry HKEY_LOCAL_MACHINE")
            count = await engine.document_count()
            await engine.close()
            record("add_document stores 3 docs", count == 3, f"count={count}")
        except Exception as e:
            record("add_document stores 3 docs", False, str(e))

    run(_run())


# ---------------------------------------------------------------------------
# Suite 5: Semantic search returns relevant results
# ---------------------------------------------------------------------------
def test_semantic_search(VectorSearchEngine):
    async def _run():
        try:
            engine = VectorSearchEngine(db_path=":memory:")
            await engine.connect()
            await engine.add_document("doc:python", "Python programming language asyncio event loop")
            await engine.add_document("doc:food", "Biryani rice chicken spices Indian cuisine")
            await engine.add_document("doc:ml", "Neural network deep learning backpropagation")

            results = await engine.search("async python coroutines", top_k=2)
            await engine.close()

            # Top result should be Python-related, not food
            ok = len(results) > 0 and "python" in results[0]["doc_id"]
            record(
                "Semantic search returns relevant doc first",
                ok,
                f"top={results[0]['doc_id'] if results else 'NONE'}, score={results[0]['score'] if results else 0}",
            )
        except Exception as e:
            record("Semantic search returns relevant doc first", False, str(e))

    run(_run())


# ---------------------------------------------------------------------------
# Suite 6: delete_document
# ---------------------------------------------------------------------------
def test_delete_document(VectorSearchEngine):
    async def _run():
        try:
            engine = VectorSearchEngine(db_path=":memory:")
            await engine.connect()
            await engine.add_document("doc:temp", "Temporary test document for deletion")
            count_before = await engine.document_count()
            deleted = await engine.delete_document("doc:temp")
            count_after = await engine.document_count()
            await engine.close()
            ok = deleted and count_before == 1 and count_after == 0
            record("delete_document removes doc", ok, f"before={count_before}, after={count_after}")
        except Exception as e:
            record("delete_document removes doc", False, str(e))

    run(_run())


# ---------------------------------------------------------------------------
# Suite 7: Context manager support
# ---------------------------------------------------------------------------
def test_context_manager(VectorSearchEngine):
    async def _run():
        try:
            async with VectorSearchEngine(db_path=":memory:") as engine:
                await engine.add_document("ctx:1", "Context manager test document")
                count = await engine.document_count()
            record("Context manager (__aenter__/__aexit__)", count == 1, f"count={count}")
        except Exception as e:
            record("Context manager (__aenter__/__aexit__)", False, str(e))

    run(_run())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Step 10.3 — VectorSearchEngine Verification")
    print("=" * 60)

    VSE = test_import()
    test_package_export()

    if VSE is None:
        print("\n[ABORT] Cannot import VectorSearchEngine — skipping remaining tests.")
        sys.exit(1)

    test_connect_empty(VSE)
    test_add_document(VSE)
    test_semantic_search(VSE)
    test_delete_document(VSE)
    test_context_manager(VSE)

    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
