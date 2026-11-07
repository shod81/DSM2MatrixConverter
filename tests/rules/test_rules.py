"""Unit tests for RuleEngine, rule loader, and transformations (Tasks T-030 to T-035)."""

from pathlib import Path

from dsm2emp.ast.nodes import Comparison
from dsm2emp.ast.values import LiteralValue, VarRef
from dsm2emp.emitter.render import emit
from dsm2emp.parser.escript.parser import parse_script
from dsm2emp.parser.ir import (
    IrCommand,
    IrCondition,
    IrLiteral,
    IrNode,
    IrPackage,
    IrScript,
    IrTodo,
    SourceRef,
)
from dsm2emp.parser.nir import parse_nir
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.loader import lint_rules, load_rules
from dsm2emp.rules.model import RuleTrace, count_constructs
from dsm2emp.validator import validate_text
from tests.fixtures.make_packages import (
    create_p01_pure_msi,
    create_p04_registry,
)


def test_rules_loader_and_linter() -> None:
    """T-030: Test rule set loading and catalog linting."""
    ruleset = load_rules()
    assert ruleset.version >= 1
    assert len(ruleset.rules) == 90

    # Lint check: no duplicate IDs, all fields valid
    issues = lint_rules(ruleset)
    assert issues == []

    # Check presence of key rules
    assert ruleset.get_rule("M-01") is not None
    assert ruleset.get_rule("M-03") is not None
    assert ruleset.get_rule("V-01") is not None
    assert ruleset.get_rule("C-01") is not None
    assert ruleset.get_rule("S-01") is not None


def test_rule_engine_m01_m04_msi_and_exec() -> None:
    """T-031: Test ExecuteEx, MSI call, and reboot checks."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)

    src = SourceRef(file=Path("test.inc"), line=1, raw="ExecuteEx(...)")
    cmd_msi = IrCommand(
        kind="ExecuteEx",
        params={
            "command": IrLiteral(value='msiexec.exe /i "%Src%\\app.msi" /qn'),
            "rc_var": IrLiteral(value="ErrorLevel"),
        },
        phase="install",
        src=src,
    )
    script = IrScript(file=Path("test.inc"), commands=[cmd_msi])
    pkg = IrPackage(name="TestMsi", main_script=script)

    result = engine.transform_package(pkg)
    assert result.document is not None
    assert len(result.traces) >= 1
    assert result.traces[0].rule_id == "M-03"

    # Emit to Setup.inf text and verify reboot section exists
    inf_text, _ = emit(result.document)
    has_msi_call = (
        "CallHidden msiexec.exe" in inf_text
        or 'CallHidden "msiexec.exe"' in inf_text
        or "CallHidden MsiExec" in inf_text
    )
    assert has_msi_call
    assert 'If "%ErrorLevel%" == "3010" Then "RebootRequired" EndIf' in inf_text
    assert "[RebootRequired]" in inf_text


def test_rule_engine_m05_m08_file_operations() -> None:
    """T-032: Test Copy, Delete, MakeDir, RemoveDir."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    src = SourceRef(file=Path("test.inc"), line=1, raw="Copy(...)")

    cmds: list[IrNode] = [
        IrCommand(
            kind="Copy",
            params={
                "source": IrLiteral(value="%Src%\\data.txt"),
                "destination": IrLiteral(value="%App%\\data.txt"),
            },
            src=src,
        ),
        IrCommand(
            kind="Delete",
            params={"path": IrLiteral(value="%Temp%\\old.tmp")},
            src=src,
        ),
        IrCommand(
            kind="MakeDir",
            params={"path": IrLiteral(value="%App%\\SubDir")},
            src=src,
        ),
        IrCommand(
            kind="RemoveDir",
            params={"path": IrLiteral(value="%App%\\EmptyDir")},
            src=src,
        ),
    ]
    script = IrScript(file=Path("test.inc"), commands=cmds)
    pkg = IrPackage(name="FilePkg", main_script=script)

    result = engine.transform_package(pkg)
    inf_text, _ = emit(result.document)

    assert 'CallHidden xcopy.exe "%Src%\\data.txt" "%App%\\data.txt" /S /H /E /V' in inf_text
    assert "Del %Temp%\\old.tmp" in inf_text
    assert "MD %App%\\SubDir" in inf_text
    assert "RD %App%\\EmptyDir" in inf_text


def test_rule_engine_extern_path_rewriting() -> None:
    """Change 1: Verify .\\extern$ is rewritten to %SRC%\\Files."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    src = SourceRef(file=Path("test.inc"), line=1, raw="MSIInstallProduct(...)")

    cmds: list[IrNode] = [
        IrCommand(
            kind="MSIInstallProduct",
            raw_args=[IrLiteral(value=".\\Extern$\\setup.msi"), IrLiteral(value="NORMAL")],
            src=src,
        ),
        IrCommand(
            kind="Copy",
            params={
                "source": IrLiteral(value=".\\extern$\\sub\\config.ini"),
                "destination": IrLiteral(value="%App%\\config.ini"),
            },
            src=src,
        ),
    ]
    script = IrScript(file=Path("test.inc"), commands=cmds)
    pkg = IrPackage(name="ExternPkg", main_script=script)

    result = engine.transform_package(pkg)
    inf_text, _ = emit(result.document)

    assert 'CallHidden MsiExec.exe /I"%SRC%\\Files\\setup.msi" /qn /norestart' in inf_text
    assert (
        'CallHidden xcopy.exe "%SRC%\\Files\\sub\\config.ini" "%App%\\config.ini" /S /H /E /V'
        in inf_text
    )


def test_rule_engine_m09_m11_registry(tmp_path: Path) -> None:
    """T-033: Test RegLoad and NIR registry integration."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)

    pkg_dir = create_p04_registry(tmp_path)
    nir_path = pkg_dir / "setup.nir"
    reg_keys = parse_nir(nir_path.read_text(encoding="cp1252"), nir_path)

    pkg = IrPackage(name="RegPkg")
    result = engine.transform_package(pkg, parsed_nirs=reg_keys)

    inf_text, _ = emit(result.document)
    assert "[Reg:Product]" in inf_text
    assert "HKLM,Software\\TestVendor\\MyApp,InstallDir" in inf_text
    assert "HKLM,Software\\TestVendor\\MyApp,Enabled,0x00010001,1" in inf_text
    assert "-HKLM,Software\\TestVendor\\OldKey" in inf_text


def test_rule_engine_m13_m20_misc_commands() -> None:
    """T-034: Test Set, Sleep, KillProcess, ExitProc, WriteLogEntry."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    src = SourceRef(file=Path("test.inc"), line=1, raw="")

    cmds: list[IrNode] = [
        IrCommand(
            kind="Set",
            params={"name": IrLiteral(value="TestVar"), "value": IrLiteral(value="123")},
            src=src,
        ),
        IrCommand(
            kind="Sleep",
            params={"seconds": IrLiteral(value="3")},
            src=src,
        ),
        IrCommand(
            kind="KillProcess",
            params={"process_name": IrLiteral(value="notepad.exe")},
            src=src,
        ),
        IrCommand(
            kind="WriteLogEntry",
            raw_args=[IrLiteral(value="Step completed")],
            src=src,
        ),
    ]
    script = IrScript(file=Path("test.inc"), commands=cmds)
    pkg = IrPackage(name="MiscPkg", main_script=script)

    result = engine.transform_package(pkg)
    inf_text, _ = emit(result.document)

    assert "Set TestVar=123" in inf_text
    assert "Sleep 3000" in inf_text
    assert "KillProcess notepad.exe" in inf_text or 'KillProcess "notepad.exe"' in inf_text
    assert 'Echo "Step completed"' in inf_text


def test_rule_engine_variables_mapping_v01_v18() -> None:
    """T-035: Test variable mapping V-01 ... V-18."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)

    assert engine.translate_variable_name("windir") == "Windows"
    assert engine.translate_variable_name("winsysdir") == "System"
    assert engine.translate_variable_name("programfiles") == "ProgramFilesDir"
    assert engine.translate_variable_name("commonfiles") == "CommonFilesDir"
    assert engine.translate_variable_name("username") == "WindowsUser"
    assert engine.translate_variable_name("computername") == "ComputerName"
    assert engine.translate_variable_name("src") == "Src"
    assert engine.translate_variable_name("app") == "App"


def test_rule_engine_conditions_mapping_c01_c20() -> None:
    """T-035: Test condition mapping C-01 ... C-20."""
    ruleset = load_rules()
    engine = RuleEngine(ruleset)

    cond_x64 = IrCondition(raw="IsRunningOnX64", kind="function", func_name="IsRunningOnX64")
    ast_cond1 = engine.translate_condition(cond_x64)
    assert isinstance(ast_cond1, Comparison)
    assert ast_cond1.left == VarRef(name="WindowsBits")
    assert ast_cond1.relation == "=="
    assert ast_cond1.right == LiteralValue(text="64")

    cond_server = IrCondition(
        raw="IsRunningOnServerOS",
        kind="function",
        func_name="IsRunningOnServerOS",
    )
    ast_cond2 = engine.translate_condition(cond_server)
    assert isinstance(ast_cond2, Comparison)
    assert ast_cond2.left == VarRef(name="OS.ProductType")
    assert ast_cond2.relation == "!="


def test_rule_engine_p01_full_transformation_and_validation(tmp_path: Path) -> None:
    """End-to-end integration: Transform P-01 MSI package and validate Setup.inf."""
    pkg_dir = create_p01_pure_msi(tmp_path)
    script_path = pkg_dir / "Script.inc"
    script = parse_script(script_path.read_text(encoding="cp1252"), script_path)

    pkg = IrPackage(
        name="PureMSIApp",
        version="1.0",
        manufacturer="TestCorp",
        main_script=script,
    )

    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    assert result.average_confidence >= 0.95
    assert len(result.todos) == 0

    inf_text, _ = emit(result.document)
    assert "[Application]" in inf_text
    assert "ProductName=PureMSIApp" in inf_text
    assert "DeveloperName=TestCorp" in inf_text

    # Validate output with semantic validator
    issues = validate_text(inf_text)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Generated Setup.inf had validation errors: {errors}"


def test_rule_engine_dsm_improvements(tmp_path: Path) -> None:
    """Test transformation of newly supported DSM commands and ! comments."""
    script_text = (
        "! This is a header comment\n"
        "!-------------------------\n"
        "MakeDir('C:\\Program Files\\App')/TS\n"
        "MSIInstallProduct('.\\setup.msi')/TS\n"
        "RemoveFolder('C:\\Temp\\AppCache')/TS\n"
        "EndProc/TS\n"
        "$BeginUnInstallScript\n"
        "MSIUnInstallProduct('{12345678-ABCD-1234-ABCD-1234567890AB}', 'App')/TS\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="App", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    # All of these commands and comments should now produce 0 TODOs
    assert len(result.todos) == 0
    inf_text, _ = emit(result.document)

    assert "; This is a header comment" in inf_text
    assert "; -------------------------" in inf_text
    assert 'MD "C:\\Program Files\\App"' in inf_text
    assert 'CallHidden MsiExec.exe /I"%SRC%\\Files\\setup.msi" /qn /norestart' in inf_text
    assert "DelTree C:\\Temp\\AppCache" in inf_text
    assert (
        "-CallHidden MsiExec.exe /X{12345678-ABCD-1234-ABCD-1234567890AB} /qn /norestart"
        in inf_text
    )


def test_checkinstallmode_handling(tmp_path: Path) -> None:
    """Verify CheckInstallMode(imWkStaPart) unwraps machine cmds.

    Also verifies imUserPart creates Set:Client.
    """
    script_text = (
        "If not CheckInstallMode(imUninstall)\n"
        "  If CheckInstallMode(imWkStaPart)\n"
        "    MakeDir('C:\\Program Files\\App')/TS\n"
        "    MSIInstallProduct('.\\setup.msi')/TS\n"
        "  EndIf\n"
        "  If CheckInstallMode(imUserPart)\n"
        "    MakeDir('%AppData%\\AppConfig')/TU\n"
        "  EndIf\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="AppMode", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    inf_text, _ = emit(result.document)

    # 1. No invalid CheckInstallMode string comparisons in Setup.inf!
    assert "CheckInstallMode" not in inf_text
    # 2. Machine commands are directly in [Set:Product]
    assert 'MD "C:\\Program Files\\App"' in inf_text
    assert 'CallHidden MsiExec.exe /I"%SRC%\\Files\\setup.msi" /qn /norestart' in inf_text
    # 3. User commands are in [Set:Client] called with CLIENT flag
    assert "#Set:Client, CLIENT" in inf_text
    assert "[Set:Client]" in inf_text
    assert "MD %AppData%\\AppConfig" in inf_text


def test_rule_engine_m28_infra_commands(tmp_path: Path) -> None:
    """Gruppe A: CommitChangesToServer and ChangeSwAssignment are handled cleanly."""
    script_text = (
        "CommitChangesToServer\n"
        "ChangeSwAssignment('{12345678-ABCD-1234-ABCD-1234567890AB}', csaInstall)/F/TW\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="InfraApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    assert result.todo_count == 0
    inf_text, _ = emit(result.document)
    assert "CommitChangesToServer" in inf_text
    assert "ChangeSwAssignment" in inf_text
    assert any(t.rule_id == "M-28" for t in result.traces)


def test_rule_engine_m21_runasex_sis(tmp_path: Path) -> None:
    """Gruppe B: RunAsEx with raUseSisAccount translates to Call in machine context."""
    script_text = (
        "RunAsEx('%varExe%','/silent','','','30','rc',raUseSisAccount+WaitForExecution)/TW\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="RunAsApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    assert result.todo_count == 0
    inf_text, _ = emit(result.document)
    assert 'CallHidden "%varExe%" /silent' in inf_text
    assert any(t.rule_id == "M-21" and t.confidence == "high" for t in result.traces)


def test_rule_engine_stray_fragments_cleanup(tmp_path: Path) -> None:
    """Gruppe C: Dangling single-word fragments (Name, False) are converted to info comments."""
    script_text = "Name\nFalse\nEndProc/TS\n"
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="StrayApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    assert result.todo_count == 0
    inf_text, _ = emit(result.document)
    assert "Verwaistes Skriptfragment ignoriert" in inf_text


def test_deinstallation_commands_reversed(tmp_path: Path) -> None:
    """Uninstall commands in Set:Deinstallation must appear in reversed order.

    DSM executes $BeginUninstallScript top-to-bottom, but Empirum Deinstallation
    requires commands bottom-to-top so that the last installed component is
    the first to be removed during uninstall.
    """
    script_text = (
        "MakeDir('C:\\\\Program Files\\\\App')/TS\n"
        "$BeginUnInstallScript\n"
        "KillProcess('ProcA')/TS\n"
        "KillProcess('ProcB')/TS\n"
        "KillProcess('ProcC')/TS\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="UninstApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    inf_text, _ = emit(result.document)
    assert "[Set:Deinstallation]" in inf_text

    lines = inf_text.splitlines()
    in_section = False
    deinstall_lines = []
    for line in lines:
        if line.strip() == "[Set:Deinstallation]":
            in_section = True
            continue
        if in_section:
            if line.startswith("["):
                break
            if line.strip():
                deinstall_lines.append(line.strip())

    kill_lines = [
        item for item in deinstall_lines if "ProcA" in item or "ProcB" in item or "ProcC" in item
    ]
    assert len(kill_lines) == 3, f"Expected 3 KillProcess lines, got: {kill_lines}"

    pos = {
        p: next(i for i, item in enumerate(kill_lines) if p in item)
        for p in ("ProcC", "ProcB", "ProcA")
    }
    assert pos["ProcC"] < pos["ProcB"] < pos["ProcA"], (
        f"Expected reversed order C<B<A, got: {pos}, lines: {kill_lines}"
    )


def test_synthesized_uninstall_when_no_begin_uninstall(tmp_path: Path) -> None:
    """When DSM package has no $BeginUninstallScript, synthesize Set:Deinstallation."""
    msi_cmd = (
        r'ExecuteEx(\'msiexec.exe /i "%Src%\setup.msi" '
        r'TRANSFORMS="%Src%\custom.mst" /qn\', \'\', \'0\')/TS'
    )
    script_text = (
        "KillProcess('MyDaemon.exe')/TS\n"
        r"MakeDir('%App%\Data')/TS" + "\n"
        r"Copy('%Src%\config.ini', '%App%\config.ini')/TS" + "\n"
        r"RegModify('HKEY_LOCAL_MACHINE\Software\MyCorp\App', 'Version', '2.0')/TS" + "\n"
        + msi_cmd
        + "\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="SynthApp", version="2.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    inf_text, _ = emit(result.document)

    # 1. Product section must have DONTDELETE / DELETE without '-'
    assert "#Set:Product, DONTDELETE" in inf_text
    assert "#Set:Deinstallation, DELETE" in inf_text
    assert "-#Set:" not in inf_text

    # 2. Set:Deinstallation section must exist
    assert "[Set:Deinstallation]" in inf_text

    lines = inf_text.splitlines()
    in_deinst = False
    deinst_lines = []
    for line in lines:
        if line.strip() == "[Set:Deinstallation]":
            in_deinst = True
            continue
        if in_deinst:
            if line.startswith("["):
                break
            if line.strip():
                deinst_lines.append(line.strip())

    # 3. Check inverted commands
    assert any(r'-DelTree "%App%\Data"' in d_line for d_line in deinst_lines)
    assert any(r'-Del "%App%\config.ini"' in d_line for d_line in deinst_lines)
    assert any(
        "-CallHidden msiexec.exe /x \"%Src%\\setup.msi\" /qn" in d_line for d_line in deinst_lines
    )
    assert any("-KillProcess MyDaemon.exe" in d_line for d_line in deinst_lines)
    assert any(
        'If "%ErrorLevel%" != "0" Then "AbortMSIInst" EndIf' in d_line
        for d_line in deinst_lines
    )
    assert any(
        'If "%ErrorLevel%" == "3010" Then "RebootRequired" EndIf' in d_line
        for d_line in deinst_lines
    )

    # 4. Check bottom-to-top order in Set:Deinstallation:
    # Top of section: DelTree, then Del, then msiexec /x, then KillProcess at bottom
    idx_deltree = next(i for i, item in enumerate(deinst_lines) if "-DelTree" in item)
    # match plain Del only (DelTree would also contain the substring "-Del")
    idx_del = next(
        i
        for i, item in enumerate(deinst_lines)
        if item.startswith("-Del ") or item.startswith('-Del "')
    )
    idx_msi = next(i for i, item in enumerate(deinst_lines) if "msiexec.exe /x" in item)
    idx_kill = next(i for i, item in enumerate(deinst_lines) if "KillProcess" in item)
    assert idx_deltree < idx_del < idx_msi < idx_kill, (
        f"Expected order DelTree < Del < MSI < KillProcess, got: "
        f"DelTree={idx_deltree}, Del={idx_del}, MSI={idx_msi}, Kill={idx_kill}"
    )

    # 5. Check Registry deletion in Reg:Product
    assert '[Reg:Product]' in inf_text
    assert '-HKLM,Software\\MyCorp\\App,Version' in inf_text


def test_abort_msi_section_only_when_msi_used(tmp_path: Path) -> None:
    """[AbortMSIInst] must only be emitted when the package performs MSI operations.

    Pure unattend packages must neither reference nor define the MSI error
    section; Inno Setup uninstallers jump to Set:DeInstallationError instead.
    """
    ruleset = load_rules()

    def _transform(script_text: str, name: str) -> str:
        script_file = tmp_path / f"{name}.inc"
        script_file.write_text(script_text, encoding="utf-8")
        script = parse_script(script_text, script_file)
        pkg = IrPackage(name=name, version="1.0", main_script=script)
        result = RuleEngine(ruleset).transform_package(pkg)
        inf_text, _ = emit(result.document)
        return inf_text

    # 1. Pure unattend package: no msiexec anywhere -> no MSI error section
    unattend_inf = _transform(
        "Copy('%Src%\\tool.exe', '%App%\\tool.exe')/TS\n"
        "KillProcess('MyDaemon.exe')/TS\n",
        "UnattendApp",
    )
    assert "[AbortMSIInst]" not in unattend_inf
    assert "AbortMSIInst" not in unattend_inf

    # 2. Inno Setup installer: uninstall synthesis targets Set:DeInstallationError
    inno_inf = _transform(
        "ExecuteEx('%SRC%\\setup.exe /VERYSILENT /NORESTART', '', '0')/TS\n",
        "InnoApp",
    )
    assert "[AbortMSIInst]" not in inno_inf
    assert "AbortMSIInst" not in inno_inf
    assert 'If "%ErrorLevel%" != "0" Then "Set:DeInstallationError" EndIf' in inno_inf

    # 3. MSI package: the error section is still emitted alongside the reference
    msi_inf = _transform(
        "ExecuteEx('msiexec.exe /i \"%Src%\\\\app.msi\" /qn', '', '0')/TS\n",
        "MsiApp",
    )
    assert "[AbortMSIInst]" in msi_inf
    assert 'If "%ErrorLevel%" != "0" Then "AbortMSIInst" EndIf' in msi_inf


def test_product_section_no_minus_prefix(tmp_path: Path) -> None:
    """Product section section calls must never have a '-' prefix."""
    script_text = (
        "ExecuteEx('msiexec.exe /i \"%Src%\\\\test.msi\" /qn', '', '0')/TS\n"
        "$BeginUnInstallScript\n"
        "ExecuteEx('msiexec.exe /x \"%Src%\\\\test.msi\" /qn', '', '0')/TS\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="NoMinusApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    inf_text, _ = emit(result.document)

    lines = inf_text.splitlines()
    in_product = False
    product_lines = []
    for line in lines:
        if line.strip() == "[Product]":
            in_product = True
            continue
        if in_product:
            if line.startswith("["):
                break
            if line.strip() and not line.strip().startswith(";"):
                product_lines.append(line.strip())

    assert "#Set:Product, DONTDELETE" in product_lines
    assert "#Set:Deinstallation, DELETE" in product_lines
    for pl in product_lines:
        assert not pl.startswith("-#"), f"Product line must not start with -#: {pl}"


def test_relative_source_paths_rewritten_to_src_files(tmp_path: Path) -> None:
    """Verify relative source paths (.\\ and relative without .\\) resolve to %SRC%\\Files."""
    script_text = (
        "Copy('.\\Grass Valley\\EDIUS\\8.00\\CurrentSettings.esp', "
        "'%USERPROFILE%\\AppData\\Roaming\\Grass Valley\\EDIUS\\11.00')/TS\n"
        "Copy('SubDir\\Config.ini', '%App%\\Config.ini')/TS\n"
        "ExecuteEx('.\\setup.exe /S /v\"\"/qn\"\"', '', '0')/TS\n"
        "ExecuteEx('msiexec.exe /i \".\\setup.msi\" /qn', '', '0')/TS\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="EdiusApp", version="11.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    inf_text, _ = emit(result.document)

    # 1. EDIUS copy with .\ and spaces must resolve to %SRC%\Files\...
    assert (
        r'CallHidden xcopy.exe "%SRC%\Files\Grass Valley\EDIUS\8.00\CurrentSettings.esp"'
        in inf_text
    )
    assert r'".\Grass Valley' not in inf_text

    # 2. Relative copy without .\ must also resolve to %SRC%\Files\...
    assert r'CallHidden xcopy.exe "%SRC%\Files\SubDir\Config.ini"' in inf_text

    # 3. ExecuteEx with .\setup.exe must resolve to %SRC%\Files\setup.exe
    assert r'CallHidden "%SRC%\Files\setup.exe" /S /v""/qn""' in inf_text

    # 4. MSI with .\setup.msi must resolve to %SRC%\Files\setup.msi
    assert r'CallHidden msiexec.exe /i "%SRC%\Files\setup.msi" /qn' in inf_text


def test_regdeletekey_install_context_emits_callhidden_reg_delete(tmp_path: Path) -> None:
    """Verify RegDeleteKey in install context maps to CallHidden reg.exe delete without TODOs."""
    script_text = (
        "RegDeleteKey('HKEY_LOCAL_MACHINE\\SOFTWARE\\OPTIMAL SYSTEMS','',)/TS\n"
        "RegDeleteKey('HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Adobe\\FeatureLockDown','bUpdater',)/TS\n"
        "RegDeleteKey('HKEY_CURRENT_USER\\Software\\Adobe\\Acrobat Reader\\DC','',)/TU\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="RegDelApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    # Must resolve cleanly without TODOs
    assert result.todo_count == 0
    inf_text, _ = emit(result.document)

    # 1. Full key deletion
    assert 'CallHidden reg.exe delete "HKLM\\SOFTWARE\\OPTIMAL SYSTEMS" /f' in inf_text
    # 2. Specific value deletion
    val_del_cmd = (
        'CallHidden reg.exe delete "HKLM\\SOFTWARE\\Policies\\Adobe\\FeatureLockDown" '
        '/v "bUpdater" /f'
    )
    assert val_del_cmd in inf_text
    # 3. HKCU user-part key deletion
    assert 'CallHidden reg.exe delete "HKCU\\Software\\Adobe\\Acrobat Reader\\DC" /f' in inf_text


def test_function_condition_eval_without_nameerror(tmp_path: Path) -> None:
    """Verify function conditions (like FileVersion) translate without missing name errors."""
    script_text = (
        "If FileVersion('C:\\Program Files\\App\\app.exe')<>11.0.0\n"
        "  ExitProcEx(Failed,'version mismatch')\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    pkg = IrPackage(name="FnCondApp", version="1.0", main_script=script)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)
    result = engine.transform_package(pkg)

    assert result.todo_count == 0
    inf_text, _ = emit(result.document)
    assert 'FileVersion ("C:\\Program Files\\App\\app.exe")' in inf_text




def test_engine_reuse_resets_per_package_state() -> None:
    """Regression: a reused RuleEngine must not leak state between packages.

    Previously _has_uninst_section stayed True from the first run, emitting a
    dangling '#Set:Deinstallation, DELETE' reference in [Product] for a second
    package without uninstall commands; _section_counter also kept incrementing.
    """
    engine = RuleEngine(load_rules())

    ir1 = parse_script(
        "If DoesFileExist('x') = '1'\n  Sleep(5)\nEndIf\n"
        "$BeginUnInstallScript\nDelete('%Temp%\\a.txt')\n",
        Path("a.inc"),
    )
    r1 = engine.transform_package(IrPackage(name="P1", main_script=ir1))
    names1 = [s.name for s in r1.document.sections]
    assert "Set:Then_1" in names1
    assert "Set:Deinstallation" in names1

    # RegLoad has no invertible counterpart, so no uninstall section is
    # synthesized for the second package
    ir2 = parse_script("RegLoad('%Src%\\config.nir')\n", Path("b.inc"))
    r2 = engine.transform_package(IrPackage(name="P2", main_script=ir2))
    names2 = [s.name for s in r2.document.sections]
    assert "Set:Deinstallation" not in names2
    assert "Set:Then_2" not in names2  # counter restarted

    product = r2.document.section("Product")
    assert product is not None
    refs = [getattr(line, "target", "") for line in product.lines]
    assert "Set:Deinstallation" not in refs


def test_count_constructs_does_not_double_count_todos() -> None:
    """Every transformation TODO also produces a todo-confidence trace; the
    shared counting must count that construct exactly once."""
    todo = IrTodo(
        raw="Bad()", message="unhandled", src=SourceRef(file=Path("s.inc"), line=1, raw="Bad()")
    )
    todo_trace = RuleTrace(
        rule_id="TODO",
        source_line=1,
        source_raw="Bad()",
        confidence="todo",
        target_summary="t",
        doc_ref="d",
    )
    high_trace = RuleTrace(
        rule_id="M-01",
        source_line=2,
        source_raw="Ok('a')",
        confidence="high",
        target_summary="t",
        doc_ref="d",
    )

    counts = count_constructs([high_trace, todo_trace], [todo])
    assert counts["total_constructs"] == 2  # not 3 (len(traces) + len(todos))
    assert counts["high"] == 1
    assert counts["todo"] == 1
    assert counts["todo_items"] == 1


def test_count_constructs_parse_only_todo_is_extra_construct() -> None:
    """A todo without any matching trace (e.g. parse-level todo) adds to totals."""
    todo = IrTodo(
        raw="garbage",
        message="parse error",
        src=SourceRef(file=Path("s.inc"), line=9, raw="garbage"),
    )
    high_trace = RuleTrace(
        rule_id="M-01",
        source_line=1,
        source_raw="Ok('a')",
        confidence="high",
        target_summary="t",
        doc_ref="d",
    )
    counts = count_constructs([high_trace], [todo])
    assert counts["total_constructs"] == 2
    assert counts["todo"] == 1


def test_delete_command_directory_becomes_deltree(tmp_path: Path) -> None:
    """Regression (KB anti-pattern 3): Del cannot remove directories.

    DSM 'Delete()' on a folder (no file extension) must emit DelTree; on a file
    it stays Del. Trailing backslashes are stripped (KB anti-pattern 2: DelTree
    with trailing backslash fails).
    """
    script_text = (
        "Delete('%APPDATA%\\DialogCrmAddInDevelop')\n"
        "$BeginUnInstallScript\n"
        "Delete('%APPDATA%\\DialogCrmAddInDevelop\\')\n"
        "Delete('%WINDIR%\\app.ini')\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_file.read_text(encoding="utf-8"), script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="App", main_script=script)
    )
    inf_text, _ = emit(result.document)

    # install context: Delete of a directory -> DelTree (no '-', install section)
    assert "DelTree %APPDATA%\\DialogCrmAddInDevelop" in inf_text
    # uninstall context: trailing backslash stripped, still DelTree with '-'
    assert "-DelTree %APPDATA%\\DialogCrmAddInDevelop" in inf_text
    # file with extension stays Del (VAR_MAP translates %WINDIR% -> %Windows%)
    assert "-Del %Windows%\\app.ini" in inf_text
    # never a bare 'Del' targeting the folder itself
    assert "-Del %APPDATA%" not in inf_text
    assert "-DelTree %APPDATA%\\DialogCrmAddInDevelop\\" not in inf_text


def test_if_with_and_condition_emits_ampersand(tmp_path: Path) -> None:
    """Test that DSM If with AND condition is emitted with '&' in Setup.inf."""
    script_text = (
        "If %Var1% == '1' And %Var2% == '2'\n"
        "  ExecuteEx('setup.exe', '', '0')\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="App", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert '("%Var1%" == "1") & ("%Var2%" == "2")' in inf_text


def test_registry_qword_type_flag() -> None:
    """Test that REG_QWORD values emit standard Empirum flag 0x00040001."""
    from dsm2emp.parser.nir import IrRegKey, IrRegValue

    key = IrRegKey(
        root="HKLM",
        path="Software\\TestVendor\\App",
        values=[
            IrRegValue(
                name="BigNum",
                val_type="REG_QWORD",
                raw_data="0x1234567890abcdef",
            )
        ],
        src=SourceRef(file=Path("test.nir"), line=1, raw="[HKLM\\Software\\TestVendor\\App]"),
    )
    engine = RuleEngine(load_rules())
    entries = engine._transform_registry_keys([key])
    assert len(entries) == 1
    reg_entry = entries[0]
    assert getattr(reg_entry, "type_flag", None) == "0x00040001"


def test_regmodifydword_toplevel_in_reg_product(tmp_path: Path) -> None:
    """Test top-level RegModifyDWord is emitted into [Reg:Product] with 0x00010001."""
    script_text = "RegModifyDWord('HKLM\\SOFTWARE\\TestApp','Setting','1',mrdwSet)\n"
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="App", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert '[Reg:Product]' in inf_text
    assert 'HKLM,SOFTWARE\\TestApp,Setting,0x00010001,1' in inf_text


def test_regmodifydword_in_if_branch_uses_callhidden_reg_add(tmp_path: Path) -> None:
    """Test RegModifyDWord inside an If branch emits sequential CallHidden reg.exe add."""
    script_text = (
        "If RegValue('HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start')='2'\n"
        "  RegModifyDWord('HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start','4',mrdwSet)\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="App", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert 'If "%HKLM,SYSTEM\\CurrentControlSet\\Services\\bfs,Start%" == "2" Then "Set:Then_1" EndIf' in inf_text
    assert '[Set:Then_1]' in inf_text
    assert 'CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" /v Start /t REG_DWORD /d 4 /f' in inf_text


def test_beginuninstallscript_regmodifydword_emits_minus_callhidden(tmp_path: Path) -> None:
    """Test $BeginUninstallScript with RegModifyDWord emits -CallHidden reg.exe add in [Set:Deinstallation]."""
    script_text = (
        "RegModifyDWord('HKLM\\SOFTWARE\\App','Mode','1',mrdwSet)\n"
        ": $BeginUninstallScript\n"
        "RegModifyDWord('HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs\\','Start','2',mrdwSet)\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="App", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert '[Set:Deinstallation]' in inf_text
    assert '-CallHidden reg.exe add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\bfs" /v Start /t REG_DWORD /d 2 /f' in inf_text


def test_dsm_system_variables_mapped(tmp_path: Path) -> None:
    """Test that DSM system and path variables are properly mapped to Empirum equivalents."""
    script_text = (
        "Copy('%SourceDir%\\setup.exe', '%InstallDir%\\setup.exe')\n"
        "Copy('%ProgramData%\\config.ini', '%CommonDesktop%\\link.txt')\n"
        "If %ExitCode% != '0'\n"
        "  ExitProcEx(Failed, 'Fehler auf %UserDomain%')\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="VarApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    # %SourceDir% -> %Src%, %InstallDir% -> %App%
    assert '"%Src%\\setup.exe"' in inf_text
    assert '"%App%\\setup.exe"' in inf_text
    # %ProgramData% -> %CommonAppData%, %CommonDesktop%
    assert '"%CommonAppData%\\config.ini"' in inf_text
    assert '"%CommonDesktop%\\link.txt"' in inf_text
    # %ExitCode% -> %ErrorLevel%, %UserDomain% -> %DomainName%
    assert "%ErrorLevel%" in inf_text
    assert "%DomainName%" in inf_text



def test_hkcu_activates_aw_switch(tmp_path: Path) -> None:
    """Test that HKCU registry modifications activate /AW in [SetupInfo] Command line options."""
    script_text = (
        "RegModify('HKCU\\Software\\MyVendor\\MyApp','Theme','Dark',mrCreate)\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="UserApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert "Command line options=/S2 /AW" in inf_text
    assert any(t.rule_id == "S-05" for t in result.traces)


def test_tu_user_commands_route_to_client(tmp_path: Path) -> None:
    """DSM /TU commands land in [Set:Client] (CLIENT) and activate /AW + MACHINE flags.

    The machine entries in [Product] must carry MACHINE so Setup.exe knows which
    parts run per machine and which per user; [SetupInfo] 'Command line options'
    must switch from /S2 to /S2 /AW.
    """
    script_text = (
        "MakeDir('C:\\Program Files\\App')/TS\n"
        "RegModify('HKLM\\Software\\MyVendor\\MyApp','InstallPath','C:\\App',mrCreate)\n"
        "ExecuteEx('usersetup.exe')/TU\n"
        "MakeDir('%AppData%\\AppConfig')/TU\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="TuApp", version="1.0", main_script=script)
    )
    inf_text, _ = emit(result.document)

    # 1. User commands routed to [Set:Client], never into [Set:Product]
    assert "[Set:Client]" in inf_text
    assert "CallHidden usersetup.exe" in inf_text
    assert "MD %AppData%\\AppConfig" in inf_text
    set_product_idx = inf_text.index("[Set:Product]")
    set_client_idx = inf_text.index("[Set:Client]")
    assert "usersetup.exe" not in inf_text[set_product_idx:set_client_idx]

    # 2. [Product] references: CLIENT for user part, MACHINE for machine parts
    assert "#Set:Client, CLIENT" in inf_text
    assert "#Set:Product, DONTDELETE, MACHINE" in inf_text
    assert "#Reg:Product, MACHINE" in inf_text

    # 3. /AW switch in [SetupInfo]
    assert "Command line options=/S2 /AW" in inf_text
    assert any(
        t.rule_id == "S-05" and "/TU" in t.target_summary for t in result.traces
    )


def test_tu_with_hkcu_keeps_reg_product_unflagged(tmp_path: Path) -> None:
    """With a user part AND HKCU entries, [Reg:Product] stays unflagged.

    HKCU registry data must also apply in the user pass (/AW), so the section
    reference must not be restricted to MACHINE context.
    """
    script_text = (
        "RegModify('HKCU\\Software\\MyVendor\\MyApp','Theme','Dark',mrCreate)\n"
        "MakeDir('%Desktop%\\AppLink')/TU\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="TuHkcuApp", version="1.0", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert "#Set:Client, CLIENT" in inf_text
    assert "Command line options=/S2 /AW" in inf_text
    assert "#Reg:Product, MACHINE" not in inf_text
    assert "#Reg:Product" in inf_text


def test_pure_machine_package_keeps_unflagged_product(tmp_path: Path) -> None:
    """Without a user part, [Product] entries stay unflagged (no MACHINE churn)."""
    script_text = "MakeDir('C:\\\\Program Files\\\\App')/TS\n"
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="MachApp", version="1.0", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert "#Set:Product, DONTDELETE" in inf_text
    assert ", MACHINE" not in inf_text
    assert "Command line options=/S2\r\n" in inf_text or "Command line options=/S2\n" in inf_text


def test_tu_and_imuserpart_merge_into_single_client_section(tmp_path: Path) -> None:
    """imUserPart blocks and /TU commands share one [Set:Client] section."""
    script_text = (
        "If CheckInstallMode(imUserPart)\n"
        "  MakeDir('%AppData%\\FromBlock')/TU\n"
        "EndIf\n"
        "Echo('per user')/TU\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="MergeApp", version="1.0", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert inf_text.count("[Set:Client]") == 1
    assert "#Set:Client, CLIENT" in inf_text
    assert "MD %AppData%\\FromBlock" in inf_text


def test_uninstall_synthesizes_sleep_before_cleanup(tmp_path: Path) -> None:
    """Test that synthesized uninstall places -Sleep 3000 between uninstaller and directory cleanup."""
    script_text = (
        "ExecuteEx('\"%Src%\\\\setup.exe\" /S', 'rc', '60')\n"
        "MakeDir('%App%\\\\Cache')\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="SleepApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert "[Set:Deinstallation]" in inf_text
    assert "-Sleep 3000" in inf_text
    # DelTree appears before -Sleep in reverse execution order (file text order)
    lines = inf_text.splitlines()
    idx_deltree = next(i for i, l in enumerate(lines) if "-DelTree" in l)
    idx_sleep = next(i for i, l in enumerate(lines) if "-Sleep 3000" in l)
    idx_uninst = next(i for i, l in enumerate(lines) if "uninstall.exe" in l or "setup.exe" in l)
    # File order: DelTree < Sleep < Uninstaller (reverse execution: Uninstaller runs, then Sleep, then DelTree)
    assert idx_deltree < idx_sleep < idx_uninst


def test_deletefilelist_and_services(tmp_path: Path) -> None:
    """Test DeleteFileList and StartService/StopService transformations."""
    script_text = (
        "DeleteFileList\n"
        " .\\file1.txt\n"
        " %windir%\\system32\\subfolder\n"
        "StartService('Spooler')\n"
        "StopService('wuauserv')\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="SvcApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert "Del %SRC%\\Files\\file1.txt" in inf_text
    assert "DelTree %Windows%\\system32\\subfolder" in inf_text
    assert "StartService Spooler" in inf_text
    assert "StopService wuauserv" in inf_text
    assert len(result.todos) == 0


def test_regread_and_runas_and_regload(tmp_path: Path) -> None:
    """Test RegReadValue, RunAsEx without user, and RegLoadEx return without TODOs."""
    script_text = (
        "RegReadValue('HKLM\\SOFTWARE\\App', 'Version', 'AppVer')\n"
        "RunAsEx('\"%Src%\\tool.exe\"', '/quiet', '', '', '', '', 'raNoWait')\n"
        "RegLoadEx('setup.nir')\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="RegApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert 'Set AppVer="%%%HKLM\\SOFTWARE\\App,Version%%%"' in inf_text
    assert "CallHidden" in inf_text
    assert "setup.nir" in inf_text
    assert len(result.todos) == 0


def test_security_user_and_group(tmp_path: Path) -> None:
    """Test LocalUserCreate and LocalGroupAddMembers with continuation line."""
    script_text = (
        "LocalUserCreate('testadmin', 'Local Admin')\n"
        "LocalGroupAddMembers('Administratoren|S-1-5-32-544')\n"
        " testadmin\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="SecApp", main_script=script)
    )
    inf_text, _ = emit(result.document)

    assert 'net user "testadmin" /add' in inf_text
    assert 'net localgroup "Administratoren" "testadmin" /add' in inf_text
    assert len(result.todos) == 0


def test_callscriptas_machine_context_and_user_context(tmp_path: Path) -> None:
    """Test CallScriptAs with raUseSisAccount (machine) vs explicit user."""
    # 1. Machine context with raUseSisAccount
    script_text1 = "CallScriptAs('C:\\Scripts\\test.ps1', '', '', '', raUseSisAccount)\n"
    script_file1 = tmp_path / "Script1.inc"
    script_file1.write_text(script_text1, encoding="utf-8")
    script1 = parse_script(script_text1, script_file1)
    result1 = RuleEngine(load_rules()).transform_package(
        IrPackage(name="SisApp", main_script=script1)
    )
    inf_text1, _ = emit(result1.document)
    assert 'powershell.exe -ExecutionPolicy Bypass -NoProfile -File "C:\\Scripts\\test.ps1"' in inf_text1
    assert len(result1.todos) == 0

    # 2. User impersonation
    script_text2 = "CallScriptAs('C:\\Scripts\\test.ps1', '', 'AZDOM\\User', 'secret', 0)\n"
    script_file2 = tmp_path / "Script2.inc"
    script_file2.write_text(script_text2, encoding="utf-8")
    script2 = parse_script(script_text2, script_file2)
    result2 = RuleEngine(load_rules()).transform_package(
        IrPackage(name="UserApp", main_script=script2)
    )
    assert len(result2.todos) == 1
    assert "AZDOM\\User" in result2.todos[0].message


def test_msireinstallproduct_with_errorlevel_check(tmp_path: Path) -> None:
    """MSIReInstallProduct emits CallHidden msiexec.exe /f "{GUID}" /qn followed by ErrorLevel checks."""
    script_text = "MSIReInstallProduct('{F23C7215-F3C6-4CBF-9AF2-820DF17F63A5}', 'TestApp', '64', '1', '0')/TS\n"
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="ReinstApp", main_script=script)
    )
    inf_text, issues = emit(result.document)
    assert 'CallHidden msiexec.exe /f "{F23C7215-F3C6-4CBF-9AF2-820DF17F63A5}" /qn' in inf_text
    assert 'If "%ErrorLevel%" == "3010" Then "RebootRequired" EndIf' in inf_text
    assert 'If "%ErrorLevel%" != "0" Then "AbortMSIInst" EndIf' in inf_text
    assert not any(i.code == "W2004" for i in issues)


def test_executeex_split_command_args_preserves_quoted_spaces(tmp_path: Path) -> None:
    """ExecuteEx with /DIR="C:\\Program Files\\App" preserves the parameter without splitting spaces."""
    script_text = 'ExecuteEx(\'%SRC%\\Setup.exe /VERYSILENT /DIR="C:\\Program Files\\App"\')/TS\n'
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="DirApp", main_script=script)
    )
    inf_text, issues = emit(result.document)
    assert 'CallHidden "%Src%\\Setup.exe" /VERYSILENT /DIR="C:\\Program Files\\App"' in inf_text
    assert not any(i.code == "W2004" for i in issues)


def test_runasex_split_command_args(tmp_path: Path) -> None:
    """RunAsEx splits multiple arguments into individual tokens properly."""
    script_text = 'RunAsEx(\'%WINSYSDIR%\\schtasks.exe\', \'/Create /XML "%SRC%\\Files\\test.xml" /TN "TaskName" /F\', \'\', \'\', \'\', \'\', raUseSisAccount)/TS\n'
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)
    result = RuleEngine(load_rules()).transform_package(
        IrPackage(name="TaskApp", main_script=script)
    )
    inf_text, issues = emit(result.document)
    assert 'CallHidden "%System%\\schtasks.exe" /Create /XML "%Src%\\Files\\test.xml" /TN "TaskName" /F' in inf_text
    assert not any(i.code == "W2004" for i in issues)




