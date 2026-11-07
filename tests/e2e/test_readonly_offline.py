"""Quellschutz and Offline verification tests (Task T-101 / AK-7 / FR-001 / NFR-001).

Covers:
1. FR-001 (Quellschutz): Source package directory is strictly read-only; SHA-256 tree hash
   before and after migration must match identically. Works even on read-only filesystems.
2. NFR-001 / AK-7 (Offline Guarantee): Default migration works completely offline with
   all network socket connections blocked.
3. FR-052 / Graceful Degradation: If AI is enabled but network fails, migration degrades
   cleanly to rule-based output with TODOs without crashing.
"""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dsm2emp.ai.config import AiConfig
from dsm2emp.ai.pipeline import AiPipeline
from dsm2emp.ai.provider import LlmProvider
from dsm2emp.fixtures.make_packages import (
    create_p01_pure_msi,
    create_p02_exe_params,
    create_p08_dsm_infrastr,
)
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.scanner.scanner import calculate_tree_hash


def set_tree_readonly(root: Path, readonly: bool = True) -> None:
    """Toggle read-only file permissions on an entire directory tree."""
    for path in root.rglob("*"):
        if path.is_file():
            if readonly:
                os.chmod(path, stat.S_IREAD)
            else:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_quellschutz_tree_hash_invariant(tmp_path: Path) -> None:
    """FR-001: SHA-256 tree hash before and after migration must be identical."""
    src = create_p02_exe_params(tmp_path / "dsm_source")
    tgt = tmp_path / "emp_target"

    hash_before = calculate_tree_hash(src)
    assert len(hash_before) == 64

    res = migrate_single(
        src,
        tgt,
        MigrationOptions(product_name="ComplexApp", version="2.0", force=True),
    )

    assert res.success is True
    assert (tgt / "Install" / "Setup.inf").exists()

    hash_after = calculate_tree_hash(src)
    assert hash_after == hash_before, "FR-001 violation: Source directory was modified!"


def test_quellschutz_readonly_filesystem(tmp_path: Path) -> None:
    """FR-001: Migration succeeds completely even if source files are write-protected."""
    src = create_p01_pure_msi(tmp_path / "dsm_source_ro")
    tgt = tmp_path / "emp_target_ro"

    hash_before = calculate_tree_hash(src)

    # Make every source file strictly read-only
    set_tree_readonly(src, readonly=True)

    try:
        res = migrate_single(
            src,
            tgt,
            MigrationOptions(product_name="MsiApp", version="1.0", force=True),
        )
        assert res.success is True
        assert (tgt / "Install" / "Setup.inf").exists()

        hash_after = calculate_tree_hash(src)
        assert hash_after == hash_before
    finally:
        # Restore write permissions so pytest can clean up tmp_path
        set_tree_readonly(src, readonly=False)


def test_offline_mode_blocks_network_completely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-001 / AK-7: Migration works with zero network access and blocked sockets."""
    src = create_p01_pure_msi(tmp_path / "dsm_offline")
    tgt = tmp_path / "emp_offline"

    # Monkeypatch socket.socket.connect to fail immediately if network is touched
    def forbidden_connect(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "AK-7 Violation: Network socket connection attempted during offline run!"
        )

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    # Standard offline run (ai_enabled=False by default)
    opts = MigrationOptions(product_name="OfflinePkg", version="1.0")
    assert opts.ai_enabled is False

    res = migrate_single(src, tgt, opts)
    assert res.success is True
    assert res.exit_code in (0, 1)
    assert (tgt / "Install" / "Setup.inf").exists()


def test_ai_network_failure_graceful_degradation(tmp_path: Path) -> None:
    """FR-052 / Graceful Degradation: Provider network error degrades cleanly."""
    src = create_p08_dsm_infrastr(tmp_path / "dsm_ai_fail")
    tgt = tmp_path / "emp_ai_fail"

    mock_provider = MagicMock(spec=LlmProvider)
    # Simulate network failure (e.g. connection refused / timeout / DNS failure)
    mock_provider.complete.side_effect = ConnectionError("Could not reach LLM endpoint")

    pipeline = AiPipeline(
        provider=mock_provider,
        config=AiConfig(enabled=True),
        cache_dir=tmp_path / "ai_cache",
    )

    opts = MigrationOptions(
        product_name="AiDegradeApp",
        version="1.0",
        ai_enabled=True,
        ai_pipeline=pipeline,
    )

    # Migration must NOT crash with ConnectionError
    res = migrate_single(src, tgt, opts)
    assert res.success is True
    assert (tgt / "Install" / "Setup.inf").exists()

    # Todos were safely retained
    assert res.transform_result is not None
    assert len(res.transform_result.todos) > 0
