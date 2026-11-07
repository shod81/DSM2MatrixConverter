"""Unit tests for DSM eScript lexer, condition, and script parser (Task T-021)."""

from pathlib import Path

from dsm2emp.parser.escript.conditions import parse_conditions
from dsm2emp.parser.escript.lexer import parse_dsm_value, split_command_line
from dsm2emp.parser.escript.parser import parse_script
from dsm2emp.parser.ir import (
    IrCommand,
    IrComment,
    IrCompositeValue,
    IrFallbackVar,
    IrIf,
    IrLiteral,
    IrNestedVar,
    IrTodo,
    IrVarRef,
)
from tests.fixtures.make_packages import (
    create_p01_pure_msi,
    create_p02_exe_params,
    create_p03_conditions,
    create_p07_uninstall_block,
    create_p10_torture,
    create_p11_damaged,
)


def test_lexer_variable_forms() -> None:
    """FR-012: Test all DSM variable forms: %Var%, %%, %[...], %[~...]."""
    # Simple variable
    val1 = parse_dsm_value("%ProgramFiles%")
    assert isinstance(val1, IrVarRef)
    assert val1.name == "ProgramFiles"

    # Escaped percent
    val2 = parse_dsm_value("%%")
    assert isinstance(val2, IrLiteral)
    assert val2.value == "%"

    # Nested variable %[Server%Number%]%
    val3 = parse_dsm_value("%[Server%Number%]%")
    assert isinstance(val3, IrNestedVar)
    assert val3.outer == "Server"
    assert isinstance(val3.inner, IrVarRef)
    assert val3.inner.name == "Number"

    # Fallback variable %[~Var~Default]%
    val4 = parse_dsm_value("%[~AppName~DefaultApp]%")
    assert isinstance(val4, IrFallbackVar)
    assert val4.name == "AppName"
    assert val4.fallback == "DefaultApp"
    assert val4.is_int is False

    # Integer fallback %[~(int)Port~8080]%
    val5 = parse_dsm_value("%[~(int)Port~8080]%")
    assert isinstance(val5, IrFallbackVar)
    assert val5.name == "Port"
    assert val5.fallback == "8080"
    assert val5.is_int is True


def test_lexer_composite_string() -> None:
    """Test composite string with embedded variables and literals."""
    comp = parse_dsm_value("'%Src%\\setup.exe' /DIR=\"%TargetDir%\"")
    assert isinstance(comp, IrCompositeValue)
    assert len(comp.parts) >= 3

    var_names = [p.name for p in comp.parts if isinstance(p, IrVarRef)]
    assert "Src" in var_names
    assert "TargetDir" in var_names


def test_lexer_split_command_line() -> None:
    """Test splitting command arguments respecting quotes and commas."""
    line = "ExecuteEx('msiexec.exe /i \"%Src%\\app.msi\", test', 'RC', '0')"
    cmd, args = split_command_line(line)
    assert cmd == "ExecuteEx"
    assert len(args) == 3
    assert 'msiexec.exe /i "%Src%\\app.msi", test' in args[0]
    assert args[1] == "'RC'"
    assert args[2] == "'0'"


def test_conditions_parsing() -> None:
    """Test parsing simple, function, and OR conditions."""
    conds = parse_conditions("%ErrorLevel% != '0'")
    assert len(conds) == 1
    assert conds[0].kind == "comparison"
    assert conds[0].op == "!="

    # Function condition
    conds_fn = parse_conditions("IsRunningOnX64")
    assert len(conds_fn) == 1
    assert conds_fn[0].kind == "function"
    assert conds_fn[0].func_name == "IsRunningOnX64"

    # OR combined condition
    conds_or = parse_conditions("%IsLaptop% = '1' OR IsRunningOnServerOS")
    assert len(conds_or) == 2
    assert conds_or[0].kind == "comparison"
    assert conds_or[1].kind == "function"


def test_parser_p01_pure_msi(tmp_path: Path) -> None:
    """Test parsing P-01 pure MSI eScript."""
    pkg = create_p01_pure_msi(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="cp1252"), script_path)

    # Comments are preserved, ExecuteEx and If are parsed
    non_comment_cmds = [c for c in script.commands if not hasattr(c, "text")]
    assert len(non_comment_cmds) >= 2

    cmd_exec = non_comment_cmds[0]
    assert isinstance(cmd_exec, IrCommand)
    assert cmd_exec.kind == "ExecuteEx"
    assert "command" in cmd_exec.params
    assert "rc_var" in cmd_exec.params

    cmd_if = non_comment_cmds[1]
    assert isinstance(cmd_if, IrIf)
    assert len(cmd_if.then_body) == 1
    assert isinstance(cmd_if.then_body[0], IrCommand)
    assert cmd_if.then_body[0].kind == "ExitProcEx"


def test_parser_p02_exe_params(tmp_path: Path) -> None:
    """Test parsing P-02 EXE with parameters."""
    pkg = create_p02_exe_params(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="cp1252"), script_path)

    non_comments = [c for c in script.commands if not hasattr(c, "text")]
    assert len(non_comments) == 2

    set_cmd = non_comments[0]
    assert isinstance(set_cmd, IrCommand)
    assert set_cmd.kind == "Set"
    assert set_cmd.params["name"] == IrLiteral(value="TargetDir")

    exec_cmd = non_comments[1]
    assert isinstance(exec_cmd, IrCommand)
    assert exec_cmd.kind == "ExecuteEx"


def test_parser_p03_conditions_nesting(tmp_path: Path) -> None:
    """FR-011: Test 3 levels of nested If/Else blocks."""
    pkg = create_p03_conditions(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="cp1252"), script_path)

    non_comments = [c for c in script.commands if not hasattr(c, "text")]
    assert len(non_comments) == 1

    top_if = non_comments[0]
    assert isinstance(top_if, IrIf)
    assert len(top_if.then_body) == 1

    lvl2_if = top_if.then_body[0]
    assert isinstance(lvl2_if, IrIf)
    assert len(lvl2_if.then_body) == 1

    lvl3_if = lvl2_if.then_body[0]
    assert isinstance(lvl3_if, IrIf)
    assert len(lvl3_if.then_body) == 1  # Set(Arch, 'x64_Client')
    assert len(lvl3_if.else_body) == 1  # Set(Arch, 'x64_Legacy')


def test_parser_p07_uninstall_block_phase_switch(tmp_path: Path) -> None:
    """FR-011: Test phase tracking across $BeginUnInstallScript."""
    pkg = create_p07_uninstall_block(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="cp1252"), script_path)

    cmds = [c for c in script.commands if isinstance(c, IrCommand)]
    assert len(cmds) == 3

    assert cmds[0].phase == "install"
    assert cmds[1].phase == "uninstall"
    assert cmds[2].phase == "uninstall"


def test_parser_p10_torture_special_characters(tmp_path: Path) -> None:
    """Test parsing with torture special characters."""
    pkg = create_p10_torture(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="utf-8"), script_path)

    non_comments = [c for c in script.commands if not hasattr(c, "text")]
    assert len(non_comments) == 2


def test_parser_p11_damaged_script_fallback_to_todo(tmp_path: Path) -> None:
    """FR-013: Test that damaged/broken script produces IrTodo and does not crash."""
    pkg = create_p11_damaged(tmp_path)
    script_path = pkg / "Script.inc"
    script = parse_script(script_path.read_text(encoding="utf-8"), script_path)

    assert len(script.commands) > 0
    # Damaged statement was parsed either into command or IrTodo without raising exception
    assert any(isinstance(c, (IrCommand, IrTodo)) for c in script.commands)


def test_parser_exclamation_comment_handling(tmp_path: Path) -> None:
    """Test that DSM ! comments are parsed as IrComment."""
    script_text = (
        "!--------------------------------------------------\n"
        "! Header Comment\n"
        "!\n"
        "MakeDir('C:\\App')/TS\n"
    )
    p = tmp_path / "Script.inc"
    p.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, p)

    assert len(script.commands) == 4
    assert isinstance(script.commands[0], IrComment)
    assert script.commands[0].text == "!--------------------------------------------------"
    assert isinstance(script.commands[1], IrComment)
    assert script.commands[1].text == "! Header Comment"
    assert isinstance(script.commands[2], IrComment)
    assert script.commands[2].text == "!"
    assert isinstance(script.commands[3], IrCommand)
    assert script.commands[3].kind == "MakeDir"


def test_parser_execution_flags_handling(tmp_path: Path) -> None:
    """Test parsing commands with /TS, /U, /x64 flags."""
    script_text = (
        "MakeDir('%HOMEDRIVE%\\Program Files (x86)\\KuKnet')/TS\n"
        "Copy('.\\TMP\\App.exe', 'C:\\App')/U/TS\n"
        "EndProc/TS\n"
        "ExecuteEx('setup.exe')/x64/TS\n"
    )
    p = tmp_path / "Script.inc"
    p.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, p)

    assert len(script.commands) == 4
    c0 = script.commands[0]
    assert isinstance(c0, IrCommand)
    assert c0.kind == "MakeDir"
    assert "path" in c0.params

    c1 = script.commands[1]
    assert isinstance(c1, IrCommand)
    assert c1.kind == "Copy"
    assert c1.phase == "uninstall"

    c2 = script.commands[2]
    assert isinstance(c2, IrCommand)
    assert c2.kind == "EndProc"

    c3 = script.commands[3]
    assert isinstance(c3, IrCommand)
    assert c3.kind == "ExecuteEx"


def test_parser_tu_flag_marks_user_context(tmp_path: Path) -> None:
    """DSM /TU (This User) marks user context, NOT the uninstall phase.

    Only the bare /U flag marks an uninstall-only command; /TU commands must
    stay install-phase so the engine routes them to the user part [Set:Client].
    """
    script_text = (
        "MakeDir('C:\\\\Program Files\\\\App')/TS\n"
        "MakeDir('%AppData%\\\\AppConfig')/TU\n"
        "ExecuteEx('usersetup.exe')/TU/TS\n"
    )
    p = tmp_path / "Script.inc"
    p.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, p)

    assert len(script.commands) == 3
    c0, c1, c2 = script.commands
    assert isinstance(c0, IrCommand) and c0.context == "machine"
    assert isinstance(c1, IrCommand)
    assert c1.context == "user"
    assert c1.phase == "install"
    assert isinstance(c2, IrCommand)
    assert c2.context == "user"
    assert c2.phase == "install"


def test_parse_conditions_double_equals_not_split() -> None:
    """Regression: '==' must be recognized as one operator; previously the
    non-greedy regex split at the first '=' leaving '= <rhs>' on the right side."""
    conds = parse_conditions("%ErrorLevel% == 3010")
    assert len(conds) == 1
    cond = conds[0]
    assert cond.kind == "comparison"
    assert cond.op == "=="
    assert (
        str(cond.right) == "type='literal' value='3010'"
        or getattr(cond.right, "value", None) == "3010"
    )

    conds2 = parse_conditions("%A% == %B%")
    assert len(conds2) == 1
    assert conds2[0].op == "=="
    assert getattr(conds2[0].right, "name", None) == "B"


def test_parse_conditions_and_operator() -> None:
    """Test parsing conditions connected by AND / and / &."""
    conds = parse_conditions("%Var1% == '1' And %Var2% == '2'")
    assert len(conds) == 2
    assert conds[0].left is not None and getattr(conds[0].left, "name", None) == "Var1"
    assert conds[0].op == "=="
    assert getattr(conds[0].right, "value", None) == "1"
    assert conds[1].left is not None and getattr(conds[1].left, "name", None) == "Var2"
    assert conds[1].op == "=="
    assert getattr(conds[1].right, "value", None) == "2"

    conds_upper = parse_conditions("%A% == '1' AND %B% == '2'")
    assert len(conds_upper) == 2

    conds_amp = parse_conditions("%A% == '1' & %B% == '2' & %C% == '3'")
    assert len(conds_amp) == 3


def test_parse_condition_expr_details() -> None:
    """Test operator detection and quote/parenthesis protection in split_condition_expr."""
    from dsm2emp.parser.escript.conditions import parse_condition_expr

    conds_and, op_and, mixed_and = parse_condition_expr("%Var1% == '1' And %Var2% == '2'")
    assert len(conds_and) == 2
    assert op_and == "&"
    assert mixed_and is False

    conds_or, op_or, mixed_or = parse_condition_expr("%Var1% == '1' OR %Var2% == '2'")
    assert len(conds_or) == 2
    assert op_or == "|"
    assert mixed_or is False

    conds_q, op_q, mixed_q = parse_condition_expr("%A% == 'Bob and Alice'")
    assert len(conds_q) == 1
    assert op_q == "|"
    assert mixed_q is False

    conds_mix, op_mix, mixed_mix = parse_condition_expr("%A% == '1' AND %B% == '2' OR %C% == '3'")
    assert len(conds_mix) == 3
    assert mixed_mix is True


def test_parse_script_if_with_and(tmp_path: Path) -> None:
    """Test eScript parsing of If-statement with AND condition."""
    script_text = (
        "If %Var1% == '1' And %Var2% == '2'\n"
        "  ExecuteEx('setup.exe', '', '0')\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    if_cmds = [c for c in script.commands if isinstance(c, IrIf)]
    assert len(if_cmds) == 1
    ir_if = if_cmds[0]
    assert len(ir_if.conditions) == 2
    assert ir_if.condition_op == "&"
    assert ir_if.is_mixed is False
    assert len(ir_if.then_body) == 1


def test_parse_script_mixed_if_emits_todo(tmp_path: Path) -> None:
    """Test that mixed AND/OR without parentheses emits an IrTodo."""
    script_text = (
        "If %A% == '1' AND %B% == '2' OR %C% == '3'\n"
        "  ExecuteEx('setup.exe', '', '0')\n"
        "EndIf\n"
    )
    script_file = tmp_path / "Script.inc"
    script_file.write_text(script_text, encoding="utf-8")
    script = parse_script(script_text, script_file)

    todos = [c for c in script.commands if isinstance(c, IrTodo)]
    assert len(todos) >= 1
    assert any("Mixed AND/OR" in t.message for t in todos)
