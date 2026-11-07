"""End-to-end and regression test for the NetApp BFS workaround on Windows 11 24H2.

Slow file copy speeds on Windows 11 24H2: set the BFS driver Start value
conditionally and revert it on uninstall.

Verifies:
1. Parsing of RegModifyDWord and RegValue within If conditions.
2. 100% confidence (no unresolved TODOs).
3. Correct conditional registry modification via CallHidden reg.exe add in branch sections.
4. Correct uninstallation via -CallHidden reg.exe add reverting Start back to 2.
5. Quellschutz invariant (SHA-256 tree hash before and after migration).
6. Offline guarantee (AK-7: no socket connections).
7. Zero errors from the Empirum Setup.inf validator.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import pytest

from dsm2emp.emitter.render import emit
from dsm2emp.orchestrator import MigrationOptions, migrate_single
from dsm2emp.parser.escript.parser import parse_script
from dsm2emp.parser.ir import IrPackage
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.loader import load_rules
from dsm2emp.scanner.scanner import calculate_tree_hash
from dsm2emp.validator.rules import validate_text

REAL_PACKAGE_ENV = "DSM2EMP_REAL_PACKAGE"
_real_package = os.environ.get(REAL_PACKAGE_ENV)
REAL_PACKAGE: Path | None = Path(_real_package) if _real_package else None
skip_if_no_real_package = pytest.mark.skipif(
    REAL_PACKAGE is None or not REAL_PACKAGE.exists(),
    reason=f"Set {REAL_PACKAGE_ENV} to a DSM package directory to run this test",
)

FIX_LOADING_SPEED_SCRIPT = """!Knowledge Base Artikel von NetApp zu dem Problem
!https://kb.netapp.com/on-prem/ontap/da/NAS/NAS-KBs/Slow_file_copy_speeds_seen_on_Windows_11_24H2
If not CheckInstallMode(imUninstall)
 If CheckInstallMode(imWkStaPart)
  If RegValue('HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start',)='2'
   RegModifyDWord('HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start','4',mrdwSet)/TS
!
: $BeginUninstallScript
RegModifyDWord('HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start','2',mrdwSet)/TS
"""


def test_netapp_bfs_workaround_inline_logic(tmp_path: Path) -> None:
    """Validate transform logic and emitter output for the BFS workaround script."""
    script_file = tmp_path / "Script.inc"
    script_file.write_text(FIX_LOADING_SPEED_SCRIPT, encoding="utf-8")
    script = parse_script(FIX_LOADING_SPEED_SCRIPT, script_file)

    engine = RuleEngine(load_rules())
    result = engine.transform_package(IrPackage(name="NetAppBfsWorkaround", main_script=script))

    assert result.todo_count == 0, f"Expected 0 TODOs, got {result.todo_count}"
    assert result.average_confidence == 1.0, (
        f"Expected 1.0 confidence, got {result.average_confidence}"
    )

    inf_text, _ = emit(result.document)

    # Validate condition translation
    assert (
        'If "%HKLM,SYSTEM\\CurrentControlSet\\Services\\bfs,Start%" == "2" Then "Set:Then_1" EndIf'
        in inf_text
    )

    # Validate conditional installation in branch
    assert "[Set:Then_1]" in inf_text
    assert (
        'CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 4 /f" in inf_text
    )

    # Validate uninstallation in [Set:Deinstallation]
    assert "[Set:Deinstallation]" in inf_text
    assert (
        '-CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 2 /f" in inf_text
    )

    # Validate Setup.inf syntax
    issues = validate_text(inf_text)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Setup.inf validator reported errors: {errors}"


def test_netapp_bfs_workaround_synthetic_package_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2E migration test for the BFS workaround with source protection and offline guarantee."""
    source_dir = tmp_path / "dsm_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "Script.inc").write_bytes(FIX_LOADING_SPEED_SCRIPT.encode("cp1252"))
    (source_dir / "Package.ini").write_text(
        "[Package]\nName=Fix LoadingSpeed in 24H2\nVersion=1.0\nManufacturer=Microsoft\n",
        encoding="utf-8",
    )

    target_dir = tmp_path / "emp_target"

    # 1. Quellschutz: tree hash before
    hash_before = calculate_tree_hash(source_dir)
    assert len(hash_before) == 64

    # 2. Offline guarantee: block network socket connections
    def forbidden_connect(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("AK-7 Violation: Network connection attempted during offline run!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    # 3. Perform migration
    opts = MigrationOptions(force=True)
    res = migrate_single(source_dir, target_dir, opts)

    # 4. Result assertions
    assert res.success is True, f"Migration failed: {res.error_message}"
    assert res.exit_code == 0, f"Expected exit code 0, got {res.exit_code}"
    assert res.transform_result is not None
    assert res.transform_result.average_confidence == 1.0
    assert res.transform_result.todo_count == 0

    # 5. Quellschutz: tree hash unchanged
    hash_after = calculate_tree_hash(source_dir)
    assert hash_after == hash_before, "FR-001 violation: Source directory was modified!"

    # 6. Verify target Setup.inf
    setup_inf = target_dir / "Install" / "Setup.inf"
    assert setup_inf.exists(), "Setup.inf missing in target"
    inf_text = setup_inf.read_text(encoding="cp1252")

    assert (
        'If "%HKLM,SYSTEM\\CurrentControlSet\\Services\\bfs,Start%" == "2" Then "Set:Then_1" EndIf'
        in inf_text
    )
    assert (
        'CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 4 /f" in inf_text
    )
    assert (
        '-CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 2 /f" in inf_text
    )

    # 7. Validator check
    issues = validate_text(inf_text)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Setup.inf validator reported errors: {errors}"


@skip_if_no_real_package
def test_netapp_bfs_workaround_real_package_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2E migration of a real DSM package supplied via DSM2EMP_REAL_PACKAGE."""
    target_dir = tmp_path / "emp_fix_loadingspeed_target"

    # 1. Quellschutz: tree hash before
    assert REAL_PACKAGE is not None
    hash_before = calculate_tree_hash(REAL_PACKAGE)
    assert len(hash_before) == 64

    # 2. Offline guarantee: block network socket connections
    def forbidden_connect(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("AK-7 Violation: Network connection attempted during offline run!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    # 3. Perform migration
    opts = MigrationOptions(force=True)
    res = migrate_single(REAL_PACKAGE, target_dir, opts)

    # 4. Result assertions
    assert res.success is True, f"Migration failed: {res.error_message}"
    assert res.exit_code == 0, f"Expected exit code 0, got {res.exit_code}"
    assert res.transform_result is not None
    assert res.transform_result.average_confidence == 1.0
    assert res.transform_result.todo_count == 0

    # 5. Quellschutz: tree hash unchanged
    hash_after = calculate_tree_hash(REAL_PACKAGE)
    assert hash_after == hash_before, "FR-001 violation: Source directory was modified!"

    # 6. Verify target Setup.inf
    setup_inf = target_dir / "Install" / "Setup.inf"
    assert setup_inf.exists(), "Setup.inf missing in target"
    inf_text = setup_inf.read_text(encoding="cp1252")

    assert (
        'If "%HKLM,SYSTEM\\CurrentControlSet\\Services\\bfs,Start%" == "2" Then "Set:Then_1" EndIf'
        in inf_text
    )
    assert (
        'CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 4 /f" in inf_text
    )
    assert (
        '-CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" '
        "/v Start /t REG_DWORD /d 2 /f" in inf_text
    )

    # 7. Validator check
    issues = validate_text(inf_text)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Setup.inf validator reported errors: {errors}"
