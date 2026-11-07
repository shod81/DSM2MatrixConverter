"""Reference models and catalog for Empirum syntax and package standard conventions."""

from dsm2emp.reference.loader import (
    CommandDef,
    DsmVarMapping,
    FlagDef,
    FunctionDef,
    RegFlagDef,
    SectionDef,
    SectionKey,
    VariableDef,
    get_commands,
    get_flags,
    get_functions,
    get_package_standard,
    get_sections,
    get_variables,
)

__all__ = [
    "CommandDef",
    "DsmVarMapping",
    "FlagDef",
    "FunctionDef",
    "RegFlagDef",
    "SectionDef",
    "SectionKey",
    "VariableDef",
    "get_commands",
    "get_flags",
    "get_functions",
    "get_sections",
    "get_package_standard",
    "get_variables",
]
