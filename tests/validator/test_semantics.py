"""Tests for semantic validation of Setup.inf documents and package standard templates."""

from pathlib import Path

from dsm2emp.validator import validate_file, validate_text

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "data" / "templates"


def test_missing_mandatory_sections() -> None:
    text = """[SetupInfo]
Author=Admin
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1002" in codes  # Missing mandatory sections: [Setup], [Application], [Product]


def test_missing_application_keys() -> None:
    text = """[SetupInfo]
Author=Admin
Method=MSI

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=Test

[Product]
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1003" in codes  # Missing mandatory keys like DeveloperName, Version, Revision...


def test_nonexistent_section_reference() -> None:
    text = """[SetupInfo]
Author=Admin
Method=MSI

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
UserKeyName=Key
MachineKeyName=Key
UninstallKeyName=Key
UninstallDisplayName=Key
UninstallString=String
ReinstallString=String
SrcDir=..
ApplicationDir=AppDir
SetupInfDir=Install

[Product]
#Set:NonExistentSection, DONTDELETE
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1007" in codes


def test_nonexistent_if_then_target() -> None:
    text = """[SetupInfo]
Author=Admin
Method=MSI

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
UserKeyName=Key
MachineKeyName=Key
UninstallKeyName=Key
UninstallDisplayName=Key
UninstallString=String
ReinstallString=String
SrcDir=..
ApplicationDir=AppDir
SetupInfDir=Install

[Product]
#Set:Product

[Set:Product]
If "%ErrorLevel%" == "0" Then "MissingTarget" EndIf
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1007" in codes


def test_duplicate_section() -> None:
    text = """[SetupInfo]
Author=Admin

[SetupInfo]
Author=Admin2
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1001" in codes


def test_standard_msi_template_validation() -> None:
    path = TEMPLATES_DIR / "MSI_Standard.inf"
    issues = validate_file(path)
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, f"Errors in MSI_Standard.inf: {errors}"


def test_standard_unattended_template_validation() -> None:
    path = TEMPLATES_DIR / "Unattended_Standard.inf"
    issues = validate_file(path)
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, f"Errors in Unattended_Standard.inf: {errors}"


def test_standard_skripte_template_validation() -> None:
    path = TEMPLATES_DIR / "Skripte_Standard.inf"
    issues = validate_file(path)
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, f"Errors in Skripte_Standard.inf: {errors}"


def test_standard_links_template_validation() -> None:
    path = TEMPLATES_DIR / "Links_Standard.inf"
    issues = validate_file(path)
    errors = [i for i in issues if i.severity == "error"]
    assert not errors, f"Errors in Links_Standard.inf: {errors}"


def test_setreboot_lowercase_invalid_mode_flagged() -> None:
    """Regression: Empirum is case-insensitive; 'setreboot 9' must be parsed as
    SetRebootStmt so the E1008 mode range check applies (previously it slipped
    through as an unrecognized-but-accepted generic command)."""
    text = """[SetupInfo]
Author=

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=Test
DeveloperName=Dev
Version=1.0
Revision=0

[Product]
#Set:Product, DONTDELETE

[Set:Product]
setreboot 9
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "E1008" in codes


def test_setreboot_case_variants_recognized() -> None:
    text = """[SetupInfo]
Author=

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=Test
DeveloperName=Dev
Version=1.0
Revision=0

[Product]
#Set:Product, DONTDELETE

[Set:Product]
SETREBOOT 1
SetReboot=0
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "W2008" not in codes  # recognized as SetRebootStmt in all spellings
    assert "E1008" not in codes


def test_callhidden_lowercase_recognized() -> None:
    text = """[SetupInfo]
Author=

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=Test
DeveloperName=Dev
Version=1.0
Revision=0

[Product]
#Set:Product, DONTDELETE

[Set:Product]
callhidden msiexec.exe /x "{12345678-1234-1234-1234-123456789012}" /qn /norestart
"""
    issues = validate_text(text)
    codes = {i.code for i in issues}
    assert "W2008" not in codes


def test_standard_error_sections_may_be_unreferenced() -> None:
    """Regression: [Set:InstallationError] / [Set:ReinstallationError] /
    [Set:DeInstallationError] are classic-template boilerplate shipped
    unreferenced by design (the engine's If jumps go to AbortMSIInst instead)
    and must not trigger W2009. Genuinely unreferenced custom sections still do.
    """
    text = """[SetupInfo]
Author=

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=Test
DeveloperName=Dev
Version=1.0
Revision=0

[Product]
#Set:Product, DONTDELETE

[Set:Product]
Sleep 500

[Set:InstallationError]
ErrorLogMsg %ErrorLogMessage%
Abort

[Set:ReinstallationError]
ErrorLogMsg %ErrorLogMessage%
Abort

[Set:DeInstallationError]
-ErrorLogMsg %ErrorLogMessage%
-Abort

[Set:Then_Orphan]
Sleep 100
"""
    issues = validate_text(text)
    w2009 = [i.message for i in issues if i.code == "W2009"]
    assert len(w2009) == 1, f"Expected W2009 only for Set:Then_Orphan, got: {w2009}"
    assert "Set:Then_Orphan" in w2009[0]


def test_val002_quoted_function_predicate() -> None:
    """VAL-002: Quoting function predicates in If statement is an error."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
If "DoesFileExist (%Windows%\\app.ini)" == "1" Then "Set:Sub" EndIf
[Set:Sub]
Sleep 100
"""
    issues = validate_text(text)
    val002 = [i for i in issues if i.code == "VAL-002"]
    assert len(val002) >= 1
    assert "DoesFileExist" in val002[0].message


def test_val003_trailing_backslash_on_deltree() -> None:
    """VAL-003: DelTree path must not have a trailing backslash."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
DelTree "%App%\\"
"""
    issues = validate_text(text)
    val003 = [i for i in issues if i.code == "VAL-003"]
    assert len(val003) >= 1
    assert "trailing backslash" in val003[0].message


def test_val004_missing_uninstall_error_prefix() -> None:
    """VAL-004: In [Set:DeInstallationError], Abort without '-' prefix must be flagged."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
#Set:DeInstallationError, DELETE
[Set:Product]
Sleep 100
[Set:DeInstallationError]
ErrorLogMsg %ErrorLogMessage%
Abort
"""
    issues = validate_text(text)
    val004 = [i for i in issues if i.code == "VAL-004"]
    assert len(val004) >= 1
    assert any("Abort" in i.message for i in val004)


def test_val005_duplicated_shelllinks_call() -> None:
    """VAL-005: Calling #Shell:Product when ShellLinks=1 duplicates shortcuts."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
ShellLinks=1
[Product]
#Set:Product
#Shell:Product
[Set:Product]
Sleep 100
[Shell:Product]
"%CommonDesktop%\\App","%App%\\app.exe"
"""
    issues = validate_text(text)
    val005 = [i for i in issues if i.code == "VAL-005"]
    assert len(val005) >= 1
    assert "ShellLinks=1" in val005[0].message


def test_val006_hkcu_without_aw() -> None:
    """VAL-006: Warning when HKCU is present but [SetupInfo] lacks /AW."""
    text = """[SetupInfo]
Author=
Command line options=/S2
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
#Reg:Product
[Set:Product]
Sleep 100
[Reg:Product]
HKCU,"Software\\MyVendor\\App","Setting",0x00000000,"1"
"""
    issues = validate_text(text)
    val006 = [i for i in issues if i.code == "VAL-006"]
    assert len(val006) >= 1
    assert "HKCU" in val006[0].message


def test_val007_dangerous_root_deletion() -> None:
    """VAL-007: Dangerous root deletion in registry must be warned."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
#Reg:Product
[Set:Product]
Sleep 100
[Reg:Product]
-HKLM,"SOFTWARE\\Microsoft"
"""
    issues = validate_text(text)
    val007 = [i for i in issues if i.code == "VAL-007"]
    assert len(val007) >= 1
    assert "Dangerous root deletion" in val007[0].message


def test_val008_missing_errorlevel_check_after_msi() -> None:
    """VAL-008: Warning when Call to msiexec is not followed by ErrorLevel check."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
CallHidden msiexec.exe /i "%Src%\\app.msi" /qn
Sleep 100
"""
    issues = validate_text(text)
    val008 = [i for i in issues if i.code == "VAL-008"]
    assert len(val008) >= 1
    assert "msiexec" in val008[0].message.lower()


def test_val009_uncontrolled_reboot() -> None:
    """VAL-009: Warning when Reboot=1 in [Application]."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
Reboot=1
[Product]
#Set:Product
[Set:Product]
Sleep 100
"""
    issues = validate_text(text)
    val009 = [i for i in issues if i.code == "VAL-009"]
    assert len(val009) >= 1
    assert "Reboot=1" in val009[0].message


def test_val010_hardcoded_system_path() -> None:
    """VAL-010: Info when hardcoded system paths are used."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
Copy "C:\\Program Files\\App\\file.txt", "C:\\Windows\\file.txt"
"""
    issues = validate_text(text)
    val010 = [i for i in issues if i.code == "VAL-010"]
    assert len(val010) >= 1
    assert any("program files" in i.message.lower() for i in val010)


def test_val020_direct_command_in_if() -> None:
    """VAL-020: Direct command after Then in If statement is illegal."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
If %ErrorLevel% != "0" Then Abort EndIf
"""
    issues = validate_text(text)
    val020 = [i for i in issues if i.code == "VAL-020"]
    assert len(val020) >= 1
    assert "Abort" in val020[0].message


def test_val021_sleep_equals_syntax() -> None:
    """VAL-021: Sleep=3000 is an invalid command assignment syntax in Empirum."""
    text = """[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
#Set:Product
[Set:Product]
Sleep=3000
"""
    issues = validate_text(text)
    val021 = [i for i in issues if i.code == "VAL-021"]
    assert len(val021) >= 1
    assert "Sleep=" in val021[0].message


def test_val030_utf8_bom_in_text_rejected() -> None:
    """VAL-030: A leading UTF-8 BOM (U+FEFF) in the emitted text is an error."""
    text = """﻿[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
"""
    issues = validate_text(text)
    val030 = [i for i in issues if i.code == "VAL-030"]
    assert len(val030) == 1
    assert "BOM" in val030[0].message


def test_val030_mojibake_bom_prefix_rejected() -> None:
    """VAL-030: 'ï»¿' (BOM bytes misdecoded as CP1252) is detected as well."""
    text = """ï»¿[SetupInfo]
Author=
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
"""
    issues = validate_text(text)
    assert any(i.code == "VAL-030" for i in issues)


def test_val031_non_cp1252_characters_rejected() -> None:
    """VAL-031: Characters not representable in Windows-1252 are an error."""
    text = """[SetupInfo]
Author=
[Strings:07]
EndMessageDesc=Instalacja zakończona pomyślnie!
[Setup]
Version=14.2
Platform=*
[Application]
ProductName=App
DeveloperName=Dev
Version=1.0
Revision=0
[Product]
"""
    issues = validate_text(text)
    val031 = [i for i in issues if i.code == "VAL-031"]
    assert len(val031) == 1
    assert "Windows-1252" in val031[0].message
    assert "line 4" in val031[0].message  # offending line is reported


def test_val030_val031_can_be_disabled_via_flag() -> None:
    """check_encoding=False skips the encoding gate (used by validate_file's byte check)."""
    issues = validate_text("﻿[SetupInfo]\n", check_encoding=False)
    assert not any(i.code in ("VAL-030", "VAL-031") for i in issues)


def test_val030_file_with_utf8_bom(tmp_path: Path) -> None:
    """VAL-030 (file level): raw UTF-8 BOM bytes are detected even though read_text strips them."""
    inf = tmp_path / "Setup.inf"
    inf.write_bytes(b"\xef\xbb\xbf[SetupInfo]\r\nAuthor=\r\n")
    issues = validate_file(inf)
    assert any(i.code == "VAL-030" for i in issues)


def test_val031_file_with_undefined_cp1252_byte(tmp_path: Path) -> None:
    """VAL-031 (file level): bytes undefined in Windows-1252 (e.g. 0x81) are rejected."""
    inf = tmp_path / "Setup.inf"
    inf.write_bytes(b"[Strings:07]\r\nText=bad\x81byte\r\n")
    issues = validate_file(inf)
    assert any(i.code == "VAL-031" for i in issues)


def test_file_clean_cp1252_passes_encoding_gate(tmp_path: Path) -> None:
    """A genuine ANSI file (umlauts as single bytes, no BOM) raises no encoding errors."""
    inf = tmp_path / "Setup.inf"
    inf.write_bytes("[SetupInfo]\r\nInstallationFor=Installation für:\r\n".encode("cp1252"))
    issues = validate_file(inf)
    assert not any(i.code in ("VAL-030", "VAL-031") for i in issues)


def test_val031_file_utf8_without_bom_detected(tmp_path: Path) -> None:
    """VAL-031: UTF-8-encoded umlauts without BOM decode cleanly as CP1252 and must
    still be flagged - the most common third-party corruption variant."""
    inf = tmp_path / "Setup.inf"
    # explicit UTF-8 encoding is the subject of this test, not redundant default
    inf.write_bytes(
        "[SetupInfo]\r\nInstallationFor=Installation für:\r\n".encode("utf-8")  # noqa: UP012
    )
    issues = validate_file(inf)
    hits = [i for i in issues if i.code == "VAL-031"]
    assert len(hits) == 1
    assert "UTF-8" in hits[0].message


def test_val031_file_utf16le_without_bom_detected(tmp_path: Path) -> None:
    """VAL-031: BOM-less UTF-16 content is flagged via the detection heuristic."""
    inf = tmp_path / "Setup.inf"
    inf.write_bytes("[SetupInfo]\r\nAuthor=Ascii\r\n".encode("utf-16-le"))
    issues = validate_file(inf)
    hits = [i for i in issues if i.code == "VAL-031"]
    assert len(hits) == 1
    assert "UTF-16" in hits[0].message


def test_file_pure_ascii_passes_charset_heuristics(tmp_path: Path) -> None:
    """Pure ASCII is valid UTF-8 AND valid CP1252 - no false positive."""
    inf = tmp_path / "Setup.inf"
    inf.write_bytes(b"[SetupInfo]\r\nAuthor=ASCII only\r\n")
    issues = validate_file(inf)
    assert not any(i.code in ("VAL-030", "VAL-031") for i in issues)
