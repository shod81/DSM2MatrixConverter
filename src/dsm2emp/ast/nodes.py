"""AST node definitions for Matrix42 Empirum Setup.inf."""

from enum import StrEnum
from typing import Literal

from dsm2emp.ast.values import Value, _Node


class SectionKind(StrEnum):
    """Classification of sections in Setup.inf."""

    META = "meta"  # SetupInfo, Setup, Application, Environment, ...
    OPTIONS = "options"  # Options
    WORK = "work"  # [Product], [<Option>], [Set:Xxx]
    TYPED = "typed"  # [Reg:Xxx], [Ini:Xxx], [Shell:Xxx], [Security:Xxx]
    SUPPORT = "support"  # Services, Processes, Disks, Strings:xx, SysStrings:xx


class Comment(_Node):
    """Comment line starting with ';' or 'Rem'."""

    text: str
    style: Literal["semicolon", "rem"] = "semicolon"


class EmptyLine(_Node):
    """Empty line for formatting."""

    pass


class KeyValue(_Node):
    """Key=Value pair in meta or configuration sections."""

    key: str
    value: Value | str


class FunctionCall(_Node):
    """Function call inside If conditions or expressions (e.g. DoesFileExist(...))."""

    function: str
    args: list[Value | str] = []


class Comparison(_Node):
    """Binary comparison in If condition (e.g. "%ErrorLevel%" == "3010")."""

    left: Value | FunctionCall | str
    relation: Literal["==", "=", "!=", "<>", "<", "<=", ">", ">="]
    right: Value | FunctionCall | str


class GroupCondition(_Node):
    """Logical grouping of conditions with & or |."""

    terms: list["Condition"]
    op: Literal["&", "|"]


Condition = Comparison | GroupCondition | FunctionCall


class Command(_Node):
    """Base class for internal script commands."""

    name: str
    args: list[Value | str] = []
    uninstall_only: bool = False  # Prepends '-' in Setup.inf
    source_trace: str | None = None


class CallStmt(Command):
    """Call, CallHidden, CallRunAs, or CallRunAsHidden execution command."""

    name: Literal["Call", "CallHidden", "CallRunAs", "CallRunAsHidden"] = "CallHidden"
    program: Value | str
    arguments: list[Value | str] = []
    runas_user: str | None = None
    runas_password_ref: str | None = None


class SetStmt(Command):
    """Set <Var>=<Value> command."""

    name: Literal["Set"] = "Set"
    variable: str
    value: Value | FunctionCall | str


class SetRebootStmt(Command):
    """SetReboot <Value> command."""

    name: Literal["SetReboot"] = "SetReboot"
    mode: int = 1  # 0..5


class IfStmt(Command):
    """If <Condition> Then "<Section>" [Else "<Section>"] EndIf."""

    name: Literal["If"] = "If"
    condition: Condition
    then_target: str
    else_target: str | None = None
    group_test: str | None = None  # e.g. INGLOBALGROUP "Group"


class ForStmt(Command):
    """For <Counter>, <Lower>, <Upper>, <Step>, <Section> loop."""

    name: Literal["For"] = "For"
    counter: str
    lower: int
    upper: int
    step: int | None = None
    body_section: str


class SectionRef(_Node):
    """Section call line: #<Name> [, Flags] or #!<Name>."""

    target: str  # e.g. "Set:Product", "Reg:Product"
    force: bool = False  # '#!' always execute
    flags: list[str] = []  # DONTDELETE, DELETE, CLIENT, etc.
    uninstall_only: bool = False
    source_trace: str | None = None


class CopyEntry(_Node):
    """File copy entry: <Disk>:<Source>, <Destination>, <Flags>, <Size>."""

    disk: int = 1
    source: str
    destination: str
    flags: list[str] = []
    size: int = 0
    service_or_font: str | None = None
    uninstall_only: bool = False
    source_trace: str | None = None


class RegEntry(_Node):
    """Registry entry in [Reg:Xxx] section."""

    root: str  # HKLM | HKCU | HKCR | HKU
    key: str
    value_name: str | None = None
    type_flag: str = "0x00000000"  # REG_SZ default
    data: list[Value | str] = []
    behavior_add: int = 0
    delete: bool = False  # '-' prefix before root key
    delete_value: str | None = None
    uninstall_only: bool = False
    source_trace: str | None = None


class ShellEntry(_Node):
    """Shortcut link entry in [Shell:Xxx] section."""

    link: str
    command: str
    arguments: str = ""
    workdir: str = ""
    description: str = ""
    icon_file: str = ""
    icon_index: int = 0
    window_state: int = 1
    hotkey: int = 0
    uninstall_only: bool = False
    source_trace: str | None = None


class ServiceEntry(_Node):
    """Windows service entry in [Services] section."""

    name: str
    display: str = ""
    service_type: str = "SERVICE_WIN32_OWN_PROCESS"
    start_type: str = "SERVICE_DEMAND_START"
    error_control: str = "SERVICE_ERROR_NORMAL"
    load_group: str = ""
    dependencies: list[str] = []
    account: str = ""
    password_ref: str | None = None
    event_source: str = ""
    start_params: str = ""
    uninstall_only: bool = False
    source_trace: str | None = None


SectionLine = (
    KeyValue
    | Comment
    | EmptyLine
    | CopyEntry
    | RegEntry
    | SectionRef
    | ShellEntry
    | ServiceEntry
    | CallStmt
    | SetStmt
    | SetRebootStmt
    | IfStmt
    | ForStmt
    | Command
)


class Section(_Node):
    """Section in Setup.inf containing typed lines."""

    name: str
    kind: SectionKind
    typed_prefix: str | None = None
    lines: list[SectionLine] = []


class InfDocument(_Node):
    """Complete, immutable Setup.inf document AST."""

    sections: list[Section]

    def section(self, name: str) -> Section | None:
        """Find section by case-insensitive name."""
        target = name.strip().lower()
        for sec in self.sections:
            if sec.name.strip().lower() == target:
                return sec
        return None

    def get_section(self, name: str) -> Section | None:
        """Alias for section(name)."""
        return self.section(name)

    def product(self) -> Section:
        """Retrieve the mandatory [Product] section."""
        sec = self.section("Product")
        if sec is None:
            raise ValueError("Document has no mandatory [Product] section")
        return sec
