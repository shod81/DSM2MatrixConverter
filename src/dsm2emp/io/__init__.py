"""I/O package for DSM2Empirum."""

from dsm2emp.io.encoding import EncodingInfo, detect_encoding, read_text, write_text

__all__ = ["EncodingInfo", "detect_encoding", "read_text", "write_text"]
