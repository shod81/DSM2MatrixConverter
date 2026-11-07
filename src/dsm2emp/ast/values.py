"""Value object types for the Empirum Setup.inf AST without quoting decisions."""

from pydantic import BaseModel, ConfigDict


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True)


class LiteralValue(_Node):
    """Raw literal text without quotes."""

    text: str


class VarRef(_Node):
    """%Name% reference, including special forms via flags."""

    name: str
    short_name: bool = False  # %~Var%
    trailing_bs: bool = False  # %Var\%
    leading_bs: bool = False  # %\Var%


class IndirectVar(_Node):
    """%%Outer%Inner%%% - dynamic resolution via ReplaceEnv."""

    outer: str
    inner: VarRef | LiteralValue


class IniRef(_Node):
    """%file,section,key% reference."""

    file: str
    section: str
    key: str


class RegistryRef(_Node):
    """%HKLM,Key,Value% / %HKLM\\Key:Value% reference."""

    root: str
    key: str
    value: str | None = None
    ms_syntax: bool = False  # True => %HKLM,"Key","Value"%


Value = LiteralValue | VarRef | IndirectVar | IniRef | RegistryRef
