"""Round-trip idempotency tests for Setup.inf Emitter and Parser."""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from dsm2emp.ast.nodes import (
    CallStmt,
    Comment,
    CopyEntry,
    InfDocument,
    KeyValue,
    Section,
    SectionKind,
    SectionRef,
    SetRebootStmt,
    SetStmt,
)
from dsm2emp.emitter import emit
from dsm2emp.io.encoding import read_text
from dsm2emp.validator import parse_setup_inf

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "data" / "templates"


def test_standard_template_roundtrip_idempotence() -> None:
    """Emitting a parsed template and re-parsing must be idempotent."""
    template_names = [
        "MSI_Standard.inf",
        "Unattended_Standard.inf",
        "Skripte_Standard.inf",
        "Links_Standard.inf",
    ]

    for name in template_names:
        tpl_path = TEMPLATES_DIR / name
        assert tpl_path.exists()

        text, _ = read_text(tpl_path)
        doc1 = parse_setup_inf(text)
        emitted1, issues1 = emit(doc1)
        assert not any(i.severity == "error" for i in issues1)

        doc2 = parse_setup_inf(emitted1)
        emitted2, issues2 = emit(doc2)
        assert not any(i.severity == "error" for i in issues2)

        # Byte-identical re-emission: emit(parse(emit(doc))) == emit(doc)
        assert emitted1 == emitted2, f"Roundtrip divergence in {name}"


# Strategy for generating safe alpha-numeric names
name_st = st.from_regex(r"^[A-Za-z][A-Za-z0-9_]{1,15}$", fullmatch=True)
val_st = st.from_regex(r"^[A-Za-z0-9_\-\.\ ]{1,30}$", fullmatch=True)


@settings(max_examples=30, deadline=None)
@given(
    prod_name=name_st,
    version=st.from_regex(r"^[0-9]\.[0-9]$", fullmatch=True),
    reboot_mode=st.integers(min_value=0, max_value=5),
    comment_text=val_st,
)
def test_hypothesis_generated_ast_roundtrip(
    prod_name: str,
    version: str,
    reboot_mode: int,
    comment_text: str,
) -> None:
    """Property test: Generated ASTs serialize and round-trip without divergence."""
    sec_info = Section(
        name="SetupInfo",
        kind=SectionKind.META,
        lines=[
            KeyValue(key="Author", value="Hypothesis"),
            KeyValue(key="Method", value="Custom"),
        ],
    )
    sec_setup = Section(
        name="Setup",
        kind=SectionKind.META,
        lines=[
            KeyValue(key="Version", value="14.2"),
            KeyValue(key="Platform", value="*"),
        ],
    )
    sec_app = Section(
        name="Application",
        kind=SectionKind.META,
        lines=[
            KeyValue(key="ProductName", value=prod_name),
            KeyValue(key="DeveloperName", value="Vendor"),
            KeyValue(key="Version", value=version),
            KeyValue(key="Revision", value="0"),
            KeyValue(key="UserKeyName", value="%DeveloperName%\\%ProductName%"),
            KeyValue(key="MachineKeyName", value="%DeveloperName%\\%ProductName%\\%Version%"),
            KeyValue(key="UninstallKeyName", value="%DeveloperName% %ProductName%"),
            KeyValue(key="UninstallDisplayName", value="%ProductName%"),
            KeyValue(key="UninstallString", value="%ReinstallString% /U"),
            KeyValue(key="ReinstallString", value='"%CommonSetupDir%\\Setup.exe"'),
            KeyValue(key="SrcDir", value=".."),
            KeyValue(key="ApplicationDir", value="%ProgramFilesDir%\\%ProductName%"),
            KeyValue(key="SetupInfDir", value="Install"),
        ],
    )
    sec_prod = Section(
        name="Product",
        kind=SectionKind.WORK,
        lines=[
            SectionRef(target="Set:Product", flags=["DONTDELETE"]),
        ],
    )
    sec_set = Section(
        name="Set:Product",
        kind=SectionKind.WORK,
        lines=[
            Comment(text=comment_text),
            SetStmt(variable="V_Status", value="Ready"),
            CallStmt(program="%Src%\\setup.exe", arguments=["/S"]),
            SetRebootStmt(mode=reboot_mode),
            CopyEntry(
                disk=1,
                source="app.exe",
                destination="%App%\\app.exe",
                flags=["NORMAL"],
                size=5000,
            ),
        ],
    )

    doc = InfDocument(sections=[sec_info, sec_setup, sec_app, sec_prod, sec_set])

    emitted1, issues1 = emit(doc)
    assert not any(i.severity == "error" for i in issues1)

    parsed = parse_setup_inf(emitted1)
    emitted2, issues2 = emit(parsed)
    assert not any(i.severity == "error" for i in issues2)

    # Re-emission must be stable
    assert emitted1 == emitted2
