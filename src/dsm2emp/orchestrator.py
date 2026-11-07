"""Migration orchestrator for transforming DSM software packages into Empirum packages.

Coordinates scanning, parsing, rule transformation, emission, validation, and package building
while enforcing strict read-only source package protection (FR-001) and target safety (FR-025).
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dsm2emp.builder.builder import (
    BuilderOptions,
    BuildResult,
    PackageBuilder,
    check_path_collision,
)
from dsm2emp.emitter.quote import Issue
from dsm2emp.emitter.render import EmitOptions, emit
from dsm2emp.io.encoding import read_text
from dsm2emp.manual.extractor import extract_manual_info
from dsm2emp.parser.escript.parser import parse_script
from dsm2emp.parser.expinfo import ExpInfoMetadata, parse_expinfo_xml
from dsm2emp.parser.ir import IrPackage, IrScript, IrTodo
from dsm2emp.parser.nir import IrRegKey, parse_nir
from dsm2emp.rules.engine import RuleEngine
from dsm2emp.rules.loader import load_rules
from dsm2emp.rules.model import TransformResult
from dsm2emp.scanner.inventory import PackageInventory
from dsm2emp.scanner.msi import extract_product_code_from_msi
from dsm2emp.scanner.scanner import calculate_tree_hash, scan
from dsm2emp.validator.rules import validate_text


@dataclass(frozen=True)
class MigrationOptions:
    """Configuration options for a package migration."""

    # Empirum Setup.exe / Package Editor read Setup.inf as ANSI (Windows-1252);
    # anything else (UTF-8, UTF-16, BOM) makes the interpreter exit immediately.
    charset: Literal["cp1252", "utf-8", "utf-16"] = "cp1252"
    force: bool = False
    developer_name: str = "Matrix42"
    product_name: str | None = None
    version: str | None = None
    rules_path: Path | None = None
    ai_enabled: bool = False
    ai_pipeline: Any | None = None
    allow_undocumented: bool = False


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of a package migration run."""

    success: bool
    exit_code: int  # 0: clean, 1: warnings, 2: errors, 3: fatal / collision
    source_root: Path
    target_root: Path | None
    inventory: PackageInventory
    transform_result: TransformResult | None = None
    issues: list[Issue] = field(default_factory=list)
    error_message: str | None = None
    build_result: BuildResult | None = None


def _extract_metadata(inventory: PackageInventory) -> ExpInfoMetadata:
    """Extract product name, version, manufacturer, and description from package metadata files."""
    # 1. Prefer _ExpInfo.xml (definitive DSM package export info)
    exp_file: Path | None = None
    for meta_art in inventory.metadata_files:
        if meta_art.rel_path.name.lower() == "_expinfo.xml":
            exp_file = meta_art.absolute_path
            break
    if not exp_file and (inventory.root_path / "_ExpInfo.xml").exists():
        exp_file = inventory.root_path / "_ExpInfo.xml"

    if exp_file:
        parsed_exp = parse_expinfo_xml(exp_file)
        if parsed_exp.name or parsed_exp.manufacturer:
            return parsed_exp

    # 2. Fall back to package.ini / setup.ini
    name: str | None = None
    ver: str | None = None
    mfg: str | None = None
    desc: str | None = None

    for meta_art in inventory.metadata_files:
        if meta_art.rel_path.name.lower() in ("package.ini", "setup.ini"):
            try:
                content, _ = read_text(meta_art.absolute_path)
                cp = configparser.ConfigParser()
                cp.read_string(content)
                for sec in ("Package", "Application", "Setup"):
                    if cp.has_section(sec):
                        name = (
                            name
                            or cp.get(sec, "Name", fallback=None)
                            or cp.get(sec, "ProductName", fallback=None)
                        )
                        ver = ver or cp.get(sec, "Version", fallback=None)
                        mfg = (
                            mfg
                            or cp.get(sec, "Manufacturer", fallback=None)
                            or cp.get(sec, "DeveloperName", fallback=None)
                        )
                        desc = (
                            desc
                            or cp.get(sec, "Description", fallback=None)
                            or cp.get(sec, "Comment", fallback=None)
                        )
            except Exception:
                pass

    return ExpInfoMetadata(name=name, version=ver, manufacturer=mfg, description=desc)


def migrate_single(
    source_path: Path,
    target_path: Path,
    options: MigrationOptions | None = None,
) -> MigrationResult:
    """Execute complete deterministic migration workflow for a single package."""
    opts = options or MigrationOptions()
    src = source_path.resolve()
    tgt = target_path.resolve()

    # 1. Validation & Safety Checks (Chapter 7.5)
    try:
        check_path_collision(src, tgt)
    except ValueError as err:
        # Create minimal inventory dummy for failure reporting
        dummy_inv = PackageInventory(root_path=src, artifacts=[], tree_hash="")
        return MigrationResult(
            success=False,
            exit_code=3,
            source_root=src,
            target_root=tgt,
            inventory=dummy_inv,
            error_message=str(err),
        )

    if not src.exists() or not src.is_dir():
        dummy_inv = PackageInventory(root_path=src, artifacts=[], tree_hash="")
        return MigrationResult(
            success=False,
            exit_code=3,
            source_root=src,
            target_root=tgt,
            inventory=dummy_inv,
            error_message=f"Source directory does not exist or is not a directory: {src}",
        )

    if tgt.exists() and any(tgt.iterdir()) and not opts.force:
        dummy_inv = PackageInventory(root_path=src, artifacts=[], tree_hash="")
        return MigrationResult(
            success=False,
            exit_code=3,
            source_root=src,
            target_root=tgt,
            inventory=dummy_inv,
            error_message=(
                f"Target directory '{tgt}' is not empty. Use --force to allow overwriting."
            ),
        )

    # 2. Source protection fingerprint (Tree-hash before run)
    tree_hash_before = calculate_tree_hash(src)

    # 3. Scanning
    inventory = scan(src)

    # 4. Parsing DSM artifacts
    main_script_ir: IrScript | None = None
    todos: list[IrTodo] = []

    if inventory.main_script:
        script_text, _ = read_text(inventory.main_script.absolute_path)
        main_script_ir = parse_script(script_text, inventory.main_script.absolute_path)

    # Parse any NIR / REG files
    parsed_nirs: list[IrRegKey] = []
    for reg_art in inventory.nirs + inventory.regs:
        reg_text, _ = read_text(reg_art.absolute_path)
        parsed_nirs.extend(parse_nir(reg_text, reg_art.absolute_path))

    # Package metadata extraction
    meta = _extract_metadata(inventory)
    prod_name = opts.product_name or meta.name or src.name
    version = opts.version or meta.version or "1.0"
    if opts.developer_name and opts.developer_name != "Matrix42":
        manufacturer = opts.developer_name
    else:
        manufacturer = meta.manufacturer or opts.developer_name or "Matrix42"

    # Extract MSI ProductCode GUIDs from payload if present
    msi_product_codes: dict[str, str] = {}
    for art in inventory.artifacts:
        if art.rel_path.suffix.lower() == ".msi":
            code = extract_product_code_from_msi(art.absolute_path)
            if code:
                msi_product_codes[art.rel_path.name] = code
                msi_product_codes[str(art.rel_path)] = code

    pkg_ir = IrPackage(
        name=prod_name,
        version=version,
        manufacturer=manufacturer,
        description=meta.description,
        revision=meta.revision,
        revision_comment=meta.revision_comment,
        main_script=main_script_ir,
        media_files=[m.absolute_path for m in inventory.artifacts],
        msi_product_codes=msi_product_codes,
        todos=todos,
    )

    # 5. Rule Transformation
    ruleset = load_rules(opts.rules_path)
    engine = RuleEngine(ruleset, allow_undocumented=opts.allow_undocumented)
    transform_res = engine.transform_package(
        pkg_ir,
        parsed_nirs=parsed_nirs,
        developer_name=manufacturer,
        product_name=prod_name,
        version=version,
        package_root=src,
        allow_undocumented=opts.allow_undocumented,
    )

    # 5b. Optional AI Pipeline (Opt-in, graceful degradation per NFR-001/FR-052)
    if opts.ai_enabled and opts.ai_pipeline and transform_res.todos:
        try:
            doc, ai_result = opts.ai_pipeline.run_pipeline(
                transform_res.todos, transform_res.document
            )
            transform_res = TransformResult(
                document=doc,
                traces=transform_res.traces + ai_result.applied_traces,
                todos=ai_result.remaining_todos,
            )
        except Exception:
            # On network or provider failure, retain rule-based todos (graceful degradation)
            pass

    # 6. Emitter (Setup.inf serialization)
    emit_opts = EmitOptions(charset=opts.charset, crlf=True)
    inf_text, emit_issues = emit(transform_res.document, emit_opts)

    # 7. Semantic Validation
    val_issues = validate_text(inf_text, allow_undocumented=opts.allow_undocumented)
    all_issues = emit_issues + val_issues
    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]

    # Halt if errors exist (Exit 2)
    if errors:
        return MigrationResult(
            success=False,
            exit_code=2,
            source_root=src,
            target_root=tgt,
            inventory=inventory,
            transform_result=transform_res,
            issues=all_issues,
            error_message=(
                f"Validation failed with {len(errors)} error(s). No target files written."
            ),
        )

    # 8. Package Building (Target writing via PackageBuilder)
    manual_info = extract_manual_info(
        inventory=inventory,
        inf_content=inf_text,
        product_name=prod_name,
        version=version,
        manufacturer=manufacturer,
        pkg_ir=pkg_ir,
        transform_result=transform_res,
        inf_charset=opts.charset,
    )
    builder = PackageBuilder(BuilderOptions(charset=opts.charset, force=opts.force))
    build_res = builder.build_package(tgt, inf_text, inventory, manual_info=manual_info)

    # 9. Quellschutz verification (FR-001)
    tree_hash_after = calculate_tree_hash(src)
    if tree_hash_after != tree_hash_before:
        raise RuntimeError(
            "CRITICAL: Quellschutz violation! "
            "Source package directory was modified during migration!"
        )

    exit_code = 1 if warnings else 0
    return MigrationResult(
        success=True,
        exit_code=exit_code,
        source_root=src,
        target_root=tgt,
        inventory=inventory,
        transform_result=transform_res,
        issues=all_issues,
        build_result=build_res,
    )
