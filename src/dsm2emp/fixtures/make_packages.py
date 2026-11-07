"""Deterministic synthetic DSM package generator for test scenarios P-01 through P-12.

Generates packages with fixed random seeds for binary media to avoid VCS bloat.
"""

import random
from pathlib import Path

FIXED_SEED = 42


def _make_dummy_binary(path: Path, size_kb: int = 4) -> None:
    """Generate deterministic dummy binary payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(FIXED_SEED + len(str(path)))
    data = rng.randbytes(size_kb * 1024)
    path.write_bytes(data)


def create_p01_pure_msi(root: Path) -> Path:
    """P-01: Reines MSI (app.msi + ExecuteEx msiexec-Zeile)."""
    pkg_dir = root / "P-01_Pure_MSI"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    _make_dummy_binary(pkg_dir / "app.msi", size_kb=8)
    _make_dummy_binary(pkg_dir / "setup.mst", size_kb=2)

    script_content = (
        "; DSM eScript P-01 Pure MSI\r\n"
        'ExecuteEx(\'msiexec.exe /i "%Src%\\app.msi" TRANSFORMS="%Src%\\setup.mst" /qn\', '
        "'ErrorLevel', '0')\r\n"
        "If %ErrorLevel% != '0'\r\n"
        "  ExitProcEx(Failed, 'MSI Installation failed')\r\n"
        "EndIf\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))

    (pkg_dir / "Package.ini").write_text(
        "[Package]\nName=PureMSIApp\nVersion=1.0\nManufacturer=TestCorp\n",
        encoding="utf-8",
    )
    return pkg_dir


def create_p02_exe_params(root: Path) -> Path:
    """P-02: EXE mit Parametern, Pfaden mit Leerzeichen, Rückgabecode."""
    pkg_dir = root / "P-02_EXE_Params"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    _make_dummy_binary(pkg_dir / "setup.exe", size_kb=16)

    script_content = (
        "; DSM eScript P-02 EXE with parameters\r\n"
        "Set(TargetDir, '%ProgramFiles%\\Vendor Suite\\App')\r\n"
        "ExecuteEx('\"%Src%\\setup.exe\" /DIR=\"%TargetDir%\" /VERYSILENT', 'ExitCode', '0')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p03_conditions(root: Path) -> Path:
    """P-03: Verschachtelte Bedingungen (3 Ebenen) und GOTO."""
    pkg_dir = root / "P-03_Conditions"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    script_content = (
        "; DSM eScript P-03 Conditions\r\n"
        "If %IsRunningOnX64% = '1'\r\n"
        "  If %IsRunningOnServerOS% = '0'\r\n"
        "    If %ClientOS% = 'WIN11'\r\n"
        "      Set(Arch, 'x64_Client')\r\n"
        "    Else\r\n"
        "      Set(Arch, 'x64_Legacy')\r\n"
        "    EndIf\r\n"
        "  EndIf\r\n"
        "EndIf\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p04_registry(root: Path) -> Path:
    """P-04: Registry mit .nir Datei (REG_SZ, DWORD, MULTI_SZ, etc.)."""
    pkg_dir = root / "P-04_Registry"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    nir_content = (
        "REGEDIT4\r\n"
        "\r\n"
        "[HKEY_LOCAL_MACHINE\\Software\\TestVendor\\MyApp]\r\n"
        '"InstallDir"="%ProgramFiles%\\\\TestVendor\\\\MyApp"\r\n'
        '"Enabled"=dword:00000001\r\n'
        '"Data"=hex:01,02,03,04\r\n'
        '"List"=hex(7):61,00,00,00,00,00\r\n'
        "\r\n"
        "[-HKEY_LOCAL_MACHINE\\Software\\TestVendor\\OldKey]\r\n"
    )
    (pkg_dir / "setup.nir").write_bytes(nir_content.encode("cp1252"))

    script_content = "; DSM eScript P-04 Registry\r\nRegLoad('%Src%\\setup.nir')\r\n"
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p05_file_operations(root: Path) -> Path:
    """P-05: Dateioperationen (Copy, Delete, MakeDir, /P)."""
    pkg_dir = root / "P-05_File_Operations"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    _make_dummy_binary(pkg_dir / "data.cab", size_kb=10)
    _make_dummy_binary(pkg_dir / "helper.dll", size_kb=4)

    script_content = (
        "; DSM eScript P-05 Files\r\n"
        "MakeDir('%ProgramFiles%\\Vendor')\r\n"
        "Copy('%Src%\\helper.dll', '%ProgramFiles%\\Vendor\\helper.dll', /P)\r\n"
        "Delete('%Temp%\\old_cache.dat')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p06_shortcuts(root: Path) -> Path:
    """P-06: Verknüpfungen (CreateLink inkl. _Short und %%)."""
    pkg_dir = root / "P-06_Shortcuts"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    script_content = (
        "; DSM eScript P-06 Shortcuts\r\n"
        "CreateLink('%CommonPrograms%\\TestApp', '%ProgramFiles%\\TestApp\\app.exe', "
        "'-arg1 %%windir%%')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p07_uninstall_block(root: Path) -> Path:
    """P-07: Deinstallationsblock ($BeginUnInstallScript)."""
    pkg_dir = root / "P-07_Uninstall_Block"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    script_content = (
        "; DSM eScript P-07 Install & Uninstall\r\n"
        "ExecuteEx('setup.exe /S', 'RC', '0')\r\n"
        "$BeginUnInstallScript\r\n"
        "ExecuteEx('uninstall.exe /S', 'RC', '0')\r\n"
        "Delete('%ProgramFiles%\\App\\config.ini')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p08_dsm_infrastr(root: Path) -> Path:
    """P-08: DSM Infrastruktur-Befehle (CommitChangesToServer etc.)."""
    pkg_dir = root / "P-08_DSM_Infra"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    script_content = (
        "; DSM eScript P-08 Infrastructure\r\n"
        "NetUseDepot()\r\n"
        "CommitChangesToServer()\r\n"
        "SendStatusUpdateToServer('Installed')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("cp1252"))
    return pkg_dir


def create_p09_encodings(root: Path) -> Path:
    """P-09: Encodings: ANSI, UTF-8-BOM, UTF-16LE."""
    pkg_dir = root / "P-09_Encodings"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    text = "; Skript mit Umlauten: ÄÖÜäöüß\r\nSet(AppTitle, 'Prüfung & Test')\r\n"

    # ANSI (Windows-1252)
    (pkg_dir / "Script_ansi.inc").write_bytes(text.encode("cp1252"))
    # UTF-8 with BOM
    (pkg_dir / "Script_utf8bom.inc").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    # UTF-16 LE with BOM
    (pkg_dir / "Script_utf16le.inc").write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))

    # Default main script
    (pkg_dir / "Script.inc").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    return pkg_dir


def create_p10_torture(root: Path) -> Path:
    """P-10: Sonderzeichen-Torture: Umlaute, &|;()", lange Pfade."""
    pkg_dir = root / "P-10_Torture"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    script_content = (
        "; DSM eScript P-10 Torture\r\n"
        "Set(SpecialVal, 'A & B | C ; D (E) \"Quoted\" ÄÖÜäöüß')\r\n"
        "ExecuteEx('\"%ProgramFiles%\\Test (x86)\\app.exe\" --arg=\"hello world;\"', 'RC', '0')\r\n"
    )
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("utf-8"))
    return pkg_dir


def create_p11_damaged(root: Path) -> Path:
    """P-11: Beschädigte / truncierte Skripte."""
    pkg_dir = root / "P-11_Damaged"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Incomplete script with unclosed string and broken statement
    script_content = "ExecuteEx('broken string with no closing quote\r\n"
    (pkg_dir / "Script.inc").write_bytes(script_content.encode("utf-8"))
    return pkg_dir


def create_p12_container_and_unknown(root: Path) -> Path:
    """P-12: Paket mit .ncp Container und unbekannter Datei."""
    pkg_dir = root / "P-12_Container_Unknown"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    _make_dummy_binary(pkg_dir / "package.ncp", size_kb=12)
    (pkg_dir / "mystery.xyz").write_text("random unidentified text", encoding="utf-8")
    _make_dummy_binary(pkg_dir / "mystery.raw", size_kb=2)
    return pkg_dir


def create_all_test_packages(target_dir: Path) -> dict[str, Path]:
    """Generate all test packages P-01 through P-12 under target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    return {
        "P-01": create_p01_pure_msi(target_dir),
        "P-02": create_p02_exe_params(target_dir),
        "P-03": create_p03_conditions(target_dir),
        "P-04": create_p04_registry(target_dir),
        "P-05": create_p05_file_operations(target_dir),
        "P-06": create_p06_shortcuts(target_dir),
        "P-07": create_p07_uninstall_block(target_dir),
        "P-08": create_p08_dsm_infrastr(target_dir),
        "P-09": create_p09_encodings(target_dir),
        "P-10": create_p10_torture(target_dir),
        "P-11": create_p11_damaged(target_dir),
        "P-12": create_p12_container_and_unknown(target_dir),
    }
