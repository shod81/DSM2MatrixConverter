"""Robust encoding detection and file I/O for legacy Windows and Empirum files."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EncodingInfo:
    """Information about detected encoding of a file or byte sequence."""

    charset: str
    has_bom: bool
    confidence: float


def detect_encoding(data: bytes) -> EncodingInfo:
    """Detect charset and BOM of raw bytes.

    Priority:
    1. UTF-8 BOM (EF BB BF)
    2. UTF-16 LE BOM (FF FE)
    3. UTF-16 BE BOM (FE FF)
    4. Valid UTF-8 without BOM
    5. Fallback: cp1252 (Windows-1252/ANSI)
    """
    if not data:
        return EncodingInfo(charset="utf-8", has_bom=False, confidence=1.0)

    # 1. UTF-8 BOM
    if data.startswith(b"\xef\xbb\xbf"):
        return EncodingInfo(charset="utf-8-sig", has_bom=True, confidence=1.0)

    # 2. UTF-16 LE BOM
    if data.startswith(b"\xff\xfe"):
        return EncodingInfo(charset="utf-16-le", has_bom=True, confidence=1.0)

    # 3. UTF-16 BE BOM
    if data.startswith(b"\xfe\xff"):
        return EncodingInfo(charset="utf-16-be", has_bom=True, confidence=1.0)

    # 4. Check for UTF-16 without BOM heuristic (e.g. alternating null bytes in ASCII range)
    if len(data) >= 4:
        if data[1::2].count(0) > len(data) // 4 and data[0::2].count(0) < len(data) // 8:
            try:
                data.decode("utf-16-le")
                return EncodingInfo(charset="utf-16-le", has_bom=False, confidence=0.85)
            except UnicodeDecodeError:
                pass

    # 5. Try strict UTF-8
    try:
        data.decode("utf-8")
        # If pure ASCII or valid UTF-8
        return EncodingInfo(charset="utf-8", has_bom=False, confidence=0.95)
    except UnicodeDecodeError:
        pass

    # 6. Fallback to Windows-1252 (ANSI)
    return EncodingInfo(charset="cp1252", has_bom=False, confidence=0.80)


def read_text(path: Path) -> tuple[str, EncodingInfo]:
    """Read file content with automatic encoding detection."""
    raw = path.read_bytes()
    enc = detect_encoding(raw)

    # Python's 'utf-8-sig' or 'utf-16' decoders handle the BOM automatically
    if enc.has_bom and enc.charset == "utf-8-sig":
        text = raw.decode("utf-8-sig")
    elif enc.has_bom and enc.charset in ("utf-16-le", "utf-16-be"):
        # decode with the BOM-honoring codec so the BOM does not leak into the
        # text as a leading U+FEFF character (would corrupt the first line)
        text = raw.decode("utf-16")
    else:
        text = raw.decode(enc.charset, errors="replace")

    # Standardize line endings internally to \n for consistent processing
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, enc


def write_text(
    path: Path,
    text: str,
    charset: str = "cp1252",
    crlf: bool = True,
    bom: bool = False,
) -> None:
    """Write text to file with specified encoding and line ending convention.

    By default uses CRLF line endings as required for Empirum Setup.inf.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Normalize input text first
    clean_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if crlf:
        output_text = clean_text.replace("\n", "\r\n")
    else:
        output_text = clean_text

    encoding_name = charset
    if bom:
        if charset in ("utf-8", "utf-8-sig"):
            encoding_name = "utf-8-sig"
        elif charset in ("utf-16", "utf-16-le"):
            encoding_name = "utf-16"

    encoded_bytes = output_text.encode(encoding_name, errors="replace")
    path.write_bytes(encoded_bytes)
