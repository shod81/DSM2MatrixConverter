"""Unit tests for AST models, nodes, and immutability."""

import pytest
from pydantic import ValidationError

from dsm2emp.ast import (
    CallStmt,
    Comment,
    Comparison,
    CopyEntry,
    IfStmt,
    InfDocument,
    KeyValue,
    LiteralValue,
    RegEntry,
    Section,
    SectionKind,
    SectionRef,
    SetRebootStmt,
    SetStmt,
    VarRef,
)


def test_immutability() -> None:
    val = LiteralValue(text="hello")
    with pytest.raises(ValidationError):
        val.text = "world"

    cmd = SetRebootStmt(mode=1)
    with pytest.raises(ValidationError):
        cmd.mode = 0


def test_section_lookup() -> None:
    sec_info = Section(
        name="SetupInfo",
        kind=SectionKind.META,
        lines=[
            KeyValue(key="Author", value="Admin"),
            KeyValue(key="Method", value="MSI"),
        ],
    )
    sec_prod = Section(
        name="Product",
        kind=SectionKind.WORK,
        lines=[
            SectionRef(target="Set:Product", flags=["DONTDELETE"]),
            SectionRef(target="Set:Uninstall", flags=["DELETE"]),
        ],
    )

    doc = InfDocument(sections=[sec_info, sec_prod])

    assert doc.section("setupinfo") is not None
    assert doc.section("Product") is not None
    assert doc.section("NonExistent") is None
    assert doc.product().name == "Product"


def test_missing_product_raises() -> None:
    doc = InfDocument(sections=[])
    with pytest.raises(ValueError, match="no mandatory \\[Product\\]"):
        doc.product()


def test_ast_serialization_roundtrip() -> None:
    stmt = IfStmt(
        condition=Comparison(
            left=VarRef(name="ErrorLevel"),
            relation="==",
            right=LiteralValue(text="3010"),
        ),
        then_target="RebootRequired",
    )

    copy_line = CopyEntry(
        disk=1,
        source="setup.exe",
        destination="%App%\\setup.exe",
        flags=["ALWAYS", "NOSIZEWARNING"],
        size=1024,
    )

    reg_line = RegEntry(
        root="HKLM",
        key="Software\\ExampleApp",
        value_name="Installed",
        type_flag="0x00010001",
        data=["1"],
    )

    sec = Section(
        name="Set:Product",
        kind=SectionKind.WORK,
        lines=[
            Comment(text="Install section"),
            SetStmt(variable="V_Status", value="Ready"),
            CallStmt(program="%Src%\\setup.exe", arguments=["/S"]),
            stmt,
            copy_line,
            reg_line,
        ],
    )

    data = sec.model_dump()
    reconstructed = Section.model_validate(data)
    assert reconstructed == sec
