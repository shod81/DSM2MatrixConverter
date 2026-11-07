"""Tests for reference data and YAML definitions."""

from dsm2emp.reference import (
    get_commands,
    get_flags,
    get_functions,
    get_package_standard,
    get_sections,
    get_variables,
)


def test_sections_reference() -> None:
    """Verify that required Empirum sections exist and have required keys."""
    sections = get_sections()
    assert "setupinfo" in sections
    assert "application" in sections
    assert "setup" in sections
    assert "environment" in sections
    assert "product" in sections

    app_sec = sections["application"]
    app_keys = {k.name for k in app_sec.allowed_keys}
    assert "ProductName" in app_keys
    assert "DeveloperName" in app_keys
    assert "Version" in app_keys
    assert "Revision" in app_keys
    assert "UserKeyName" in app_keys
    assert "MachineKeyName" in app_keys
    assert "UninstallKeyName" in app_keys
    assert "ApplicationDir" in app_keys
    assert "SrcDir" in app_keys
    assert "SetupInfDir" in app_keys


def test_commands_reference() -> None:
    """Verify core Empirum commands."""
    commands = get_commands()
    assert "call" in commands
    assert "callhidden" in commands
    assert "sleep" in commands
    assert "if" in commands
    assert "for" in commands
    assert "killprocess" in commands
    assert "askkillprocesses" in commands
    assert "setreboot" in commands
    assert "errorlogmsg" in commands
    assert "abort" in commands
    assert "exit" in commands
    assert "set" in commands
    assert "replaceenv" in commands

    call_cmd = commands["call"]
    assert call_cmd.sets_errorlevel is True


def test_flags_reference() -> None:
    """Verify section, copy, and registry flags."""
    flags = get_flags()
    assert "DONTDELETE" in flags["section_flags"]
    assert "DELETE" in flags["section_flags"]
    assert "CLIENT" in flags["section_flags"]
    assert "MACHINE" in flags["section_flags"]

    assert "ALWAYS" in flags["copy_flags"]
    assert "REPLACEOLDER" in flags["copy_flags"]
    assert "DONTDELETE" in flags["copy_flags"]

    assert "0x00000000" in flags["reg_flags"]
    assert flags["reg_flags"]["0x00000000"].type_name == "REG_SZ"
    assert "0x00010001" in flags["reg_flags"]
    assert flags["reg_flags"]["0x00010001"].type_name == "REG_DWORD"


def test_variables_reference() -> None:
    """Verify variable mappings."""
    vars_data = get_variables()
    emp_vars = vars_data["empirum"]
    assert "app" in emp_vars
    assert "src" in emp_vars
    assert "windows" in emp_vars
    assert "system" in emp_vars
    assert "temp" in emp_vars

    dsm_map = {m.dsm.lower(): m.empirum for m in vars_data["dsm_mapping"]}
    assert dsm_map["%windir%"] == "%Windows%"
    assert dsm_map["%winsysdir%"] == "%System%"
    assert dsm_map["%programfiles%"] == "%ProgramFilesDir%"
    assert dsm_map["%temp%"] == "%Temp%"


def test_functions_reference() -> None:
    """Verify If condition functions."""
    funcs = get_functions()
    assert "doesfileexist" in funcs
    assert "doesregkeyexist" in funcs
    assert "doesprocessexist" in funcs
    assert "getuninstallkeyname" in funcs
    assert "fileversion" in funcs


def test_package_standard_reference() -> None:
    """Verify the package standard YAML."""
    standard = get_package_standard()
    assert standard["package_standard"]["version"] == "1.0"
    conventions = standard["package_standard"]["conventions"]
    assert "$Matrix42Scripts$" in conventions["application_dir"]
    assert "$Matrix42Packages$" in conventions["registry"]["user_key_name"]
    assert conventions["reboot_handling"]["section_name"] == "RebootRequired"
    assert conventions["reboot_handling"]["errorlevel_trigger"] == "3010"

    templates = standard["package_standard"]["templates"]
    assert "msi" in templates
    assert "unattended" in templates
    assert "skripte" in templates
    assert "links" in templates
