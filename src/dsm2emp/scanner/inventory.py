"""Data models for package inventory and scanned artifacts."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ArtifactKind = Literal[
    "script",
    "nir",
    "reg",
    "media",
    "metadata",
    "container",
    "internal",
    "unknown",
]


class PackageArtifact(BaseModel):
    """Represents a single discovered file within a DSM package."""

    model_config = ConfigDict(frozen=True)

    rel_path: Path
    absolute_path: Path
    size_bytes: int
    sha256: str
    kind: ArtifactKind
    is_binary: bool = False
    encoding: str | None = None
    has_bom: bool = False
    encoding_confidence: float = 1.0
    reason: str | None = None


class PackageInventory(BaseModel):
    """Complete inventory of a scanned DSM package."""

    model_config = ConfigDict(frozen=True)

    root_path: Path
    artifacts: list[PackageArtifact] = Field(default_factory=list)
    tree_hash: str
    scanned_at_iso: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def scripts(self) -> list[PackageArtifact]:
        """Return all eScript scripts found in package."""
        return [a for a in self.artifacts if a.kind == "script"]

    @property
    def main_script(self) -> PackageArtifact | None:
        """Find the primary Script.inc or first available script."""
        for artifact in self.scripts:
            if artifact.rel_path.name.lower() == "script.inc":
                return artifact
        return self.scripts[0] if self.scripts else None

    @property
    def nirs(self) -> list[PackageArtifact]:
        """Return all .nir registry files."""
        return [a for a in self.artifacts if a.kind == "nir"]

    @property
    def regs(self) -> list[PackageArtifact]:
        """Return all .reg registry files."""
        return [a for a in self.artifacts if a.kind == "reg"]

    @property
    def media(self) -> list[PackageArtifact]:
        """Return all installer binaries, payloads, and archives."""
        return [a for a in self.artifacts if a.kind == "media"]

    @property
    def metadata_files(self) -> list[PackageArtifact]:
        """Return all package metadata files (e.g. Package.ini)."""
        return [a for a in self.artifacts if a.kind == "metadata"]

    @property
    def containers(self) -> list[PackageArtifact]:
        """Return any .ncp package containers requiring export."""
        return [a for a in self.artifacts if a.kind == "container"]

    @property
    def internal_files(self) -> list[PackageArtifact]:
        """Return all internal or non-payload package files (e.g. DSM _NI5.zip cache)."""
        return [a for a in self.artifacts if a.kind == "internal"]

    @property
    def unknowns(self) -> list[PackageArtifact]:
        """Return all unclassified or ambiguous artifacts."""
        return [a for a in self.artifacts if a.kind == "unknown"]

    def get_artifact(self, rel_path: Path | str) -> PackageArtifact | None:
        """Find an artifact by relative path."""
        target = Path(rel_path)
        for artifact in self.artifacts:
            if artifact.rel_path == target:
                return artifact
        return None
