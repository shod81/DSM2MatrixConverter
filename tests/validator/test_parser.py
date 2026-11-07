"""Unit tests for the Empirum Setup.inf parser."""

from pathlib import Path

from dsm2emp.ast import (
    CallStmt,
    IfStmt,
    KeyValue,
    SectionRef,
)
from dsm2emp.io.encoding import read_text
from dsm2emp.validator.parser import parse_setup_inf

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "data" / "templates"


def test_parse_simple_inf() -> None:
    text = """[SetupInfo]
Author=Admin
Method=MSI

[Setup]
Version=14.2
Platform=*

[Application]
ProductName=TestApp
DeveloperName=TestDev
Version=1.0
Revision=0

[Product]
#Set:Product, DONTDELETE
#Set:Uninstall, DELETE

[Set:Product]
Set MSIGUID={12345678-ABCD}
Call MsiExec /I "%Src%\\setup.msi" /qn
If "%ErrorLevel%" == "3010" Then "RebootRequired" EndIf

[RebootRequired]
SetReboot 1
-SetReboot 1
"""
    doc = parse_setup_inf(text)

    assert doc.section("SetupInfo") is not None
    assert doc.section("Product") is not None
    assert doc.section("Set:Product") is not None
    assert doc.section("RebootRequired") is not None

    setup_info = doc.section("SetupInfo")
    assert setup_info is not None
    keys = {line.key: line.value for line in setup_info.lines if isinstance(line, KeyValue)}
    assert keys["Author"] == "Admin"
    assert keys["Method"] == "MSI"

    prod_sec = doc.section("Product")
    assert prod_sec is not None
    refs = [line for line in prod_sec.lines if isinstance(line, SectionRef)]
    assert len(refs) == 2
    assert refs[0].target == "Set:Product"
    assert "DONTDELETE" in refs[0].flags

    set_prod = doc.section("Set:Product")
    assert set_prod is not None
    calls = [line for line in set_prod.lines if isinstance(line, CallStmt)]
    assert len(calls) == 1
    assert calls[0].program == "MsiExec"

    ifs = [line for line in set_prod.lines if isinstance(line, IfStmt)]
    assert len(ifs) == 1
    assert ifs[0].then_target == "RebootRequired"


def test_parse_msi_standard_template() -> None:
    template_path = TEMPLATES_DIR / "MSI_Standard.inf"
    assert template_path.exists()

    text, _ = read_text(template_path)
    doc = parse_setup_inf(text)

    assert doc.section("SetupInfo") is not None
    assert doc.section("Setup") is not None
    assert doc.section("Application") is not None
    assert doc.section("Environment") is not None
    assert doc.section("Product") is not None
    assert doc.section("Set:Product") is not None
    assert doc.section("InstallMSI") is not None
    assert doc.section("RepairMSI") is not None
    assert doc.section("Set:Uninstall") is not None
    assert doc.section("RebootRequired") is not None


def test_parse_unattended_standard_template() -> None:
    template_path = TEMPLATES_DIR / "Unattended_Standard.inf"
    assert template_path.exists()

    text, _ = read_text(template_path)
    doc = parse_setup_inf(text)

    assert doc.section("SetupInfo") is not None
    assert doc.section("Application") is not None
    assert doc.section("Processes") is not None
    assert doc.section("Set:AppActive") is not None
    assert doc.section("Set:Product") is not None
    assert doc.section("Installation") is not None
    assert doc.section("Repair") is not None


def test_parse_skripte_standard_template() -> None:
    template_path = TEMPLATES_DIR / "Skripte_Standard.inf"
    assert template_path.exists()

    text, _ = read_text(template_path)
    doc = parse_setup_inf(text)

    assert doc.section("SetupInfo") is not None
    assert doc.section("Application") is not None
    assert doc.section("Product") is not None


def test_parse_links_standard_template() -> None:
    template_path = TEMPLATES_DIR / "Links_Standard.inf"
    assert template_path.exists()

    text, _ = read_text(template_path)
    doc = parse_setup_inf(text)

    assert doc.section("SetupInfo") is not None
    assert doc.section("Application") is not None
    assert doc.section("Shell:Product") is not None
