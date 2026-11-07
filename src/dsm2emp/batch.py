"""Batch migration processor for converting multiple DSM packages (Task T-043).

Supports deterministic package sorting, concurrent execution via worker pool,
state persistence for resumption (--resume via state.ndjson), and aggregated reporting.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dsm2emp.orchestrator import MigrationOptions, MigrationResult, migrate_single
from dsm2emp.report.index_page import generate_package_index
from dsm2emp.scanner.inventory import PackageInventory


@dataclass(frozen=True)
class BatchOptions:
    """Configuration options for batch package migrations."""

    jobs: int = 1
    resume: bool = False
    state_file: Path | None = None
    force: bool = False
    # Empirum Setup.exe / Package Editor read Setup.inf as ANSI (Windows-1252);
    # anything else (UTF-8, UTF-16, BOM) makes the interpreter exit immediately.
    charset: Literal["cp1252", "utf-8", "utf-16"] = "cp1252"
    developer_name: str = "Matrix42"
    rules_path: Path | None = None
    allow_undocumented: bool = False


@dataclass
class BatchResult:
    """Aggregated outcome of a batch migration run."""

    total_packages: int
    successful: int
    warnings: int
    failed: int
    skipped: int
    results: list[MigrationResult] = field(default_factory=list)
    overall_exit_code: int = 0


def is_dsm_package_dir(path: Path) -> bool:
    """Check if a directory contains DSM package indicators."""
    if not path.is_dir():
        return False
    # Check for direct marker files
    for child in path.iterdir():
        name_lower = child.name.lower()
        if name_lower in ("script.inc", "package.ini", "setup.nir") or name_lower.endswith(".inc"):
            return True
    return False


def discover_packages(source_root: Path) -> list[Path]:
    """Find all DSM packages under source_root, sorted deterministically."""
    root = source_root.resolve()
    if not root.exists():
        return []

    # If the root itself is a package
    if is_dsm_package_dir(root):
        return [root]

    packages: list[Path] = []
    # Search immediate children and subdirectories
    for item in sorted(root.iterdir(), key=lambda p: str(p).lower()):
        if item.is_dir():
            if is_dsm_package_dir(item):
                packages.append(item)
            else:
                # One level deeper if needed
                for sub in sorted(item.iterdir(), key=lambda p: str(p).lower()):
                    if sub.is_dir() and is_dsm_package_dir(sub):
                        packages.append(sub)

    return sorted(packages, key=lambda p: str(p).lower())


def _load_completed_state(state_file: Path) -> dict[str, dict[str, object]]:
    """Load previously completed packages from state.ndjson."""
    completed: dict[str, dict[str, object]] = {}
    if not state_file.exists():
        return completed

    try:
        with open(state_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if isinstance(record, dict) and "package_name" in record:
                        pkg_key = str(record["package_name"])
                        completed[pkg_key] = record
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass

    return completed


def _append_state_record(state_file: Path, record: Mapping[str, object]) -> None:
    """Atomically append a single package migration record to state.ndjson."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def migrate_batch(
    source_root: Path,
    target_root: Path,
    options: BatchOptions | None = None,
    progress_callback: Callable[[MigrationResult, int, int], None] | None = None,
) -> BatchResult:
    """Execute batch migration across all discovered DSM packages.

    Enforces deterministic processing, worker pool parallelization,
    resumption support via state.ndjson, and aggregated exit codes.
    """
    opts = options or BatchOptions()
    src_root = source_root.resolve()
    tgt_root = target_root.resolve()

    packages = discover_packages(src_root)
    state_file = opts.state_file or (tgt_root / "state.ndjson")
    completed_state = _load_completed_state(state_file) if opts.resume else {}

    results: list[MigrationResult] = []
    successful = 0
    warnings = 0
    failed = 0
    skipped = 0

    to_process: list[Path] = []
    for pkg in packages:
        pkg_name = pkg.name
        if opts.resume and pkg_name in completed_state:
            prev = completed_state[pkg_name]
            prev_exit = int(str(prev.get("exit_code", 0)))
            if prev_exit in (0, 1):
                skipped += 1
                if prev_exit == 0:
                    successful += 1
                else:
                    warnings += 1
                continue
        to_process.append(pkg)

    def _worker(pkg_path: Path) -> MigrationResult:
        # Determine subfolder name relative to source_root if possible
        try:
            rel = pkg_path.relative_to(src_root)
        except ValueError:
            rel = Path(pkg_path.name)

        dest_dir = tgt_root / rel
        single_opts = MigrationOptions(
            charset=opts.charset,
            force=opts.force,
            developer_name=opts.developer_name,
            rules_path=opts.rules_path,
            allow_undocumented=opts.allow_undocumented,
        )
        return migrate_single(pkg_path, dest_dir, single_opts)

    completed_count = skipped
    total_count = len(packages)

    if opts.jobs <= 1 or len(to_process) <= 1:
        # Sequential execution
        for pkg in to_process:
            res = _worker(pkg)
            results.append(res)
            completed_count += 1

            if res.exit_code == 0:
                successful += 1
            elif res.exit_code == 1:
                warnings += 1
            else:
                failed += 1

            status_str = (
                "success" if res.exit_code == 0 else "warning" if res.exit_code == 1 else "failed"
            )
            record = {
                "package_name": pkg.name,
                "source_path": str(res.source_root),
                "target_path": str(res.target_root) if res.target_root else None,
                "status": status_str,
                "exit_code": res.exit_code,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
            _append_state_record(state_file, record)

            if progress_callback:
                progress_callback(res, completed_count, total_count)
    else:
        # Concurrent execution via ThreadPoolExecutor
        workers = min(opts.jobs, len(to_process))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_pkg = {executor.submit(_worker, pkg): pkg for pkg in to_process}
            for future in as_completed(future_to_pkg):
                pkg = future_to_pkg[future]
                try:
                    res = future.result()
                except Exception as ex:
                    res = MigrationResult(
                        success=False,
                        exit_code=3,
                        source_root=pkg,
                        target_root=None,
                        inventory=PackageInventory(root_path=pkg, artifacts=[], tree_hash=""),
                        error_message=str(ex),
                    )

                results.append(res)
                completed_count += 1

                if res.exit_code == 0:
                    successful += 1
                elif res.exit_code == 1:
                    warnings += 1
                else:
                    failed += 1

                status_str = (
                    "success"
                    if res.exit_code == 0
                    else "warning"
                    if res.exit_code == 1
                    else "failed"
                )
                record = {
                    "package_name": pkg.name,
                    "source_path": str(res.source_root),
                    "target_path": str(res.target_root) if res.target_root else None,
                    "status": status_str,
                    "exit_code": res.exit_code,
                    "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                }
                _append_state_record(state_file, record)

                if progress_callback:
                    progress_callback(res, completed_count, total_count)

    # Calculate overall exit code
    overall_exit = 0
    if failed > 0:
        overall_exit = 2
    elif warnings > 0:
        overall_exit = 1

    # Generate interactive Paketindex.html in the target root directory
    try:
        generate_package_index(tgt_root)
    except Exception:
        pass

    return BatchResult(
        total_packages=len(packages),
        successful=successful,
        warnings=warnings,
        failed=failed,
        skipped=skipped,
        results=results,
        overall_exit_code=overall_exit,
    )
