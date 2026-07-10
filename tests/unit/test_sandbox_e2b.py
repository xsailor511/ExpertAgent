from __future__ import annotations

import pytest

from coding_agent.sandbox.e2b import HAS_E2B, E2BSandbox


def test_e2b_import_check():
    """E2B may or may not be installed, but the import should not crash."""
    assert isinstance(HAS_E2B, bool)


def test_e2b_init_without_sdk():
    """If E2B isn't installed, init should raise ImportError."""
    if not HAS_E2B:
        with pytest.raises(ImportError):
            E2BSandbox()
    else:
        sbx = E2BSandbox()
        assert sbx._sandbox is None
        assert sbx.api_key is None
