"""Background QThread workers for long-running operations (Task T-050).

Conforms to Chapter 5.1:
- Long running operations run in QThread to ensure UI never freezes.
- Communicates exclusively via Qt signals.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from dsm2emp.batch import BatchOptions, migrate_batch
from dsm2emp.orchestrator import MigrationOptions, MigrationResult, migrate_single
from dsm2emp.report.index_page import generate_package_index
from dsm2emp.scanner.scanner import scan


class ScanWorker(QThread):
    """Background worker for scanning a DSM package directory."""

    scanned = Signal(object)  # PackageInventory
    failed = Signal(str)

    def __init__(self, source_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.source_dir = source_dir

    def run(self) -> None:
        """Run package scan."""
        try:
            inventory = scan(self.source_dir)
            self.scanned.emit(inventory)
        except Exception as exc:
            self.failed.emit(str(exc))


class MigrationWorker(QThread):
    """Background worker for executing single package migration."""

    progress = Signal(str)
    finished_result = Signal(object)  # MigrationResult
    failed = Signal(str)

    def __init__(
        self,
        source_dir: Path,
        target_dir: Path | None,
        options: MigrationOptions,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.options = options

    def run(self) -> None:
        """Run migration pipeline."""
        try:
            self.progress.emit("Migration gestartet...")
            target = self.target_dir or (self.source_dir.parent / f"{self.source_dir.name}_Empirum")
            result = migrate_single(
                self.source_dir,
                target,
                self.options,
            )
            if result.success and target.parent.exists():
                try:
                    generate_package_index(target.parent)
                except Exception:
                    pass
            self.progress.emit("Migration abgeschlossen.")
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class BatchWorker(QThread):
    """Background worker for running batch package conversions."""

    package_completed = Signal(object)  # MigrationResult
    batch_finished = Signal(object)  # BatchResult
    failed = Signal(str)

    def __init__(
        self,
        source_dir: Path,
        target_dir: Path,
        options: BatchOptions | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.options = options or BatchOptions()

    def run(self) -> None:
        """Run batch processing in worker thread."""
        try:

            def on_progress(res: MigrationResult, current: int, total: int) -> None:
                self.package_completed.emit(res)

            summary = migrate_batch(
                self.source_dir,
                self.target_dir,
                options=self.options,
                progress_callback=on_progress,
            )
            self.batch_finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
