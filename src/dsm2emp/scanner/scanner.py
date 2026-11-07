"""Package scanner implementation for Ivanti DSM software packages.

Performs strictly read-only analysis, classifies artifacts, detects encodings,
and computes cryptographic fingerprints.
"""

import hashlib
from pathlib import Path

from dsm2emp.io.encoding import detect_encoding
from dsm2emp.scanner.inventory import ArtifactKind, PackageArtifact, PackageInventory

# Common file extension classifications
SCRIPT_EXTENSIONS = {".inc", ".dsm"}
REG_EXTENSIONS = {".reg"}
NIR_EXTENSIONS = {".nir"}
CONTAINER_EXTENSIONS = {".ncp"}
METADATA_FILENAMES = {
    "package.ini",
    "setup.ini",
    "metadata.xml",
    "package.xml",
    "dsm_package.xml",
    "packageinfo.xml",
    "_expinfo.xml",
}
DSM_INTERNAL_FILENAMES = {
    "compproject.status",
    "project.status",
    "project.jdf",
    "package.fpi",
    "package.fpi.checksum",
}
MEDIA_EXTENSIONS = {
    # Installers & binaries
    ".msi",
    ".msp",
    ".mst",
    ".exe",
    ".cab",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
    ".iso",
    ".bin",
    ".dat",
    ".dll",
    ".sys",
    ".ocx",
    ".jar",
    ".cmd",
    ".bat",
    ".vbs",
    ".vbe",
    ".ps1",
    ".js",
    # Fonts
    ".otf",
    ".ttf",
    ".fon",
    ".woff",
    ".woff2",
    ".eot",
    # Icons & images
    ".ico",
    ".bmp",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    # Config & data
    ".cfg",
    ".ini",
    ".xml",
    ".json",
    ".conf",
    ".esp",
    ".epp",
    ".tpd",
    ".rdlc",
    ".pdb",
    ".indt",
    ".lnk",
    ".iss",
    ".640",
    ".txt",
    ".pdf",
    ".chm",
}


def _hash_file(path: Path, preview_bytes: int = 0) -> tuple[str, int, bytes]:
    """Compute SHA-256 hash and file size in a streaming read-only manner.

    If preview_bytes > 0, also captures the first preview_bytes of the file in the same pass.
    """
    sha = hashlib.sha256()
    size = 0
    preview = b""
    buffer_size = 65536  # 64 KB

    with path.open("rb") as f:
        while chunk := f.read(buffer_size):
            if preview_bytes > 0 and len(preview) < preview_bytes:
                needed = preview_bytes - len(preview)
                preview += chunk[:needed]
            sha.update(chunk)
            size += len(chunk)

    return sha.hexdigest(), size, preview


def _is_binary(preview: bytes) -> bool:
    """Heuristic check whether byte preview is binary (non-text)."""
    if not preview:
        return False
    # UTF-16 BOMs have null bytes that are legitimate text
    if preview.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    # Check for excessive null bytes
    return b"\x00" in preview[:1024]


def classify_artifact(
    rel_path: Path,
    preview: bytes,
    is_bin: bool,
) -> tuple[ArtifactKind, str | None]:
    """Determine artifact category and diagnostic reason."""
    filename_lower = rel_path.name.lower()
    suffix_lower = rel_path.suffix.lower()

    parts_lower = [p.lower() for p in rel_path.parts]

    # 1. DSM NetInstall cache or internal revision folder
    if filename_lower.endswith("_ni5.zip") or "rev" in parts_lower:
        desc = (
            f"DSM NetInstall Paket-Cache / Revision ({rel_path.name}) - für Empirum übersprungen"
        )
        return "internal", desc

    # 2. DSM project status and backup files
    if filename_lower in DSM_INTERNAL_FILENAMES:
        return "internal", f"DSM-Projektstatusdatei ({rel_path.name}) - für Empirum übersprungen"

    if filename_lower.startswith("script.") and (
        filename_lower.endswith((".ba1", ".ba2", ".bak")) or filename_lower[7:].isdigit()
    ):
        return "internal", f"DSM-Skript-Backupdatei ({rel_path.name}) - für Empirum übersprungen"

    # 3. Container
    if suffix_lower in CONTAINER_EXTENSIONS:
        return "container", "DSM-Paket-Container: Export als Verzeichnis erforderlich"

    # 4. Main script
    is_script = filename_lower == "script.inc" or (
        suffix_lower in SCRIPT_EXTENSIONS and len(rel_path.parts) == 1
    )
    if is_script:
        return "script", "DSM eScript-Skriptdatei"

    # 5. Registry files (excluding payload / profile directories like HOMEDRIVE)
    is_payload_dir = any(p in ("homedrive", "extern$", "extern") for p in parts_lower)
    if suffix_lower in NIR_EXTENSIONS and not is_payload_dir:
        return "nir", "DSM NetInstall Registry-Datei (.nir)"

    if suffix_lower in REG_EXTENSIONS and not is_payload_dir:
        return "reg", "Windows Registry-Datei (.reg)"

    # 6. Metadata files (root level only)
    if filename_lower in METADATA_FILENAMES and len(rel_path.parts) == 1:
        return "metadata", f"Paket-Metadatendatei ({rel_path.name})"

    # 7. Extern$ / $Extern payload folder
    if ("extern$" in parts_lower or "$extern" in parts_lower) and "rev" not in parts_lower:
        return "media", f"Extern$-Payload-Datei ({rel_path.name})"

    # 8. Known media extensions
    if suffix_lower in MEDIA_EXTENSIONS:
        return "media", f"Quellmedium/Installationsdatei ({suffix_lower})"

    # 9. Any file in a subfolder (payload directory structure like FONT, Grass Valley, etc.)
    if len(rel_path.parts) > 1 and "rev" not in parts_lower:
        return "media", f"Unterordner-Payload-Datei ({rel_path})"

    # Content-based heuristic for text files
    if not is_bin and preview:
        try:
            sample_text = preview[:2048].decode("utf-8", errors="replace").lower()
            if "regedit4" in sample_text or "windows registry editor" in sample_text:
                if "%" in sample_text or suffix_lower == ".nir":
                    return "nir", "Registry-Datei mit DSM-Variablensyntax"
                return "reg", "Windows Registry-Datei nach Inhalt"

            escript_markers = [
                "executeex",
                "executepolicies",
                "$beginuninstallscript",
                "installfile",
                "createlink",
                "regload",
                "exitproc",
            ]
            if any(marker in sample_text for marker in escript_markers):
                return "script", "eScript-Befehlssequenz anhand von Befehlsmarkern erkannt"
        except Exception:
            pass

    if is_bin:
        # Unknown binary payload
        return "unknown", f"Nicht klassifizierte Binärdatei ({suffix_lower or 'ohne Endung'})"

    return "unknown", f"Nicht klassifizierte Textdatei ({rel_path.name})"


def scan(root: Path) -> PackageInventory:
    """Scan a DSM package root directory in read-only mode and return inventory."""
    root_resolved = root.resolve()
    if not root_resolved.exists():
        raise FileNotFoundError(f"Package directory does not exist: {root_resolved}")
    if not root_resolved.is_dir():
        raise NotADirectoryError(f"Package root must be a directory: {root_resolved}")

    artifacts: list[PackageArtifact] = []
    tree_entries: list[tuple[str, str, int]] = []

    # Recursively find all files in single I/O pass
    for file_path in sorted(root_resolved.rglob("*")):
        if not file_path.is_file():
            continue

        rel_path = file_path.relative_to(root_resolved)
        sha256, size_bytes, preview = _hash_file(file_path, preview_bytes=4096)
        tree_entries.append((rel_path.as_posix(), sha256, size_bytes))

        is_bin = _is_binary(preview)
        kind, reason = classify_artifact(rel_path, preview, is_bin)

        encoding_str: str | None = None
        has_bom = False
        confidence = 1.0

        if not is_bin:
            enc_info = detect_encoding(preview)
            encoding_str = enc_info.charset
            has_bom = enc_info.has_bom
            confidence = enc_info.confidence

        artifacts.append(
            PackageArtifact(
                rel_path=rel_path,
                absolute_path=file_path,
                size_bytes=size_bytes,
                sha256=sha256,
                kind=kind,
                is_binary=is_bin,
                encoding=encoding_str,
                has_bom=has_bom,
                encoding_confidence=confidence,
                reason=reason,
            )
        )

    # Calculate tree hash deterministically from the already computed artifact hashes
    tree_hash = calculate_tree_hash(root_resolved, entries=tree_entries)

    return PackageInventory(
        root_path=root_resolved,
        artifacts=artifacts,
        tree_hash=tree_hash,
    )


def calculate_tree_hash(
    root: Path,
    entries: list[tuple[str, str, int]] | None = None,
) -> str:
    """Calculate deterministic tree hash of directory contents.

    Ensures that any file modification or addition/removal changes the hash.
    Used to guarantee source package directory remains byte-identical.
    """
    root_resolved = root.resolve()
    if not root_resolved.exists() or not root_resolved.is_dir():
        return ""

    if entries is None:
        entries = []
        for file_path in sorted(root_resolved.rglob("*")):
            if file_path.is_file():
                rel_str = file_path.relative_to(root_resolved).as_posix()
                sha, size, _ = _hash_file(file_path)
                entries.append((rel_str, sha, size))

    hasher = hashlib.sha256()
    for rel_str, sha, size in sorted(entries, key=lambda x: x[0]):
        line = f"{rel_str}:{sha}:{size}\n"
        hasher.update(line.encode("utf-8"))

    return hasher.hexdigest()
