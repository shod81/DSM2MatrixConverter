"""Unit tests for the Setup.inf document emitter."""

from dsm2emp.ast import (
    CallStmt,
    Comment,
    Comparison,
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
    ShellEntry,
    VarRef,
)
from dsm2emp.emitter.render import EmitOptions, emit


def test_canonical_section_ordering() -> None:
    """Sections must be emitted in canonical order regardless of input list order."""
    sec_shell = Section(name="Shell:Product", kind=SectionKind.TYPED, lines=[])
    sec_prod = Section(name="Product", kind=SectionKind.WORK, lines=[])
    sec_app = Section(name="Application", kind=SectionKind.META, lines=[])
    sec_info = Section(name="SetupInfo", kind=SectionKind.META, lines=[])
    sec_setup = Section(name="Setup", kind=SectionKind.META, lines=[])
    sec_set = Section(name="Set:Product", kind=SectionKind.WORK, lines=[])
    sec_reg = Section(name="Reg:Product", kind=SectionKind.TYPED, lines=[])

    doc = InfDocument(
        sections=[sec_shell, sec_prod, sec_app, sec_info, sec_setup, sec_set, sec_reg]
    )

    rendered, issues = emit(doc)
    assert not issues

    indices = [
        rendered.index("[SetupInfo]"),
        rendered.index("[Setup]"),
        rendered.index("[Application]"),
        rendered.index("[Product]"),
        rendered.index("[Set:Product]"),
        rendered.index("[Reg:Product]"),
        rendered.index("[Shell:Product]"),
    ]
    # Check that indices are strictly increasing
    assert indices == sorted(indices)


def test_crlf_line_endings() -> None:
    """Emitter must emit CRLF by default."""
    sec = Section(
        name="Setup",
        kind=SectionKind.META,
        lines=[KeyValue(key="Version", value="14.2")],
    )
    doc = InfDocument(sections=[sec])
    rendered, _ = emit(doc, opts=EmitOptions(crlf=True))

    assert "\r\n" in rendered
    assert "\r\r\n" not in rendered
    assert rendered.endswith("\r\n")


def test_full_sample_standard_emission() -> None:
    """Emit a complete sample package following the package standard conventions."""
    sec_info = Section(
        name="SetupInfo",
        kind=SectionKind.META,
        lines=[
            KeyValue(key="Author", value="IT-Packaging"),
            KeyValue(key="Method", value="MSI"),
            KeyValue(key="Command line options", value="/S2"),
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
            KeyValue(key="ProductName", value="7-Zip"),
            KeyValue(key="DeveloperName", value="Igor Pavlov"),
            KeyValue(key="Version", value="24.05"),
            KeyValue(key="Revision", value="0"),
            KeyValue(
                key="ApplicationDir",
                value="%CommonAppData%\\$Matrix42Scripts$\\%DeveloperName%\\%ProductName%\\%Version%",
            ),
            KeyValue(key="SetupInfDir", value="Install"),
            KeyValue(key="SrcDir", value=".."),
        ],
    )

    sec_prod = Section(
        name="Product",
        kind=SectionKind.WORK,
        lines=[
            SectionRef(target="Set:Product", flags=["DONTDELETE"]),
            SectionRef(target="Reg:Product", flags=["DONTDELETE"]),
            SectionRef(target="Set:Uninstall", flags=["DELETE"]),
        ],
    )

    sec_set_prod = Section(
        name="Set:Product",
        kind=SectionKind.WORK,
        lines=[
            Comment(text="Install MSI package"),
            SetStmt(
                variable="MSIGUID",
                value=LiteralValue(text="{23170F69-40C1-2702-2405-000001000000}"),
            ),
            CallStmt(
                program="MsiExec",
                arguments=[
                    "/I",
                    '"%Src%\\7z2405-x64.msi"',
                    "/qn",
                    "REBOOT=REALLYSUPPRESS",
                ],
            ),
            IfStmt(
                condition=Comparison(
                    left=VarRef(name="ErrorLevel"),
                    relation="==",
                    right="3010",
                ),
                then_target="RebootRequired",
            ),
        ],
    )

    sec_reboot = Section(
        name="RebootRequired",
        kind=SectionKind.WORK,
        lines=[
            SetRebootStmt(mode=1, uninstall_only=False),
            SetRebootStmt(mode=1, uninstall_only=True),
        ],
    )

    sec_reg = Section(
        name="Reg:Product",
        kind=SectionKind.TYPED,
        lines=[
            RegEntry(
                root="HKLM",
                key="Software\\Matrix42Packages\\Igor Pavlov\\7-Zip",
                value_name="Configured",
                type_flag="0x00010001",
                data=["1"],
            )
        ],
    )

    sec_shell = Section(
        name="Shell:Product",
        kind=SectionKind.TYPED,
        lines=[
            ShellEntry(
                link="%CommonPrograms%\\7-Zip",
                command="%ProgramFilesDir%\\7-Zip\\7zFM.exe",
                arguments="",
                workdir="%ProgramFilesDir%\\7-Zip",
                description="7-Zip File Manager",
                icon_file="%ProgramFilesDir%\\7-Zip\\7zFM.exe",
                icon_index=0,
            )
        ],
    )

    doc = InfDocument(
        sections=[
            sec_info,
            sec_setup,
            sec_app,
            sec_prod,
            sec_set_prod,
            sec_reboot,
            sec_reg,
            sec_shell,
        ]
    )

    rendered, issues = emit(doc)
    assert not issues
    assert "[SetupInfo]" in rendered
    assert "[Application]" in rendered
    assert "[Set:Product]" in rendered
    assert 'CallHidden MsiExec /I "%Src%\\7z2405-x64.msi" /qn REBOOT=REALLYSUPPRESS' in rendered
    assert 'If "%ErrorLevel%" == "3010" Then "RebootRequired" EndIf' in rendered
    assert "-SetReboot 1" in rendered
    assert "HKLM," in rendered
