"""Unit tests for Klasse 1 undocumented interpreter commands and --allow-undocumented flag."""

from pathlib import Path

from dsm2emp.ast.nodes import CallStmt, Command
from dsm2emp.parser.ir import (
    IrCommand,
    IrLiteral,
    IrNode,
    IrPackage,
    IrScript,
    SourceRef,
)
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.loader import load_rules
from dsm2emp.validator.rules import validate_text


def test_val_024_undocumented_commands_warn_by_default() -> None:
    inf_text = """[SetupInfo]
EnableStatus=1

[Setup]
Version=10.5

[Application]
ProductName=TestApp
DeveloperName=Matrix42
Version=1.0

[Product]
CollapseEnv MyVar
Extract
RenDir "C:\\Old" "C:\\New"
BlockInput 1
"""
    # Without allow_undocumented -> warnings for each undocumented command
    issues = validate_text(inf_text, allow_undocumented=False)
    val_024_issues = [i for i in issues if i.code == "VAL-024"]
    assert len(val_024_issues) == 4
    for issue in val_024_issues:
        assert issue.severity == "warning"
        assert "--allow-undocumented" in issue.message


def test_val_024_undocumented_commands_permitted_with_flag() -> None:
    inf_text = """[SetupInfo]
EnableStatus=1

[Setup]
Version=10.5

[Application]
ProductName=TestApp
DeveloperName=Matrix42
Version=1.0

[Product]
CollapseEnv MyVar
Extract
RenDir "C:\\Old" "C:\\New"
BlockInput 1
"""
    # With allow_undocumented=True -> no VAL-024 warnings
    issues = validate_text(inf_text, allow_undocumented=True)
    val_024_issues = [i for i in issues if i.code == "VAL-024"]
    assert len(val_024_issues) == 0


def test_rule_engine_rendir_transformation() -> None:
    ruleset = load_rules()
    src_ref = SourceRef(file=Path("script.inc"), line=1, raw="RenDir OldDir NewDir")
    cmd = IrCommand(
        kind="RenDir",
        raw_args=[IrLiteral(value="OldDir"), IrLiteral(value="NewDir")],
        src=src_ref,
    )
    script = IrScript(file=Path("script.inc"), commands=[cmd])
    pkg = IrPackage(name="App", version="1.0", manufacturer="Matrix42", main_script=script)

    # 1. Without allow_undocumented -> Fallback to cmd.exe
    engine_safe = RuleEngine(ruleset, allow_undocumented=False)
    res_safe = engine_safe.transform_package(pkg)
    product_sec = res_safe.document.section("Set:Product")
    assert product_sec is not None
    call_cmds = [line for line in product_sec.lines if isinstance(line, CallStmt)]
    assert call_cmds[0].program == "cmd.exe"
    assert "ren" in call_cmds[0].arguments

    # 2. With allow_undocumented -> Native RenDir command emitted
    engine_undoc = RuleEngine(ruleset, allow_undocumented=True)
    res_undoc = engine_undoc.transform_package(pkg)
    product_sec_undoc = res_undoc.document.section("Set:Product")
    assert product_sec_undoc is not None
    native_cmds = [
        line
        for line in product_sec_undoc.lines
        if isinstance(line, Command) and line.name == "RenDir"
    ]
    assert len(native_cmds) == 1
    assert native_cmds[0].args == ["OldDir", "NewDir"]


def test_rule_engine_collapseenv_transformation() -> None:
    ruleset = load_rules()
    src_ref = SourceRef(file=Path("script.inc"), line=1, raw="CollapseEnv DynVar")
    cmd = IrCommand(
        kind="CollapseEnv",
        raw_args=[IrLiteral(value="DynVar")],
        src=src_ref,
    )
    script = IrScript(file=Path("script.inc"), commands=[cmd])
    pkg = IrPackage(name="App", version="1.0", manufacturer="Matrix42", main_script=script)

    # 1. Without allow_undocumented -> IrTodo + Comment
    engine_safe = RuleEngine(ruleset, allow_undocumented=False)
    res_safe = engine_safe.transform_package(pkg)
    assert res_safe.todo_count >= 1
    assert any("CollapseEnv" in t.raw for t in res_safe.todos)

    # 2. With allow_undocumented -> Native CollapseEnv command emitted, 0 todos
    engine_undoc = RuleEngine(ruleset, allow_undocumented=True)
    res_undoc = engine_undoc.transform_package(pkg)
    assert res_undoc.todo_count == 0
    product_sec_undoc = res_undoc.document.section("Set:Product")
    assert product_sec_undoc is not None
    native_cmds = [
        line
        for line in product_sec_undoc.lines
        if isinstance(line, Command) and line.name == "CollapseEnv"
    ]
    assert len(native_cmds) == 1
    assert native_cmds[0].args == ["DynVar"]


def test_rule_engine_extract_and_blockinput_transformation() -> None:
    ruleset = load_rules()
    src_ref1 = SourceRef(file=Path("script.inc"), line=1, raw="Extract")
    src_ref2 = SourceRef(file=Path("script.inc"), line=2, raw="BlockInput 1")
    cmds: list[IrNode] = [
        IrCommand(kind="Extract", raw_args=[], src=src_ref1),
        IrCommand(kind="BlockInput", raw_args=[IrLiteral(value="1")], src=src_ref2),
    ]
    script = IrScript(file=Path("script.inc"), commands=cmds)
    pkg = IrPackage(name="App", version="1.0", manufacturer="Matrix42", main_script=script)

    # With allow_undocumented
    engine = RuleEngine(ruleset, allow_undocumented=True)
    res = engine.transform_package(pkg)
    product_sec = res.document.section("Set:Product")
    assert product_sec is not None
    cmd_names = [line.name for line in product_sec.lines if isinstance(line, Command)]
    assert "Extract" in cmd_names
    assert "BlockInput" in cmd_names
