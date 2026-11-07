"""DSM parser package for eScript, NIR registry, and metadata."""

from dsm2emp.parser.escript import parse_script
from dsm2emp.parser.ir import (
    IrCommand,
    IrComment,
    IrCompositeValue,
    IrCondition,
    IrFallbackVar,
    IrGoto,
    IrIf,
    IrLabel,
    IrLiteral,
    IrNestedVar,
    IrNode,
    IrPackage,
    IrScript,
    IrTodo,
    IrValue,
    IrVarRef,
    SourceRef,
)
from dsm2emp.parser.nir import IrRegKey, IrRegValue, parse_nir

__all__ = [
    "IrCommand",
    "IrComment",
    "IrCompositeValue",
    "IrCondition",
    "IrFallbackVar",
    "IrGoto",
    "IrIf",
    "IrLabel",
    "IrLiteral",
    "IrNestedVar",
    "IrNode",
    "IrPackage",
    "IrRegKey",
    "IrRegValue",
    "IrScript",
    "IrTodo",
    "IrValue",
    "IrVarRef",
    "SourceRef",
    "parse_nir",
    "parse_script",
]
