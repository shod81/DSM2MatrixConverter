"""Tests for MSI ProductCode GUID extraction, resolution, and uninstall synthesis."""

from pathlib import Path

from dsm2emp.emitter import emit
from dsm2emp.parser.ir import IrCommand, IrLiteral, IrPackage, IrScript, SourceRef
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.model import RuleSet
from dsm2emp.rules.msi import (
    extract_product_code_from_msi,
    is_valid_guid,
    resolve_msi_guid,
)


def test_is_valid_guid() -> None:
    assert is_valid_guid("{A7AB73A3-CB10-4AA5-9D38-6AEFFBDE4C91}")
    assert is_valid_guid("{12345678-ABCD-1234-ABCD-1234567890AB}")
    assert not is_valid_guid("setup.msi")
    assert not is_valid_guid("{1234}")
    assert not is_valid_guid("")


def test_resolve_msi_guid_direct_guid() -> None:
    guid = "{A7AB73A3-CB10-4AA5-9D38-6AEFFBDE4C91}"
    assert resolve_msi_guid(guid) == guid
    assert resolve_msi_guid(guid.lower()) == guid


def test_resolve_msi_guid_binary_fallback(tmp_path: Path) -> None:
    # Create mock MSI file with embedded ProductCode pattern
    msi_path = tmp_path / "mock_app.msi"
    test_guid = "{12345678-ABCD-1234-ABCD-1234567890AB}"
    msi_content = (
        b"\xd0\xcf\x11\xe0"
        + b"\x00" * 100
        + b"ProductCode\x00\x00"
        + test_guid.encode("ascii")
        + b"\x00" * 50
    )
    msi_path.write_bytes(msi_content)

    extracted = extract_product_code_from_msi(msi_path)
    assert extracted == test_guid

    # Test resolution with package_root
    resolved = resolve_msi_guid("mock_app.msi", package_root=tmp_path)
    assert resolved == test_guid

    # Test resolution with %SRC%\Files\ prefix
    resolved_prefix = resolve_msi_guid(r"%SRC%\Files\mock_app.msi", package_root=tmp_path)
    assert resolved_prefix == test_guid


def test_resolve_msi_guid_fallback_when_not_found(tmp_path: Path) -> None:
    assert resolve_msi_guid("nonexistent.msi", package_root=tmp_path) is None


def test_rule_engine_synthesizes_msi_uninstall_with_guid(tmp_path: Path) -> None:
    """When a real or mock MSI with ProductCode is in package, uninstall should use {GUID}."""
    test_guid = "{99998888-7777-6666-5555-444433332222}"
    msi_file = tmp_path / "setup.msi"
    msi_content = (
        b"\xd0\xcf\x11\xe0"
        + b"\x00" * 50
        + b"ProductCode="
        + test_guid.encode("ascii")
        + b"\x00" * 50
    )
    msi_file.write_bytes(msi_content)

    dummy_src = SourceRef(file=Path("test.inc"), line=1, raw="ExecuteEx(...)")
    script = IrScript(
        file=Path("test.inc"),
        commands=[
            IrCommand(
                kind="ExecuteEx",
                raw_args=[],
                params={"command": IrLiteral(value=r'msiexec.exe /i "%Src%\setup.msi" /qn')},
                src=dummy_src,
            )
        ],
    )
    pkg = IrPackage(name="AppWithMsi", main_script=script, media_files=[msi_file])
    engine = RuleEngine(RuleSet(rules=[]))
    res = engine.transform_package(pkg, package_root=tmp_path)

    inf_text, _ = emit(res.document)
    # Must use extracted GUID for /x call
    assert f"-CallHidden msiexec.exe /x {test_guid} /qn" in inf_text


def test_rule_engine_synthesizes_msi_install_product_with_guid(tmp_path: Path) -> None:
    """MSIInstallProduct should resolve GUID from payload MSI file on uninstall."""
    test_guid = "{AAAA1111-BBBB-2222-CCCC-333344445555}"
    files_dir = tmp_path / "Files"
    files_dir.mkdir(parents=True)
    msi_file = files_dir / "package.msi"
    msi_content = (
        b"\xd0\xcf\x11\xe0"
        + b"\x00" * 50
        + b"ProductCode="
        + test_guid.encode("ascii")
        + b"\x00" * 50
    )
    msi_file.write_bytes(msi_content)

    dummy_src = SourceRef(file=Path("test.inc"), line=1, raw="MSIInstallProduct(...)")
    script = IrScript(
        file=Path("test.inc"),
        commands=[
            IrCommand(
                kind="MSIInstallProduct",
                raw_args=[IrLiteral(value=r".\package.msi")],
                params={},
                src=dummy_src,
            )
        ],
    )
    pkg = IrPackage(name="MsiProdApp", main_script=script, media_files=[msi_file])
    engine = RuleEngine(RuleSet(rules=[]))
    res = engine.transform_package(pkg, package_root=tmp_path)

    inf_text, _ = emit(res.document)
    assert f"-CallHidden MsiExec.exe /X{test_guid} /qn /norestart" in inf_text
