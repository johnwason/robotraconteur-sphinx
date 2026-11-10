"""Pure-Python parser for Robot Raconteur service definition (``.robdef``) files.

The parser follows the grammar in robotraconteur_standards
``draft/service_defintion.md`` and mirrors the documentation comment handling
of the reference C++ parser (``RobotRaconteurCore/src/ServiceDefinition.cpp``):

* A documentation line matches ``^[ \\t]*##([ -~\\t]*)$``; the captured text is
  kept verbatim (including leading blanks) and lines are joined with ``\\n``.
* At service scope a ``#`` comment line clears the pending docstring.
* A blank line does not clear the pending docstring, but the next ``##`` line
  after a blank line starts a new docstring.
* Inside ``struct``/``pod``/``namedarray``/``object``/``enum`` blocks, comment
  lines behave like blank lines (the reference parser drops them while
  extracting the block).

It is intentionally a documentation parser: it accepts every valid service
definition and reports obvious syntax errors, but it does not perform the full
semantic verification that ``RobotRaconteur.ServiceDefinition`` does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Union

__all__ = [
    "PRIMITIVE_TYPES",
    "ConstantDef",
    "EntryDef",
    "EnumDef",
    "EnumValueDef",
    "ExceptionDef",
    "MemberDef",
    "RobdefParseError",
    "ServiceDef",
    "TypeRef",
    "parse_robdef",
    "parse_robdef_file",
]

PRIMITIVE_TYPES = frozenset(
    [
        "void",
        "double",
        "single",
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "string",
        "cdouble",
        "csingle",
        "bool",
        "varvalue",
        "varobject",
    ]
)

_DOC_RE = re.compile(r"^[ \t]*##([ -~\t]*)$")
_COMMENT_RE = re.compile(r"^[ \t]*#(?!#)[ -~\t]*$")
_EMPTY_RE = re.compile(r"^[ \t]*$")
_VALID_RE = re.compile(r"^[ -~\t]*$")

_NAME = r"[a-zA-Z](?:\w*[a-zA-Z0-9])?"
_QNAME = rf"{_NAME}(?:\.{_NAME})*"
_TYPE = rf"{_QNAME}(?:\[[^\]]*\])?(?:\{{\w+\}})?"
_MODS = r"(?:[ \t]*(\[.*\]))?"
_INT = r"[+\-]?(?:0|[1-9]\d*)"
_HEX = r"[+\-]?0x[\da-fA-F]+"

_TYPE_PARTS_RE = re.compile(rf"^({_QNAME})(\[[^\]]*\])?(\{{\w+\}})?$")
_PARAM_RE = re.compile(rf"[ \t]*({_TYPE})[ \t]+({_NAME})[ \t]*(?:,|$)")

_MEMBER_RES = {
    "field": re.compile(rf"^[ \t]*field[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "property": re.compile(rf"^[ \t]*property[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "objref": re.compile(rf"^[ \t]*objref[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "pipe": re.compile(rf"^[ \t]*pipe[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "wire": re.compile(rf"^[ \t]*wire[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "memory": re.compile(rf"^[ \t]*memory[ \t]+({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$"),
    "function": re.compile(
        rf"^[ \t]*function[ \t]+({_TYPE})[ \t]+({_NAME})[ \t]*\(([^)]*)\){_MODS}[ \t]*$"
    ),
    "callback": re.compile(
        rf"^[ \t]*callback[ \t]+({_TYPE})[ \t]+({_NAME})[ \t]*\(([^)]*)\){_MODS}[ \t]*$"
    ),
    "event": re.compile(rf"^[ \t]*event[ \t]+()({_NAME})[ \t]*\(([^)]*)\){_MODS}[ \t]*$"),
}

_CONSTANT_RE = re.compile(rf"^[ \t]*constant[ \t]+(\S+)[ \t]+({_NAME})[ \t]+(.*?)[ \t]*$")
_KEYWORD_RE = re.compile(r"^[ \t]*(\w+)(?:[ \t]+(.*?))?[ \t]*$")
_BLOCK_START_RE = re.compile(rf"^[ \t]*(\w{{1,16}})[ \t]+({_NAME})[ \t]*$")
_END_RE = re.compile(r"^[ \t]*end(?:[ \t]+(\w{1,16}))?[ \t]*$")
_USING_RE = re.compile(rf"^({_NAME}(?:\.{_NAME})+)(?:[ \t]+as[ \t]+({_NAME}))?$")
_ENUM_VALUE_RE = re.compile(rf"^[ \t]*([A-Za-z]\w*)(?:[ \t]*=[ \t]*(?:({_HEX})|({_INT})))?[ \t]*$")


class RobdefParseError(ValueError):
    """Raised when a service definition cannot be parsed."""

    def __init__(self, message: str, filename: Optional[str] = None, lineno: Optional[int] = None):
        self.message = message
        self.filename = filename
        self.lineno = lineno
        loc = ""
        if filename:
            loc = f"{filename}:"
        if lineno is not None:
            loc += f"{lineno}:"
        super().__init__(f"{loc} {message}" if loc else message)


@dataclass
class TypeRef:
    """A type as written in a service definition, e.g. ``double[3]{list}``."""

    base: str
    array: str = ""
    container: str = ""
    name: str = ""
    """Parameter name, when the type is a function/event/callback parameter."""

    @classmethod
    def parse(cls, s: str, name: str = "") -> "TypeRef":
        m = _TYPE_PARTS_RE.match(s.strip())
        if m is None:
            raise RobdefParseError(f"Invalid type: {s!r}")
        return cls(m.group(1), m.group(2) or "", m.group(3) or "", name)

    @property
    def is_primitive(self) -> bool:
        return self.base in PRIMITIVE_TYPES

    def __str__(self) -> str:
        return f"{self.base}{self.array}{self.container}"

    def to_robdef(self) -> str:
        """Type followed by the parameter name, if any."""
        return f"{self} {self.name}" if self.name else str(self)


@dataclass
class MemberDef:
    """A struct/pod/namedarray field or an object member."""

    kind: str
    """One of field, property, function, event, objref, pipe, callback, wire, memory."""
    name: str
    type: Optional[TypeRef] = None
    """Field/property/pipe/wire/memory/objref type, or the function/callback return type."""
    params: list[TypeRef] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    docstring: str = ""
    lineno: Optional[int] = None

    @property
    def has_params(self) -> bool:
        return self.kind in ("function", "callback", "event")

    def signature(self) -> str:
        """The declaration without the leading keyword, e.g. ``void f(int32 a)``."""
        s = ""
        if self.type is not None:
            s = f"{self.type} "
        s += self.name
        if self.has_params:
            s += "(" + ", ".join(p.to_robdef() for p in self.params) + ")"
        if self.modifiers:
            s += " [" + ",".join(self.modifiers) + "]"
        return s

    def to_robdef(self) -> str:
        return f"{self.kind} {self.signature()}"


@dataclass
class ConstantDef:
    name: str
    type: str
    """Constant type as written: a primitive, a 1-D array such as ``double[]``, or ``struct``."""
    value: str
    docstring: str = ""
    lineno: Optional[int] = None

    def signature(self) -> str:
        return f"{self.type} {self.name} {self.value}"

    def to_robdef(self) -> str:
        return f"constant {self.signature()}"


@dataclass
class EnumValueDef:
    name: str
    value: int
    implicit: bool = False
    hex: bool = False
    docstring: str = ""

    def value_str(self) -> str:
        if self.hex:
            return f"-0x{-self.value:x}" if self.value < 0 else f"0x{self.value:x}"
        return str(self.value)


@dataclass
class EnumDef:
    name: str
    values: list[EnumValueDef] = field(default_factory=list)
    docstring: str = ""
    lineno: Optional[int] = None


@dataclass
class ExceptionDef:
    name: str
    docstring: str = ""
    lineno: Optional[int] = None


@dataclass
class EntryDef:
    """A ``struct``, ``pod``, ``namedarray`` or ``object`` block."""

    kind: str
    name: str
    members: list[MemberDef] = field(default_factory=list)
    constants: list[ConstantDef] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    docstring: str = ""
    lineno: Optional[int] = None


Definition = Union[ConstantDef, EnumDef, ExceptionDef, EntryDef]


@dataclass
class ServiceDef:
    name: str = ""
    docstring: str = ""
    stdver: str = ""
    imports: list[str] = field(default_factory=list)
    using: dict[str, str] = field(default_factory=dict)
    """Map of local (unqualified or aliased) name to fully qualified name."""
    options: list[str] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    """All top-level definitions in declaration order."""
    filename: Optional[str] = None

    def _of(self, cls, kind=None):
        return [d for d in self.definitions if isinstance(d, cls) and (kind is None or d.kind == kind)]

    @property
    def constants(self) -> list[ConstantDef]:
        return self._of(ConstantDef)

    @property
    def enums(self) -> list[EnumDef]:
        return self._of(EnumDef)

    @property
    def exceptions(self) -> list[ExceptionDef]:
        return self._of(ExceptionDef)

    @property
    def structs(self) -> list[EntryDef]:
        return self._of(EntryDef, "struct")

    @property
    def pods(self) -> list[EntryDef]:
        return self._of(EntryDef, "pod")

    @property
    def namedarrays(self) -> list[EntryDef]:
        return self._of(EntryDef, "namedarray")

    @property
    def objects(self) -> list[EntryDef]:
        return self._of(EntryDef, "object")

    def local_names(self) -> set[str]:
        return {d.name for d in self.definitions}

    def resolve_type_name(self, name: str) -> Optional[str]:
        """Return the fully qualified name for a type name, or ``None`` for primitives.

        ``using`` aliases are resolved to the imported fully qualified name,
        names declared in this service are qualified with the service name and
        names that are already qualified are returned unchanged.
        """
        if name in PRIMITIVE_TYPES:
            return None
        if name in self.using:
            return self.using[name]
        if "." in name:
            return name
        return f"{self.name}.{name}"


class _LineReader:
    """Port of ``ServiceDefinition_GetLine`` from the reference parser."""

    def __init__(self, lines: list[str], first_lineno: int = 1, filename: Optional[str] = None):
        self._lines = lines
        self._i = 0
        self._first = first_lineno
        self.filename = filename
        self.lineno = first_lineno - 1

    def error(self, msg: str, lineno: Optional[int] = None) -> RobdefParseError:
        return RobdefParseError(msg, self.filename, self.lineno if lineno is None else lineno)

    def _next_raw(self) -> Optional[str]:
        if self._i >= len(self._lines):
            return None
        line = self._lines[self._i].rstrip("\r")
        self._i += 1
        self.lineno = self._first + self._i - 1
        if "\0" in line:
            raise self.error("Service definition must not contain null characters")
        return line

    def get_line(self, return_docstring: bool = False) -> Optional[tuple[int, str, str]]:
        """Return ``(lineno, line, docstring)`` for the next declaration line, or ``None`` at EOF."""
        doc: list[str] = []
        empty_encountered = False
        while True:
            line = self._next_raw()
            if line is None:
                return None
            m = _DOC_RE.match(line)
            if m and not return_docstring:
                if empty_encountered:
                    empty_encountered = False
                    doc.clear()
                doc.append(m.group(1))
                continue
            if _COMMENT_RE.match(line):
                doc.clear()
                continue
            if _EMPTY_RE.match(line):
                empty_encountered = True
                continue
            lineno = self.lineno
            while line.endswith("\\"):
                cont = self._next_raw()
                if cont is None:
                    raise self.error("Service definition line continuation must not be on last line")
                line = line[:-1] + " " + cont
            if not _VALID_RE.match(line):
                raise self.error("Service definition must contain only ASCII characters", lineno)
            return lineno, line, "\n".join(doc)

    def read_block(self, start_line: str) -> tuple[list[str], int]:
        """Collect the body of a block (excluding start and ``end`` lines).

        Mirrors ``ServiceDefinition_FindBlock``: docstring lines are kept,
        comment and blank lines become empty lines so line numbers are preserved.
        Returns the body lines and the line number of the first body line.
        """
        m = _BLOCK_START_RE.match(start_line)
        if m is None:
            raise self.error("Parse error")
        block_type = m.group(1)
        first = self.lineno + 1
        body: list[str] = []
        last = self.lineno
        while True:
            r = self.get_line(return_docstring=True)
            if r is None:
                raise self.error("Block end not found")
            lineno, line, _ = r
            body.extend([""] * (lineno - last - 1))
            last = self.lineno
            em = _END_RE.match(line)
            if em:
                if em.group(1) is not None and em.group(1) != block_type:
                    raise self.error("Block end does not match start", lineno)
                return body, first
            body.append(line)
            # Continuation lines were consumed; keep numbering aligned.
            body.extend([""] * (self.lineno - lineno))


def _split_modifiers(s: Optional[str]) -> list[str]:
    if not s:
        return []
    inner = s.strip()[1:-1]
    out: list[str] = []
    depth = 0
    cur = ""
    for c in inner:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            out.append(re.sub(r"[ \t]+", "", cur))
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(re.sub(r"[ \t]+", "", cur))
    return out


def _parse_params(s: str, reader: _LineReader, lineno: int) -> list[TypeRef]:
    s = s.strip()
    if not s:
        return []
    params: list[TypeRef] = []
    pos = 0
    while pos < len(s):
        m = _PARAM_RE.match(s, pos)
        if m is None:
            raise reader.error(f"Invalid parameter list: ({s})", lineno)
        params.append(TypeRef.parse(m.group(1), m.group(2)))
        pos = m.end()
    return params


def _parse_member(kind: str, line: str, doc: str, reader: _LineReader, lineno: int) -> MemberDef:
    m = _MEMBER_RES[kind].match(line)
    if m is None:
        raise reader.error(f"Invalid {kind} declaration: {line.strip()}", lineno)
    type_s, name = m.group(1), m.group(2)
    params: list[TypeRef] = []
    if kind in ("function", "callback", "event"):
        params = _parse_params(m.group(3), reader, lineno)
        mods = m.group(4)
    else:
        mods = m.group(3)
    return MemberDef(
        kind=kind,
        name=name,
        type=TypeRef.parse(type_s) if type_s else None,
        params=params,
        modifiers=_split_modifiers(mods),
        docstring=doc,
        lineno=lineno,
    )


def _parse_constant(line: str, doc: str, reader: _LineReader, lineno: int) -> ConstantDef:
    m = _CONSTANT_RE.match(line)
    if m is None:
        raise reader.error(f"Invalid constant declaration: {line.strip()}", lineno)
    return ConstantDef(name=m.group(2), type=m.group(1), value=m.group(3), docstring=doc, lineno=lineno)


_ENTRY_KINDS = ("struct", "pod", "namedarray", "object")
_STRUCT_MEMBERS = ("field",)
_OBJECT_MEMBERS = ("property", "function", "event", "objref", "pipe", "callback", "wire", "memory")


def _parse_entry(kind: str, name: str, body: list[str], first: int, doc: str, reader: _LineReader,
                 lineno: int) -> EntryDef:
    entry = EntryDef(kind=kind, name=name, docstring=doc, lineno=lineno)
    sub = _LineReader(body, first, reader.filename)
    allowed = _OBJECT_MEMBERS if kind == "object" else _STRUCT_MEMBERS
    while True:
        r = sub.get_line()
        if r is None:
            break
        ln, line, mdoc = r
        km = _KEYWORD_RE.match(line)
        keyword = km.group(1) if km else ""
        if keyword in allowed:
            entry.members.append(_parse_member(keyword, line, mdoc, sub, ln))
        elif keyword == "constant":
            entry.constants.append(_parse_constant(line, mdoc, sub, ln))
        elif keyword == "implements" and kind == "object":
            entry.implements.append(km.group(2))
        elif keyword == "option":
            entry.options.append(km.group(2) or "")
        else:
            raise sub.error(f"Invalid declaration in {kind} {name}: {line.strip()}", ln)
    return entry


def _parse_enum(name: str, body: list[str], first: int, doc: str, reader: _LineReader, lineno: int) -> EnumDef:
    """Port of ``EnumDefinition::FromString``."""
    enum = EnumDef(name=name, docstring=doc, lineno=lineno)
    docv: list[str] = []
    empty_encountered = False
    comma_endl = True
    next_value = 0
    for i, line in enumerate(body):
        ln = first + i
        m = _DOC_RE.match(line)
        if m:
            if empty_encountered:
                empty_encountered = False
                docv.clear()
            docv.append(m.group(1))
            continue
        if _EMPTY_RE.match(line):
            empty_encountered = True
            continue
        if not comma_endl:
            raise reader.error("Enum parse error", ln)
        line = line.strip()
        comma_endl = line.endswith(",")
        line = line.rstrip(",")
        for item in line.split(","):
            vm = _ENUM_VALUE_RE.match(item)
            if vm is None:
                raise reader.error(f"Enum parse error: {item.strip()!r}", ln)
            v = EnumValueDef(name=vm.group(1), value=next_value, implicit=True)
            if docv:
                v.docstring = "\n".join(docv)
            empty_encountered = False
            docv.clear()
            if vm.group(2) is not None:
                v.value = int(vm.group(2), 16)
                v.hex = True
                v.implicit = False
            elif vm.group(3) is not None:
                v.value = int(vm.group(3))
                v.implicit = False
            elif not enum.values:
                raise reader.error("Enum first value must be specified", ln)
            next_value = v.value + 1
            enum.values.append(v)
    if comma_endl and enum.values:
        raise reader.error("Enum must not end with a comma", lineno)
    return enum


def parse_robdef(text: str, filename: Optional[str] = None) -> ServiceDef:
    """Parse the text of a service definition."""
    reader = _LineReader(text.split("\n"), 1, filename)
    svc = ServiceDef(filename=filename)
    while True:
        r = reader.get_line()
        if r is None:
            break
        lineno, line, doc = r
        km = _KEYWORD_RE.match(line)
        if km is None:
            raise reader.error(f"Parse error: {line.strip()}", lineno)
        keyword, rest = km.group(1), km.group(2) or ""
        if keyword != "service" and not svc.name:
            raise reader.error("service name must be first entry in service definition", lineno)
        if keyword == "service":
            if svc.name:
                raise reader.error("service name already specified", lineno)
            if not re.fullmatch(_QNAME, rest):
                raise reader.error(f"Invalid service name: {rest!r}", lineno)
            svc.name = rest
            svc.docstring = doc
        elif keyword == "stdver":
            svc.stdver = rest
        elif keyword == "import":
            svc.imports.append(rest)
        elif keyword == "using":
            um = _USING_RE.match(rest)
            if um is None:
                raise reader.error(f"Invalid using declaration: {rest!r}", lineno)
            qualified = um.group(1)
            local = um.group(2) or qualified.rsplit(".", 1)[1]
            svc.using[local] = qualified
        elif keyword == "option":
            svc.options.append(rest)
        elif keyword == "constant":
            svc.definitions.append(_parse_constant(line, doc, reader, lineno))
        elif keyword == "exception":
            if not re.fullmatch(_NAME, rest):
                raise reader.error(f"Invalid exception name: {rest!r}", lineno)
            svc.definitions.append(ExceptionDef(name=rest, docstring=doc, lineno=lineno))
        elif keyword in _ENTRY_KINDS or keyword == "enum":
            body, first = reader.read_block(line)
            if keyword == "enum":
                svc.definitions.append(_parse_enum(rest, body, first, doc, reader, lineno))
            else:
                svc.definitions.append(_parse_entry(keyword, rest, body, first, doc, reader, lineno))
        else:
            raise reader.error(f"Unknown declaration: {line.strip()}", lineno)
    if not svc.name:
        raise RobdefParseError("Service name not found", filename)
    return svc


def parse_robdef_file(path: Union[str, Path]) -> ServiceDef:
    path = Path(path)
    # Read as latin-1 so non-ASCII bytes reach the ASCII check instead of
    # failing in the decoder.
    return parse_robdef(path.read_text(encoding="latin-1"), str(path))


def iter_robdef_files(paths: list[Union[str, Path]]) -> Iterator[Path]:
    """Expand directories (recursively) to ``*.robdef`` files, sorted."""
    for p in paths:
        p = Path(p)
        if p.is_dir():
            yield from sorted(p.rglob("*.robdef"))
        else:
            yield p
