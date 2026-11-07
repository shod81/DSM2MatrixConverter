"""Loader and models for Empirum reference and package standard data."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

REF_DIR = Path(__file__).parent


class SectionKey(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    required: bool = False
    allowed_values: list[str] | None = None
    default: str | None = None


class SectionDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    required: bool = False
    description: str = ""
    doc_ref: str = ""
    allowed_keys: list[SectionKey] = []


class CommandDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    category: str = ""
    doc_ref: str = ""
    signature: str = ""
    description: str = ""
    sets_errorlevel: bool = False
    allowed_values: list[str] | None = None


class FlagDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str = ""
    doc_ref: str = ""


class RegFlagDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    flag: str
    type_name: str
    description: str = ""
    doc_ref: str = ""


class VariableDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str = ""
    category: str = ""
    doc_ref: str = ""


class DsmVarMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    dsm: str
    empirum: str
    id: str


class FunctionDef(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    signature: str = ""
    return_type: str = ""
    doc_ref: str = ""
    description: str = ""


def _load_yaml(filename: str) -> dict[str, Any]:
    file_path = REF_DIR / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Reference file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        data: Any = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
        return {}


@lru_cache(maxsize=1)
def get_sections() -> dict[str, SectionDef]:
    data = _load_yaml("sections.yaml")
    sections_list = data.get("sections", [])
    return {s["name"].lower(): SectionDef(**s) for s in sections_list}


@lru_cache(maxsize=1)
def get_commands() -> dict[str, CommandDef]:
    data = _load_yaml("commands.yaml")
    commands_list = data.get("commands", [])
    return {c["name"].lower(): CommandDef(**c) for c in commands_list}


@lru_cache(maxsize=1)
def get_flags() -> dict[str, Any]:
    data = _load_yaml("flags.yaml")
    return {
        "section_flags": {f["name"].upper(): FlagDef(**f) for f in data.get("section_flags", [])},
        "copy_flags": {f["name"].upper(): FlagDef(**f) for f in data.get("copy_flags", [])},
        "reg_flags": {f["flag"]: RegFlagDef(**f) for f in data.get("reg_flags", [])},
    }


@lru_cache(maxsize=1)
def get_variables() -> dict[str, Any]:
    data = _load_yaml("variables.yaml")
    return {
        "empirum": {v["name"].lower(): VariableDef(**v) for v in data.get("empirum_variables", [])},
        "dsm_mapping": [DsmVarMapping(**m) for m in data.get("dsm_variable_mappings", [])],
    }


@lru_cache(maxsize=1)
def get_functions() -> dict[str, FunctionDef]:
    data = _load_yaml("functions.yaml")
    func_list = data.get("functions", [])
    return {f["name"].lower(): FunctionDef(**f) for f in func_list}


@lru_cache(maxsize=1)
def get_package_standard() -> dict[str, Any]:
    return _load_yaml("package_standard.yaml")
