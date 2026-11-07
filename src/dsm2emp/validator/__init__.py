"""Setup.inf validation and parsing package."""

from dsm2emp.validator.parser import parse_setup_inf
from dsm2emp.validator.rules import (
    validate_document,
    validate_file,
    validate_fragment,
    validate_text,
)

__all__ = [
    "parse_setup_inf",
    "validate_document",
    "validate_file",
    "validate_fragment",
    "validate_text",
]
