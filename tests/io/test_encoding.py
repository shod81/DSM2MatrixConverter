"""Unit tests for encoding detection and file I/O."""

from pathlib import Path

from dsm2emp.io.encoding import detect_encoding, read_text, write_text


def test_detect_empty_bytes() -> None:
    enc = detect_encoding(b"")
    assert enc.charset == "utf-8"
    assert enc.has_bom is False


def test_detect_utf8_bom() -> None:
    data = b"\xef\xbb\xbf[SetupInfo]\r\nDescription=Test\r\n"
    enc = detect_encoding(data)
    assert enc.charset == "utf-8-sig"
    assert enc.has_bom is True
    assert enc.confidence == 1.0


def test_detect_utf16_le_bom() -> None:
    text = "[SetupInfo]\r\n"
    data = b"\xff\xfe" + text.encode("utf-16-le")
    enc = detect_encoding(data)
    assert enc.charset == "utf-16-le"
    assert enc.has_bom is True


def test_detect_utf16_be_bom() -> None:
    text = "[SetupInfo]\r\n"
    data = b"\xfe\xff" + text.encode("utf-16-be")
    enc = detect_encoding(data)
    assert enc.charset == "utf-16-be"
    assert enc.has_bom is True


def test_detect_utf8_without_bom() -> None:
    data = "Installation für Testbenutzer: äöüß".encode()
    enc = detect_encoding(data)
    assert enc.charset == "utf-8"
    assert enc.has_bom is False
    assert enc.confidence >= 0.9


def test_detect_cp1252_ansi_umlauts() -> None:
    # 0xE4 = ä, 0xF6 = ö, 0xFC = ü, 0xDF = ß in cp1252 (invalid UTF-8 byte sequence)
    data = b"Installation f\xfcr: \xe4\xf6\xfc\xdf"
    enc = detect_encoding(data)
    assert enc.charset == "cp1252"
    assert enc.has_bom is False


def test_detect_cp1252_euro_symbol() -> None:
    # 0x80 is Euro sign in cp1252 (invalid UTF-8 start byte)
    data = b"Preis: 100 \x80"
    enc = detect_encoding(data)
    assert enc.charset == "cp1252"


def test_read_text_utf8_bom(tmp_path: Path) -> None:
    p = tmp_path / "test_utf8_bom.inf"
    content = "[SetupInfo]\r\nAuthor=Admin\r\n"
    p.write_bytes(b"\xef\xbb\xbf" + content.encode())

    text, enc = read_text(p)
    assert enc.charset == "utf-8-sig"
    assert enc.has_bom is True
    assert "Author=Admin" in text
    assert "\r" not in text  # Normalized to \n


def test_read_text_cp1252(tmp_path: Path) -> None:
    p = tmp_path / "test_cp1252.inf"
    raw = b"[Strings:07]\r\nInstallationFor=Installation f\xfcr:\r\n"
    p.write_bytes(raw)

    text, enc = read_text(p)
    assert enc.charset == "cp1252"
    assert "Installation für:" in text
    assert "\r" not in text


def test_read_text_utf16_le(tmp_path: Path) -> None:
    p = tmp_path / "test_utf16.inf"
    raw = b"\xff\xfe" + "ProductName=Empirum\n".encode("utf-16-le")
    p.write_bytes(raw)

    text, enc = read_text(p)
    assert enc.charset == "utf-16-le"
    assert "ProductName=Empirum" in text


def test_write_text_crlf_enforcement(tmp_path: Path) -> None:
    p = tmp_path / "out.inf"
    write_text(p, "[Setup]\nVersion=14.2\nPlatform=*", charset="cp1252", crlf=True)

    raw = p.read_bytes()
    assert b"[Setup]\r\nVersion=14.2\r\nPlatform=*" == raw


def test_write_text_with_bom(tmp_path: Path) -> None:
    p = tmp_path / "out_bom.inf"
    write_text(p, "[Setup]\nVersion=14.2", charset="utf-8", bom=True)

    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"[Setup]\r\nVersion=14.2" in raw


def test_roundtrip_german_umlauts_cp1252(tmp_path: Path) -> None:
    p = tmp_path / "umlauts.inf"
    orig = "[Strings:07]\nMsg=Grüße, Äpfel, Überraschung & Spaß\n"
    write_text(p, orig, charset="cp1252", crlf=True)

    text, enc = read_text(p)
    assert enc.charset == "cp1252"
    assert "Grüße, Äpfel, Überraschung & Spaß" in text


def test_read_text_strips_utf16_bom(tmp_path: Path) -> None:
    """Regression: decoding UTF-16 with BOM must not leak U+FEFF into the text."""
    p = tmp_path / "utf16.inc"
    content = "REGEDIT4\r\n[HKEY_LOCAL_MACHINE\\Software\\Test]\r\n"
    p.write_bytes(b"\xff\xfe" + content.encode("utf-16-le"))

    text, enc = read_text(p)
    assert enc.charset == "utf-16-le"
    assert not text.startswith("\ufeff")
    assert text.startswith("REGEDIT4")


def test_read_text_strips_utf16_be_bom(tmp_path: Path) -> None:
    p = tmp_path / "utf16be.inc"
    content = "REGEDIT4\r\n"
    p.write_bytes(b"\xfe\xff" + content.encode("utf-16-be"))

    text, enc = read_text(p)
    assert enc.charset == "utf-16-be"
    assert not text.startswith("\ufeff")
    assert text.startswith("REGEDIT4")
