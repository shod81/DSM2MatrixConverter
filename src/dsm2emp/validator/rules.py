import re
from pathlib import Path

from dsm2emp.ast.nodes import (
    CallStmt,
    Command,
    IfStmt,
    InfDocument,
    KeyValue,
    RegEntry,
    SectionRef,
    SetRebootStmt,
)
from dsm2emp.ast.values import LiteralValue
from dsm2emp.emitter.quote import Issue, validate_percent_count
from dsm2emp.io.encoding import read_text
from dsm2emp.reference import get_commands, get_flags, get_sections
from dsm2emp.validator.parser import parse_setup_inf


def validate_document(doc: InfDocument) -> list[Issue]:
    """Perform semantic validation on an InfDocument AST."""
    issues: list[Issue] = []
    sec_defs = get_sections()
    cmd_defs = get_commands()
    flag_defs = get_flags()

    # 1. Check duplicate sections
    seen_sections: set[str] = set()
    existing_sections: set[str] = set()
    for sec in doc.sections:
        name_lower = sec.name.strip().lower()
        existing_sections.add(name_lower)
        if name_lower in seen_sections:
            issues.append(
                Issue(
                    code="E1001",
                    message=f"Duplicate section: [{sec.name}]",
                    severity="error",
                )
            )
        seen_sections.add(name_lower)

    # 2. Check mandatory sections
    for req_sec_name in ("setupinfo", "setup", "application", "product"):
        if req_sec_name not in existing_sections:
            issues.append(
                Issue(
                    code="E1002",
                    message=f"Mandatory section missing: [{req_sec_name.title()}]",
                    severity="error",
                )
            )

    # 3. Check [Application] mandatory keys
    app_sec = doc.section("application")
    if app_sec is not None:
        app_keys = {
            line.key.lower(): line.value for line in app_sec.lines if isinstance(line, KeyValue)
        }
        app_def = sec_defs.get("application")
        if app_def:
            for req_key in app_def.allowed_keys:
                if req_key.required and req_key.name.lower() not in app_keys:
                    issues.append(
                        Issue(
                            code="E1003",
                            message=f"Mandatory key '{req_key.name}' missing in [Application]",
                            severity="error",
                            field=req_key.name,
                        )
                    )

    # 4. Check [Setup] Version and Platform
    setup_sec = doc.section("setup")
    if setup_sec is not None:
        setup_keys = {
            line.key.lower(): str(line.value)
            for line in setup_sec.lines
            if isinstance(line, KeyValue)
        }
        if "version" not in setup_keys:
            issues.append(
                Issue(
                    code="E1006",
                    message="Setup engine Version missing in [Setup]",
                    severity="error",
                )
            )
        if "platform" in setup_keys:
            plat = setup_keys["platform"].strip()
            if plat not in ("x86", "x86os", "x64", "*"):
                issues.append(
                    Issue(
                        code="W2006",
                        message=f"Unknown or non-standard Platform '{plat}' in [Setup]",
                        severity="warning",
                    )
                )

    # 5. Check Section References & If Targets
    referenced_sections: set[str] = {"product"}
    for sec in doc.sections:
        for line in sec.lines:
            if isinstance(line, SectionRef):
                target_lower = line.target.strip().lower()
                referenced_sections.add(target_lower)
                if target_lower not in existing_sections:
                    issues.append(
                        Issue(
                            code="E1007",
                            message=f"Section '#{line.target}' called in [{sec.name}] missing",
                            severity="error",
                        )
                    )
                # Check section flags
                for flag in line.flags:
                    if flag.upper() not in flag_defs["section_flags"]:
                        issues.append(
                            Issue(
                                code="W2007",
                                message=f"Unknown section flag '{flag}' on '#{line.target}'",
                                severity="warning",
                            )
                        )

            elif isinstance(line, IfStmt):
                then_lower = line.then_target.strip().lower()
                referenced_sections.add(then_lower)
                if then_lower not in existing_sections:
                    issues.append(
                        Issue(
                            code="E1007",
                            message=f"Then target '{line.then_target}' does not exist",
                            severity="error",
                        )
                    )
                if line.else_target:
                    else_lower = line.else_target.strip().lower()
                    referenced_sections.add(else_lower)
                    if else_lower not in existing_sections:
                        issues.append(
                            Issue(
                                code="E1007",
                                message=f"Else target '{line.else_target}' does not exist",
                                severity="error",
                            )
                        )

            elif isinstance(line, SetRebootStmt):
                if line.mode not in range(0, 6):
                    issues.append(
                        Issue(
                            code="E1008",
                            message=f"Invalid SetReboot mode '{line.mode}' (allowed: 0..5)",
                            severity="error",
                        )
                    )

            elif isinstance(line, Command):
                cmd_lower = line.name.strip().lower()
                recognized_specials = (
                    "addmeter",
                    "askkillprocesses",
                    "closewindow",
                    "killprocess",
                    "md",
                    "mkdir",
                    "rd",
                    "rmdir",
                    "deltree",
                    "replaceenv",
                )
                if cmd_lower == "deltree":
                    for arg in line.args:
                        raw_arg = arg.text if isinstance(arg, LiteralValue) else str(arg)
                        clean_arg = raw_arg.strip('"').strip("'")
                        if clean_arg.endswith("\\") or clean_arg.endswith("/"):
                            issues.append(
                                Issue(
                                    code="VAL-003",
                                    message=(
                                        f"DelTree path '{raw_arg}' in [{sec.name}] has a trailing backslash "
                                        "which causes Setup.exe to fail (VAL-003)"
                                    ),
                                    severity="error",
                                )
                            )

                if cmd_lower not in cmd_defs and cmd_lower not in recognized_specials:
                    issues.append(
                        Issue(
                            code="W2008",
                            message=f"Unrecognized command '{line.name}' in [{sec.name}]",
                            severity="warning",
                        )
                    )

        # VAL-004: Missing '-' prefix in deinstallation error sections
        if sec.name.lower() in ("set:deinstallationerror", "abortmsiuninst"):
            for line in sec.lines:
                if isinstance(line, Command) and line.name.lower() in ("abort", "errorlogmsg"):
                    if not line.uninstall_only:
                        issues.append(
                            Issue(
                                code="VAL-004",
                                message=(
                                    f"Command '{line.name}' in [{sec.name}] lacks the '-' prefix required "
                                    "for execution during uninstallation (/U) (VAL-004)"
                                ),
                                severity="error",
                            )
                        )

    # 6. Check unreferenced custom work sections
    # Standard error sections from the classic Matrix42 package template are
    # shipped by design as unreferenced fallback targets (the engine's own If
    # jumps go to AbortMSIInst/RebootRequired instead) - never flag them.
    STANDARD_ERROR_SECTIONS = {
        "set:installationerror",
        "set:reinstallationerror",
        "set:deinstallationerror",
    }
    for sec in doc.sections:
        name_lower = sec.name.strip().lower()
        if (
            name_lower.startswith("set:")
            or name_lower.startswith("reg:")
            or name_lower.startswith("ini:")
        ):
            if (
                name_lower not in referenced_sections
                and name_lower != "reg:product"
                and name_lower not in STANDARD_ERROR_SECTIONS
            ):
                issues.append(
                    Issue(
                        code="W2009",
                        message=f"Section [{sec.name}] is defined but never called or referenced",
                        severity="warning",
                    )
                )

    # 7. VAL-005: Duplicated ShellLinks Call
    prod_sec = doc.section("product")
    if app_sec and prod_sec:
        app_keys = {
            line.key.lower(): str(line.value).strip()
            for line in app_sec.lines
            if isinstance(line, KeyValue)
        }
        if app_keys.get("shelllinks") in ("1", "true"):
            for line in prod_sec.lines:
                if isinstance(line, SectionRef) and line.target.lower() == "shell:product":
                    issues.append(
                        Issue(
                            code="VAL-005",
                            message=(
                                "[Product] calls #Shell:Product while ShellLinks=1 in [Application]; "
                                "Setup.exe executes [Shell:Product] automatically, resulting in duplicate "
                                "shortcuts (VAL-005)"
                            ),
                            severity="warning",
                        )
                    )

    # 8. VAL-006: HKCU without /AW
    setupinfo_sec = doc.section("setupinfo")
    has_aw = False
    if setupinfo_sec:
        info_keys = {
            line.key.lower(): str(line.value)
            for line in setupinfo_sec.lines
            if isinstance(line, KeyValue)
        }
        has_aw = "/aw" in info_keys.get("command line options", "").lower()

    has_client_flag = any(
        any(f.upper() == "CLIENT" for f in line.flags)
        for sec in doc.sections
        for line in sec.lines
        if isinstance(line, SectionRef)
    )

    has_hkcu = False
    for sec in doc.sections:
        if sec.name.lower().startswith("reg:"):
            for line in sec.lines:
                if isinstance(line, RegEntry) and line.root.upper() in ("HKCU", "HKEY_CURRENT_USER"):
                    has_hkcu = True
                    break
        elif sec.name.lower().startswith("set:"):
            for line in sec.lines:
                if isinstance(line, Command):
                    cmd_text = " ".join(
                        arg.text if isinstance(arg, LiteralValue) else str(arg)
                        for arg in line.args
                    ).lower()
                    if "hkcu" in cmd_text or "hkey_current_user" in cmd_text:
                        has_hkcu = True
                        break
        if has_hkcu:
            break

    if has_hkcu and not (has_aw or has_client_flag):
        issues.append(
            Issue(
                code="VAL-006",
                message=(
                    "HKCU registry entries found but [SetupInfo] 'Command line options' lacks '/AW' "
                    "and no section has CLIENT flag; settings will not apply to end users (VAL-006)"
                ),
                severity="warning",
            )
        )

    # 9. VAL-007: Dangerous Root Deletion in Registry
    dangerous_roots = {
        "software\\microsoft",
        "software\\classes",
        "software\\windows",
        "software",
        "system",
    }
    for sec in doc.sections:
        if sec.name.lower().startswith("reg:"):
            for line in sec.lines:
                if isinstance(line, RegEntry) and line.delete and not line.value_name:
                    clean_k = line.key.strip("\\/ ").lower()
                    if clean_k in dangerous_roots:
                        issues.append(
                            Issue(
                                code="VAL-007",
                                message=(
                                    f"Dangerous root deletion '-{line.root},{line.key}' in [{sec.name}] "
                                    "may delete shared operating system or vendor trees (VAL-007)"
                                ),
                                severity="warning",
                            )
                        )

    # 10. VAL-008: Missing ErrorLevel handling after MSI / Setup Call
    for sec in doc.sections:
        if sec.name.lower().startswith("set:"):
            for i, line in enumerate(sec.lines):
                if isinstance(line, CallStmt):
                    prog = line.program.lower()
                    is_msi = "msiexec" in prog or prog.endswith(".msi")
                    if is_msi:
                        # In forward execution, ErrorLevel check follows the call (sec.lines[i + 1 :]).
                        # In reverse uninstall execution, ErrorLevel check precedes the call in text order (sec.lines[:i]).
                        has_rc_check = any(
                            isinstance(nxt, IfStmt)
                            and (
                                "errorlevel" in str(nxt.condition).lower()
                                or "doesregkeyexist" in str(nxt.condition).lower()
                            )
                            for nxt in sec.lines
                        )
                        if not has_rc_check:
                            issues.append(
                                Issue(
                                    code="VAL-008",
                                    message=(
                                        f"MSI installer call '{line.program}' in [{sec.name}] not followed by "
                                        "%ErrorLevel% check (VAL-008)"
                                    ),
                                    severity="warning",
                                )
                            )

    # 11. VAL-009: Uncontrolled Reboot
    if app_sec:
        app_keys = {
            line.key.lower(): str(line.value).strip()
            for line in app_sec.lines
            if isinstance(line, KeyValue)
        }
        if app_keys.get("reboot") == "1":
            issues.append(
                Issue(
                    code="VAL-009",
                    message=(
                        "Unconditional 'Reboot=1' in [Application]; use 'Reboot=0' with dynamic "
                        "ErrorLevel 3010 check instead (VAL-009)"
                    ),
                    severity="warning",
                )
            )

    # 12. VAL-010: Hardcoded System Path
    for sec in doc.sections:
        if sec.name.lower().startswith("set:"):
            for line in sec.lines:
                if isinstance(line, Command):
                    for arg in line.args:
                        arg_text = (arg.text if isinstance(arg, LiteralValue) else str(arg)).lower()
                        if re.search(r"[a-z]:\\(?:program files|windows|users\\public)", arg_text):
                            issues.append(
                                Issue(
                                    code="VAL-010",
                                    message=(
                                        f"Hardcoded system path in [{sec.name}]: '{arg_text}'. "
                                        "Use %ProgramFilesDir% or %Windows% instead (VAL-010)"
                                    ),
                                    severity="info",
                                )
                            )
                            break

    return issues


def validate_fragment(command_text: str, target_section: str = "Set:Product") -> list[Issue]:
    """Validate a single command or fragment (e.g. from AI translation) against Empirum rules."""
    issues: list[Issue] = []

    # 1. Quoting check (unbalanced double quotes)
    if command_text.count('"') % 2 != 0:
        issues.append(
            Issue(
                code="E1004",
                message=f"Unbalanced double quotes in command: '{command_text}'",
                severity="error",
            )
        )

    # 2. Percent sign balance check
    validate_percent_count(command_text, issues=issues)

    # 3. Parse check
    try:
        test_inf = f"[{target_section}]\n{command_text}\n"
        doc = parse_setup_inf(test_inf)
        sec = doc.section(target_section)
        if not sec or not sec.lines:
            issues.append(
                Issue(
                    code="E1000",
                    message="No valid AST lines parsed from command",
                    severity="error",
                )
            )
    except Exception as ex:
        issues.append(
            Issue(
                code="E1000",
                message=f"Syntax error in command: {ex}",
                severity="error",
            )
        )

    return issues


def _non_cp1252_chars_in_text(text: str) -> dict[int, set[str]]:
    """Return {line_number: offending_chars} for characters not encodable in Windows-1252."""
    result: dict[int, set[str]] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        bad: set[str] = set()
        for ch in line:
            try:
                ch.encode("cp1252")
            except UnicodeEncodeError:
                bad.add(ch)
        if bad:
            result[line_no] = bad
    return result


def _encoding_issues_for_text(text: str) -> list[Issue]:
    """VAL-030/VAL-031: Setup.inf must be ANSI (Windows-1252) without BOM.

    The Empirum Setup interpreter and the Package Editor read the file as ANSI;
    a UTF-8 BOM corrupts the first section header so the interpreter exits
    immediately ("flash and gone") and the debugger cannot even start.
    """
    issues: list[Issue] = []

    if text.startswith("\ufeff") or text.startswith("\xef\xbb\xbf"):
        issues.append(
            Issue(
                code="VAL-030",
                message=(
                    "Setup.inf starts with a UTF-8 BOM; Empirum Setup.exe and the "
                    "Package Editor expect ANSI/Windows-1252 without BOM and abort immediately "
                    "on BOM-prefixed files (VAL-030)"
                ),
                severity="error",
            )
        )
        text = text.removeprefix("\ufeff").removeprefix("\xef\xbb\xbf")

    non_cp1252 = _non_cp1252_chars_in_text(text)
    if non_cp1252:
        sample = "; ".join(
            f"line {ln}: {''.join(sorted(chs))!r}" for ln, chs in list(non_cp1252.items())[:3]
        )
        issues.append(
            Issue(
                code="VAL-031",
                message=(
                    "Characters not representable in Windows-1252 (ANSI) found in Setup.inf - "
                    f"{sample}. Empirum reads ANSI only; replace these characters in the "
                    "source package (VAL-031)"
                ),
                severity="error",
            )
        )

    return issues


def validate_text(
    text: str, allow_undocumented: bool = False, check_encoding: bool = True
) -> list[Issue]:
    """Validate raw Setup.inf text for encoding, percent balance and semantic validity."""
    issues: list[Issue] = []

    if check_encoding:
        issues.extend(_encoding_issues_for_text(text))

    text = text.lstrip("\ufeff\xef\xbb\xbf")

    # Text-level validation
    for _line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith(";") and not line.lower().startswith("rem "):
            validate_percent_count(line, issues=issues)
            if line.count('"') % 2 != 0:
                issues.append(
                    Issue(
                        code="E1004",
                        message=f"Unbalanced double quotes in line: '{line}'",
                        severity="error",
                    )
                )

            # VAL-002: Quoted Function Predicate in If statement
            m_val002 = re.search(
                r'(?i)^\s*-?if\s+"(DoesFileExist|DoesPathExist|DoesRegKeyExist|DoesProcessExist|DoesTextInFileExist|FileVersion|FileSize|IsDotNetVersionAvailable|GetDiskFreeSpaceKB)\s*\(',
                line,
            )
            if m_val002:
                issues.append(
                    Issue(
                        code="VAL-002",
                        message=(
                            f"Function predicate '{m_val002.group(1)}' in If statement must not be enclosed "
                            "in quotes; Empirum will perform string comparison instead of executing function (VAL-002)"
                        ),
                        severity="error",
                    )
                )

            # VAL-022: Non-existent alias predicates (K-02)
            m_val022 = re.search(
                r'(?i)^\s*-?if\b.*\b(DirExists|FileExists|ProcessExists|RegKeyExists|RegValueExists|DoesDirExist|DoesServiceExist|ServiceExists|DoesRegValueExist)\s*\(',
                line,
            )
            if m_val022:
                issues.append(
                    Issue(
                        code="VAL-022",
                        message=(
                            f"Non-existent predicate '{m_val022.group(1)}' in If statement (K-02); "
                            "not supported by Empirum Setup interpreter v26.1.0 and will fail silently. "
                            "Use valid predicate (e.g. DoesFileExist, DoesPathExist, DoesProcessExist, DoesRegKeyExist)."
                        ),
                        severity="error",
                    )
                )

            # VAL-023: Deprecated/non-existent CheckLanAdministrator (K-01)
            if re.search(r'(?i)^\s*-?checklanadministrator\b', line):
                issues.append(
                    Issue(
                        code="VAL-023",
                        message=(
                            "Command 'CheckLanAdministrator' does not exist in "
                            "Empirum Setup interpreter v26.1.0 (K-01)"
                        ),
                        severity="error",
                    )
                )

            # VAL-024: Undocumented interpreter command (Klasse 1) without feature flag
            if not allow_undocumented:
                m_val024 = re.search(
                    r'(?i)^\s*-?(CollapseEnv|Extract|RenDir)\b|^\s*-?(BlockInput)\s+[01]\b',
                    line,
                )
                if m_val024:
                    cmd_name = m_val024.group(1) or m_val024.group(2)
                    issues.append(
                        Issue(
                            code="VAL-024",
                            message=(
                                f"Command '{cmd_name}' is an undocumented Empirum internal command "
                                "(Klasse 1). Pass --allow-undocumented to permit."
                            ),
                            severity="warning",
                        )
                    )

            # VAL-020: Direct command after Then in If statement
            m_val020 = re.search(
                r'(?i)^\s*-?if\b.+\bthen\s+(abort|echo|exit|call|callhidden|del|deltree|md|mkdir|rd|rmdir|set|setreboot)\b',
                line,
            )
            if m_val020:
                issues.append(
                    Issue(
                        code="VAL-020",
                        message=(
                            f"Direct command '{m_val020.group(1)}' after Then is illegal in Empirum; "
                            "only section jumps are permitted: If <Cond> Then \"<Section>\" EndIf (VAL-020)"
                        ),
                        severity="error",
                    )
                )

            # VAL-021: Sleep= Syntax Error
            if re.search(r'(?i)^\s*-?sleep\s*=\s*\d+', line):
                issues.append(
                    Issue(
                        code="VAL-021",
                        message=(
                            "Invalid syntax 'Sleep=...'; Empirum commands use space delimiter: 'Sleep <ms>' (VAL-021)"
                        ),
                        severity="error",
                    )
                )

    # Parse and AST validation
    try:
        doc = parse_setup_inf(text)
        ast_issues = validate_document(doc)
        issues.extend(ast_issues)
    except Exception as ex:
        issues.append(
            Issue(
                code="E1000",
                message=f"Parsing error: {ex}",
                severity="error",
            )
        )

    return issues


def validate_file(path: Path, allow_undocumented: bool = False) -> list[Issue]:
    """Read and validate a Setup.inf file (byte-level encoding check + content)."""
    issues: list[Issue] = []
    raw = path.read_bytes()

    # Byte-level checks: read_text()/detect_encoding() transparently strips a BOM,
    # so only the raw bytes reveal what Empirum's ANSI parser will actually see.
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        issues.append(
            Issue(
                code="VAL-030",
                message=(
                    f"'{path.name}' starts with a UTF-16/UTF-8 BOM; Empirum Setup.exe and the "
                    "Package Editor expect ANSI/Windows-1252 without BOM (VAL-030)"
                ),
                severity="error",
            )
        )
    else:
        try:
            raw.decode("cp1252")
        except UnicodeDecodeError as ex:
            issues.append(
                Issue(
                    code="VAL-031",
                    message=(
                        f"'{path.name}' is not valid Windows-1252 (ANSI) at byte offset "
                        f"{ex.start}: {ex.reason}. Empirum reads ANSI only (VAL-031)"
                    ),
                    severity="error",
                )
            )

    text, enc = read_text(path)

    # Content-level charset verdicts the byte decode cannot deliver:
    # UTF-8-encoded non-ASCII without BOM decodes cleanly as CP1252 (mojibake
    # 'Ã¼'), so it passes the raw-byte check above - but strictly valid UTF-8
    # with non-ASCII bytes is practically never intended CP1252. Same for a
    # BOM-less UTF-16 detection heuristic.
    if not raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        if enc.charset == "utf-8" and max(raw, default=0) > 0x7F:
            issues.append(
                Issue(
                    code="VAL-031",
                    message=(
                        f"'{path.name}' appears to be UTF-8 encoded (non-ASCII content decodes "
                        "as strict UTF-8), not Windows-1252: umlauts etc. will render as mojibake "
                        "in Empirum. Re-save as ANSI (VAL-031)"
                    ),
                    severity="error",
                )
            )
        elif enc.charset in ("utf-16-le", "utf-16-be"):
            issues.append(
                Issue(
                    code="VAL-031",
                    message=(
                        f"'{path.name}' appears to be UTF-16 encoded without BOM; Empirum "
                        "reads Windows-1252 (ANSI) only (VAL-031)"
                    ),
                    severity="error",
                )
            )

    # Byte-level encoding verdicts above are precise; skip the text-level duplicate.
    issues.extend(validate_text(text, allow_undocumented=allow_undocumented, check_encoding=False))
    return issues

