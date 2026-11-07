"""Typed Intermediate Representation (IR) for parsed DSM packages.

Models DSM eScript commands, conditions, control flow, and package structure
before transformation into Empirum Setup.inf AST.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    """Source code reference indicating origin of an IR node."""

    model_config = ConfigDict(frozen=True)

    file: Path
    line: int
    col: int = 1
    raw: str = ""


# --- Values ---


class IrLiteral(BaseModel):
    """Literal string or constant value."""

    model_config = ConfigDict(frozen=True)
    type: Literal["literal"] = "literal"
    value: str


class IrVarRef(BaseModel):
    """DSM variable reference, e.g. %ProgramFiles% or %ErrorLevel%."""

    model_config = ConfigDict(frozen=True)
    type: Literal["var_ref"] = "var_ref"
    name: str


class IrNestedVar(BaseModel):
    """Nested DSM variable, e.g. %[Server%Number%]%."""

    model_config = ConfigDict(frozen=True)
    type: Literal["nested_var"] = "nested_var"
    outer: str
    inner: IrValue


class IrFallbackVar(BaseModel):
    """DSM variable with fallback, e.g. %[~Var~Default]% or %[~(int)Var~0]%."""

    model_config = ConfigDict(frozen=True)
    type: Literal["fallback_var"] = "fallback_var"
    name: str
    fallback: str
    is_int: bool = False


class IrCompositeValue(BaseModel):
    """Composite string with interleaved literals and variables."""

    model_config = ConfigDict(frozen=True)
    type: Literal["composite"] = "composite"
    parts: list[IrValue] = Field(default_factory=list)


IrValue = Annotated[
    IrLiteral | IrVarRef | IrNestedVar | IrFallbackVar | IrCompositeValue,
    Field(discriminator="type"),
]


# --- Conditions ---


class IrCondition(BaseModel):
    """Condition evaluated in an If-statement."""

    model_config = ConfigDict(frozen=True)

    raw: str
    kind: str  # "comparison", "function", "raw"
    left: IrValue | None = None
    op: str | None = None  # "=", "!=", "<", ">", "<=", ">="
    right: IrValue | None = None
    func_name: str | None = None
    func_args: list[IrValue] = Field(default_factory=list)
    negated: bool = False
    logical_op: Literal["|", "&"] | None = None


# --- Commands and Control Flow ---


class IrCommand(BaseModel):
    """A standard DSM eScript command (e.g. ExecuteEx, Copy, Set, RegLoad)."""

    model_config = ConfigDict(frozen=True)
    type: Literal["command"] = "command"

    kind: str  # "ExecuteEx", "Copy", "Set", "CreateLink", "Delete", etc.
    params: dict[str, IrValue] = Field(default_factory=dict)
    raw_args: list[IrValue] = Field(default_factory=list)
    phase: Literal["install", "uninstall", "both"] = "install"
    context: Literal["user", "machine", "service", "unknown"] = "machine"
    x64_redirect_off: bool = False
    continue_on_error: bool = False
    prevent_uninstall: bool = False
    src: SourceRef


class IrIf(BaseModel):
    """Conditional block with Then and optional Else branch."""

    model_config = ConfigDict(frozen=True)
    type: Literal["if"] = "if"

    conditions: list[IrCondition] = Field(default_factory=list)
    condition_op: Literal["|", "&"] = "|"
    is_mixed: bool = False
    then_body: list[IrNode] = Field(default_factory=list)
    else_body: list[IrNode] = Field(default_factory=list)
    src: SourceRef


class IrLabel(BaseModel):
    """Target label for GOTO statements."""

    model_config = ConfigDict(frozen=True)
    type: Literal["label"] = "label"

    name: str
    src: SourceRef


class IrGoto(BaseModel):
    """Jump to label."""

    model_config = ConfigDict(frozen=True)
    type: Literal["goto"] = "goto"

    target: str
    src: SourceRef


class IrTodo(BaseModel):
    """Unrecognized or unconvertible command preserved for review."""

    model_config = ConfigDict(frozen=True)
    type: Literal["todo"] = "todo"

    raw: str
    message: str
    src: SourceRef
    confidence: float = 0.0


class IrComment(BaseModel):
    """Script comment line."""

    model_config = ConfigDict(frozen=True)
    type: Literal["comment"] = "comment"

    text: str
    src: SourceRef


IrNode = Annotated[
    IrCommand | IrIf | IrLabel | IrGoto | IrTodo | IrComment,
    Field(discriminator="type"),
]


# Resolve forward references in Pydantic models
IrNestedVar.model_rebuild()
IrCompositeValue.model_rebuild()
IrIf.model_rebuild()


# --- Top-Level Script and Package ---


class IrScript(BaseModel):
    """A single parsed eScript file."""

    model_config = ConfigDict(frozen=True)

    file: Path
    commands: list[IrNode] = Field(default_factory=list)


class IrPackage(BaseModel):
    """Aggregated intermediate representation of a full DSM software package."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    version: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    revision: str | None = None
    revision_comment: str | None = None
    main_script: IrScript | None = None
    additional_scripts: list[IrScript] = Field(default_factory=list)
    registry_files: list[Path] = Field(default_factory=list)
    media_files: list[Path] = Field(default_factory=list)
    msi_product_codes: dict[str, str] = Field(default_factory=dict)
    todos: list[IrTodo] = Field(default_factory=list)
