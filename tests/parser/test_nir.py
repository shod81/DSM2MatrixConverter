"""Unit tests for NIR and REG registry file parser (Task T-022)."""

from pathlib import Path

from dsm2emp.parser.ir import IrCompositeValue, IrVarRef
from dsm2emp.parser.nir import parse_nir
from tests.fixtures.make_packages import create_p04_registry


def test_parse_nir_p04_registry(tmp_path: Path) -> None:
    """Test parsing setup.nir from P-04 fixture."""
    pkg = create_p04_registry(tmp_path)
    nir_path = pkg / "setup.nir"
    keys = parse_nir(nir_path.read_text(encoding="cp1252"), nir_path)

    assert len(keys) == 2

    # Key 1: HKLM\Software\TestVendor\MyApp
    k1 = keys[0]
    assert k1.root == "HKLM"
    assert k1.path == "Software\\TestVendor\\MyApp"
    assert k1.is_delete is False
    assert len(k1.values) == 4

    # Value 1: InstallDir with variable
    v1 = k1.values[0]
    assert v1.name == "InstallDir"
    assert v1.val_type == "REG_SZ"
    assert isinstance(v1.parsed_value, IrCompositeValue)
    var_names = [p.name for p in v1.parsed_value.parts if isinstance(p, IrVarRef)]
    assert "ProgramFiles" in var_names

    # Value 2: Enabled DWORD
    v2 = k1.values[1]
    assert v2.name == "Enabled"
    assert v2.val_type == "REG_DWORD"
    assert v2.dword_int == 1

    # Value 3: Data BINARY
    v3 = k1.values[2]
    assert v3.name == "Data"
    assert v3.val_type == "REG_BINARY"
    assert "01,02,03,04" in v3.raw_data

    # Value 4: List MULTI_SZ
    v4 = k1.values[3]
    assert v4.name == "List"
    assert v4.val_type == "REG_MULTI_SZ"

    # Key 2: Key deletion [-HKEY_LOCAL_MACHINE\Software\TestVendor\OldKey]
    k2 = keys[1]
    assert k2.root == "HKLM"
    assert k2.path == "Software\\TestVendor\\OldKey"
    assert k2.is_delete is True


def test_parse_nir_line_continuations(tmp_path: Path) -> None:
    """Test registry parser handling backslash line continuations for long data."""
    text = (
        "Windows Registry Editor Version 5.00\r\n"
        "\r\n"
        "[HKEY_CURRENT_USER\\Software\\TestApp]\r\n"
        '"LongBinary"=hex:01,02,03,04,05,\\\r\n'
        "  06,07,08,09,0a,\\\r\n"
        "  0b,0c,0d,0e,0f\r\n"
        '"DeleteMe"=-\r\n'
        '@="DefaultString"\r\n'
    )
    reg_file = tmp_path / "test.reg"
    keys = parse_nir(text, reg_file)

    assert len(keys) == 1
    k = keys[0]
    assert k.root == "HKCU"
    assert k.path == "Software\\TestApp"
    assert len(k.values) == 3

    # LongBinary joined
    v_bin = k.values[0]
    assert v_bin.name == "LongBinary"
    assert v_bin.val_type == "REG_BINARY"
    assert "01,02,03,04,05,06,07,08,09,0a,0b,0c,0d,0e,0f" in v_bin.raw_data

    # Delete value
    v_del = k.values[1]
    assert v_del.name == "DeleteMe"
    assert v_del.is_delete is True
    assert v_del.val_type == "DELETE"

    # Default @ value
    v_def = k.values[2]
    assert v_def.name == ""
    assert v_def.val_type == "REG_SZ"
    assert v_def.raw_data == '"DefaultString"'
