"""Test suite for the 25 quoting and escaping edge cases from the quoting specification."""

from dsm2emp.ast import (
    CallStmt,
    Command,
    Comparison,
    CopyEntry,
    FunctionCall,
    IfStmt,
    IndirectVar,
    LiteralValue,
    RegEntry,
    VarRef,
)
from dsm2emp.emitter.quote import (
    Issue,
    q_call_statement,
    q_call_token,
    q_command,
    q_copy_entry,
    q_function_call,
    q_if_statement,
    q_reg_entry,
    q_value,
    validate_percent_count,
)


def test_f01_path_without_special_chars() -> None:
    """F-01: Pfad ohne Sonderzeichen -> kein Quoting nötig."""
    cmd = Command(name="Copy", args=["C:\\Temp\\a.txt", "C:\\Ziel\\a.txt"])
    rendered = q_command(cmd)
    assert rendered == "Copy C:\\Temp\\a.txt, C:\\Ziel\\a.txt"


def test_f02_path_with_space_in_call() -> None:
    """F-02: Pfad mit Leerzeichen als Call-Argument -> gequoted."""
    call = CallStmt(program="%Src%\\Example Setup\\setup.exe")
    rendered = q_call_statement(call)
    assert rendered == 'CallHidden "%Src%\\Example Setup\\setup.exe"'


def test_f03_argument_with_spaces() -> None:
    """F-03: Argument mit Leerzeichen -> zusammenhängendes Token gequoted."""
    call = CallStmt(
        program="%Src%\\setup.exe",
        arguments=["/D=C:\\Program Files\\Example"],
    )
    rendered = q_call_statement(call)
    assert rendered == 'CallHidden "%Src%\\setup.exe" "/D=C:\\Program Files\\Example"'


def test_f04_value_with_comma_in_list() -> None:
    """F-04: Wert mit Komma in Liste -> Gesamtwert in Anführungszeichen."""
    desc = "Installer für Example, Standardsprache Deutsch"
    quoted = q_value(desc)
    assert quoted == f'"{desc}"'


def test_f05_then_target_with_space() -> None:
    """F-05: Then-Ziel (Sektionsname) mit Leerzeichen -> in Anführungszeichen."""
    stmt = IfStmt(
        condition=Comparison(left=VarRef(name="rc"), relation="==", right="0"),
        then_target="Set:Install Viewer",
    )
    rendered = q_if_statement(stmt)
    assert 'Then "Set:Install Viewer"' in rendered


def test_f06_if_operand_with_space() -> None:
    """F-06: If-Operand mit Leerzeichen -> beide Seiten gequoted."""
    stmt = IfStmt(
        condition=Comparison(
            left=VarRef(name="ProductName"),
            relation="==",
            right="Example Viewer",
        ),
        then_target="Set:Product",
    )
    rendered = q_if_statement(stmt)
    assert 'If "%ProductName%" == "Example Viewer" Then "Set:Product" EndIf' == rendered


def test_f07_literal_percent_replacevars() -> None:
    """F-07: Literal % in REPLACEVARS-Kontext."""
    # %%windir%% represents literal %windir%
    val = LiteralValue(text="%%windir%%")
    assert q_value(val) == "%%windir%%"


def test_f08_literal_percent_in_call_arg() -> None:
    """F-08: Literal % in Call-Argument -> Emitter verdoppelt %-Zeichen."""
    rendered = q_call_token("/P=50%")
    assert rendered == "/P=50%%"


def test_f09_indirect_variable() -> None:
    """F-09: Indirekte Variable %%Outer%Inner%%%."""
    var = IndirectVar(outer="InformixServers", inner=VarRef(name="Counter"))
    rendered = q_value(var)
    assert rendered == "%%InformixServers%Counter%%%"


def test_f10_registry_key_with_comma_in_path() -> None:
    """F-10: Registry-Key mit Komma -> Pfadbestandteil in '...'."""
    fn = FunctionCall(
        function="DoesRegKeyExist",
        args=[
            "HKLM,SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
            "Adobe Acrobat 8 Standard - English, Français, Deutsch,UnInstallString"
        ],
    )
    rendered = q_function_call(fn)
    expected = (
        "DoesRegKeyExist (\"HKLM,'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
        "Adobe Acrobat 8 Standard - English, Français, Deutsch',UnInstallString\")"
    )
    assert rendered == expected


def test_f11_reg_value_check_three_components() -> None:
    """F-11: Reg-Wert-Prüfung (Drei-Komponenten)."""
    fn = FunctionCall(
        function="DoesRegKeyExist",
        args=["HKLM,Software\\Matrix42\\Test,RunningInUserMode"],
    )
    rendered = q_function_call(fn)
    assert 'DoesRegKeyExist ("HKLM,Software\\Matrix42\\Test,RunningInUserMode")' == rendered


def test_f12_reg_multi_sz_with_commas() -> None:
    """F-12: REG_MULTI_SZ mit Strings und Hex-Bytes."""
    reg = RegEntry(
        root="HKLM",
        key="Software\\Application Systems",
        value_name=None,
        type_flag="0x00010000",
        data=["String1", "String2", "0D", "0A", "String3", "00"],
    )
    rendered = q_reg_entry(reg)
    expected = (
        'HKLM,"Software\\Application Systems",0x00010000,"String1","String2",0D,0A,"String3",00'
    )
    assert rendered == expected


def test_f13_echo_unc_path() -> None:
    """F-13: Echo mit UNC-Pfad."""
    cmd = Command(name="Echo", args=["\\\\Server\\Share\\"])
    rendered = q_command(cmd)
    assert rendered == "Echo \\\\Server\\Share\\"


def test_f14_semicolon_in_value() -> None:
    """F-14: Semikolon in Wert -> gequoted."""
    val = "Version 1.0; intern"
    rendered = q_value(val)
    assert rendered == f'"{val}"'


def test_f15_embedded_double_quotes_in_value() -> None:
    """F-15: Anführungszeichen im Wert -> W2004 Warnung und kein umgebendes Quoting."""
    issues: list[Issue] = []
    val = 'sag "Hallo"'
    rendered = q_value(val, issues=issues)
    assert rendered == 'sag "Hallo"'
    assert any(i.code == "W2004" for i in issues)


def test_f16_single_quote_in_reg_component() -> None:
    """F-16: Single Quote in Registry-Pfadbestandteil -> E1004 Fehler."""
    issues: list[Issue] = []
    fn = FunctionCall(
        function="DoesRegKeyExist",
        args=["HKLM,SOFTWARE\\X'Y,Value"],
    )
    q_function_call(fn, issues=issues)
    assert any(i.code == "E1004" for i in issues)


def test_f17_uninstall_only_command() -> None:
    """F-17: Nur-Deinstallation-Befehl -> Minus-Präfix direkt vor dem Befehl."""
    call = CallStmt(
        program="%App%\\uninstall.exe",
        arguments=["/S"],
        uninstall_only=True,
    )
    rendered = q_call_statement(call)
    assert rendered == '-CallHidden "%App%\\uninstall.exe" /S'


def test_f18_copy_entry_empty_destination() -> None:
    """F-18: Kopierzeile mit leerem Ziel -> leere Spalte zwischen Kommas."""
    entry = CopyEntry(
        disk=1,
        source="app.exe",
        destination="",
        flags=["NORMAL"],
        size=574784,
    )
    rendered = q_copy_entry(entry)
    assert rendered == "1:app.exe, , NORMAL, 574784"


def test_f19_source_filename_with_comma() -> None:
    """F-19: Dateiname mit Komma (Copy-Quelle) -> W2005 Warnung."""
    issues: list[Issue] = []
    entry = CopyEntry(
        disk=1,
        source="Bericht,final.txt",
        destination="",
        flags=["NORMAL"],
        size=1234,
    )
    rendered = q_copy_entry(entry, issues=issues)
    assert "1:Bericht,final.txt" in rendered
    assert any(i.code == "W2005" for i in issues)


def test_f20_short_path_var() -> None:
    """F-20: Short-Path (8.3) mit VarRef(short_name=True)."""
    var = VarRef(name="App", short_name=True)
    rendered = f'"{q_value(var)}\\legacy.exe"'
    assert rendered == '"%~App%\\legacy.exe"'


def test_f21_conditional_trailing_backslash() -> None:
    """F-21: Bedingter Backslash mit VarRef(trailing_bs=True)."""
    var = VarRef(name="SrcDir", trailing_bs=True)
    rendered = f'"{q_value(var)}data.dat"'
    assert rendered == '"%SrcDir\\%data.dat"'


def test_f22_umlauts_windows1252() -> None:
    """F-22: Umlaute in Wert (Windows-1252 kompatibel)."""
    user = "Müller"
    rendered = q_value(user)
    assert rendered == "Müller"


def test_f23_return_code_3010() -> None:
    """F-23: Rückgabecode 3010 Prüfung."""
    stmt = IfStmt(
        condition=Comparison(
            left=VarRef(name="ErrorLevel"),
            relation="==",
            right="3010",
        ),
        then_target="Set:Reboot",
    )
    rendered = q_if_statement(stmt)
    assert 'If "%ErrorLevel%" == "3010" Then "Set:Reboot" EndIf' == rendered


def test_f24_odd_percent_balance() -> None:
    """F-24: Ungerade %-Anzahl in Zeile -> E1005 Fehler."""
    issues: list[Issue] = []
    is_valid = validate_percent_count("/S 50%", issues=issues)
    assert is_valid is False
    assert any(i.code == "E1005" for i in issues)


def test_f24_windows_argument_placeholder_percent() -> None:
    """F-24: Windows %1-%9 argument placeholders in registry commands are valid."""
    issues: list[Issue] = []
    line = (
        "HKCR,Applications\\PDFXCview.exe\\shell\\open\\command,0x00000000,"
        '"%ProgramFilesDir%\\app.exe" "%1"'
    )
    assert validate_percent_count(line, issues=issues) is True
    assert len(issues) == 0

    issues.clear()
    line_print = (
        "HKCR,PDF-XChangeViewer.1\\shell\\print\\command,0x00000000,"
        '"%ProgramFilesDir%\\app.exe" /print "%1"'
    )
    assert validate_percent_count(line_print, issues=issues) is True
    assert len(issues) == 0


def test_f25_window_title_with_spaces() -> None:
    """F-25: Fenstertitel mit Leerzeichen/Wildcard -> gequoted."""
    cmd = Command(
        name="CloseWindow",
        args=['"* - Editor"', "QUERYCLOSEWINDOW", "60", '"Meldungstext"'],
    )
    rendered = q_command(cmd)
    assert rendered == 'CloseWindow "* - Editor", QUERYCLOSEWINDOW, 60, "Meldungstext"'


def test_cli_token_with_inner_quotes_and_spaces() -> None:
    """CLI token with quotes around path containing spaces should not receive outer quotes or W2004."""
    issues: list[Issue] = []
    token = '/DIR="C:\\Program Files\\UltraVNC"'
    rendered = q_call_token(token, issues=issues)
    assert rendered == '/DIR="C:\\Program Files\\UltraVNC"'
    assert not any(i.code == "W2004" for i in issues)


def test_transforms_token_no_w2004_warning() -> None:
    """MSI TRANSFORMS parameter with quoted path should not trigger W2004."""
    issues: list[Issue] = []
    token = 'TRANSFORMS="%SRC%\\Files\\Msidata\\jre.mst"'
    rendered = q_call_token(token, issues=issues)
    assert rendered == 'TRANSFORMS="%SRC%\\Files\\Msidata\\jre.mst"'
    assert not any(i.code == "W2004" for i in issues)

