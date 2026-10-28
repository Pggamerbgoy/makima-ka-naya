"""
Tests the native desktop launcher module.
"""

from makima.desktop.launcher import _find_edge_executable, _is_port_in_use


def test_desktop_launcher_port_check():
    # Test unallocated high port
    assert not _is_port_in_use("127.0.0.1", 59871)


def test_edge_executable_resolution():
    exe = _find_edge_executable()
    # On Windows, Edge is expected to be found
    if exe is not None:
        assert exe.exists()
        assert exe.name.lower() in ("msedge.exe", "msedge")
