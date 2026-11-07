"""Empirum package builder assembling target structure and copying payload assets (Task T-042).

Enforces target safety (FR-025), configurable directory layouts (Chapter 2.2),
and byte-exact SHA-256 payload integrity verification.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dsm2emp.io.encoding import write_text
from dsm2emp.manual.extractor import extract_manual_info, sanitize_filename
from dsm2emp.manual.generator import generate_manual_pdf
from dsm2emp.manual.model import PackageManualInfo
from dsm2emp.scanner.inventory import PackageInventory


@dataclass(frozen=True)
class BuilderOptions:
    """Configuration options for Empirum package layout generation."""

    setup_inf_dir: str = "Install"
    payload_dir: str = "Files"
    manual_dir: str = "Manual"
    # Empirum Setup.exe / Package Editor read Setup.inf as ANSI (Windows-1252)
    # without BOM; UTF-8 output makes the interpreter exit immediately ("flash and
    # gone") and breaks single-step debugging in the Package Editor.
    charset: Literal["cp1252", "utf-8", "utf-16"] = "cp1252"
    verify_hashes: bool = True
    force: bool = False
    generate_manual: bool = True


@dataclass
class BuildResult:
    """Result of assembling an Empirum software package."""

    target_root: Path
    setup_inf_path: Path
    payload_dir: Path
    manual_dir: Path | None = None
    manual_pdf_path: Path | None = None
    copied_files: list[Path] = field(default_factory=list)
    total_bytes_copied: int = 0
    hashes_verified: bool = True


def check_path_collision(source: Path, target: Path) -> None:
    """Ensure source and target paths do not overlap or collide (E9001)."""
    src_res = source.resolve()
    tgt_res = target.resolve()

    if src_res == tgt_res:
        raise ValueError(f"E9001: Source and target directories cannot be identical: {src_res}")

    # Check if target is inside source
    try:
        tgt_res.relative_to(src_res)
        raise ValueError(
            f"E9001: Target directory '{tgt_res}' cannot be inside source directory '{src_res}'"
        )
    except ValueError as ex:
        if "E9001" in str(ex):
            raise

    # Check if source is inside target
    try:
        src_res.relative_to(tgt_res)
        raise ValueError(
            f"E9001: Source directory '{src_res}' cannot be inside target directory '{tgt_res}'"
        )
    except ValueError as ex:
        if "E9001" in str(ex):
            raise


class PackageBuilder:
    """Builds Empirum directory layout, writes Setup.inf and copies payload media."""

    def __init__(self, options: BuilderOptions | None = None) -> None:
        self.options = options or BuilderOptions()

    def build_package(
        self,
        target_dir: Path,
        inf_content: str,
        inventory: PackageInventory,
        manual_info: PackageManualInfo | None = None,
    ) -> BuildResult:
        """Assemble Empirum package layout under target_dir.

        On any failure, artifacts already written by this build are removed
        (best-effort), so no half-finished package is left behind.
        """
        tgt = target_dir.resolve()
        src = inventory.root_path.resolve()

        # 1. Collision check
        check_path_collision(src, tgt)

        # 2. Existing directory check
        if tgt.exists() and any(tgt.iterdir()) and not self.options.force:
            raise FileExistsError(
                f"Target directory '{tgt}' is not empty. Use --force to allow overwriting."
            )

        written_files: list[Path] = []
        created_dirs: list[Path] = []
        tgt_existed = tgt.exists()

        def _mkdir_tracked(path: Path) -> None:
            if path.exists():
                return
            missing: list[Path] = []
            current = path
            while not current.exists():
                missing.append(current)
                current = current.parent
            path.mkdir(parents=True)
            created_dirs.extend(reversed(missing))

        try:
            # 3. Create directory layout
            install_dir = tgt / self.options.setup_inf_dir
            payload_dir = tgt / self.options.payload_dir
            _mkdir_tracked(install_dir)
            _mkdir_tracked(payload_dir)

            # 4. Copy media payload files with SHA-256 verification
            copied_files: list[Path] = []
            total_bytes = 0

            for art in inventory.media:
                if art.rel_path.name.lower().endswith("_ni5.zip"):
                    continue

                parts_lower = [p.lower() for p in art.rel_path.parts]
                if "extern$" in parts_lower:
                    idx = parts_lower.index("extern$")
                    subpath = Path(*art.rel_path.parts[idx + 1 :])
                    dest_file = payload_dir / subpath
                elif "$extern" in parts_lower:
                    idx = parts_lower.index("$extern")
                    subpath = Path(*art.rel_path.parts[idx + 1 :])
                    dest_file = payload_dir / subpath
                else:
                    dest_file = payload_dir / art.rel_path

                if not dest_file.parent.exists():
                    _mkdir_tracked(dest_file.parent)
                shutil.copy2(art.absolute_path, dest_file)
                written_files.append(dest_file)
                copied_files.append(dest_file)
                total_bytes += art.size_bytes

                if self.options.verify_hashes and art.sha256:
                    hasher = hashlib.sha256()
                    with open(dest_file, "rb") as f:
                        while chunk := f.read(65536):
                            hasher.update(chunk)
                    dest_hash = hasher.hexdigest()
                    if dest_hash != art.sha256:
                        raise OSError(
                            f"Payload hash verification failed for '{dest_file.name}': "
                            f"expected {art.sha256}, got {dest_hash}"
                        )

            # 5. Write Setup.inf
            setup_inf_path = install_dir / "Setup.inf"
            write_text(
                setup_inf_path,
                inf_content,
                charset=self.options.charset,
                crlf=True,
                bom=False,
            )
            written_files.append(setup_inf_path)

            # 6. Create Manual folder and package documentation PDF (last step:
            # a reportlab failure must not invalidate an otherwise complete build
            # - and thanks to the rollback below nothing is left behind anyway)
            manual_dir: Path | None = None
            manual_pdf_path: Path | None = None
            if self.options.generate_manual:
                manual_dir = tgt / self.options.manual_dir
                _mkdir_tracked(manual_dir)
                info = manual_info or extract_manual_info(
                    inventory=inventory,
                    inf_content=inf_content,
                    inf_charset=self.options.charset,
                )
                safe_name = sanitize_filename(info.package_name)
                manual_pdf_path = manual_dir / f"{safe_name}.pdf"
                written_files.append(manual_pdf_path)
                generate_manual_pdf(info, manual_pdf_path)
        except Exception:
            self._rollback(tgt, written_files, created_dirs, tgt_existed)
            raise

        return BuildResult(
            target_root=tgt,
            setup_inf_path=tgt / self.options.setup_inf_dir / "Setup.inf",
            payload_dir=payload_dir,
            manual_dir=manual_dir,
            manual_pdf_path=manual_pdf_path,
            copied_files=copied_files,
            total_bytes_copied=total_bytes,
            hashes_verified=self.options.verify_hashes,
        )

    @staticmethod
    def _rollback(
        tgt: Path,
        written_files: list[Path],
        created_dirs: list[Path],
        tgt_existed: bool,
    ) -> None:
        """Best-effort removal of everything this build created; touches nothing
        outside the package target directory and never raises."""
        for file_path in written_files:
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError:
                pass
        # Deepest dirs first; rmdir only succeeds on empty directories, so any
        # pre-existing content survives untouched.
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        if not tgt_existed:
            try:
                tgt.rmdir()
            except OSError:
                pass
