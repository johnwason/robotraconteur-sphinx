"""Generate reStructuredText for the ``robdef`` Sphinx domain from service definitions.

One ``.rst`` file is written per service definition. Every declaration is
emitted as a ``robdef`` domain directive, docstrings are dedented and
reindented under their directive, and every non-primitive type in a signature
is written fully qualified (``using`` aliases resolved) so the domain can
render it as a cross-reference.

Command line::

    robdef-sphinx -o docs/robdef --index path/to/robdefs/ extra.robdef
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

from .docstring import check_docstring, indent_docstring
from .parser import (
    ConstantDef,
    EntryDef,
    EnumDef,
    ExceptionDef,
    MemberDef,
    RobdefParseError,
    ServiceDef,
    TypeRef,
    iter_robdef_files,
    parse_robdef_file,
)

__all__ = ["DocstringWarning", "generate_index", "generate_rst", "generate_files", "main"]

INDENT = "   "

_SECTIONS = [
    ("Constants", lambda s: s.constants),
    ("Enums", lambda s: s.enums),
    ("Exceptions", lambda s: s.exceptions),
    ("Structures", lambda s: s.structs),
    ("Pods", lambda s: s.pods),
    ("Named Arrays", lambda s: s.namedarrays),
    ("Objects", lambda s: s.objects),
]


@dataclass
class DocstringWarning:
    filename: Optional[str]
    lineno: Optional[int]
    target: str
    message: str

    def __str__(self) -> str:
        loc = f"{self.filename}:{self.lineno}:" if self.filename else ""
        return f"{loc} {self.target}: {self.message}".strip()


def _heading(title: str, char: str) -> list[str]:
    return [title, char * len(title), ""]


def _qualify_type(svc: ServiceDef, t: TypeRef) -> str:
    q = svc.resolve_type_name(t.base)
    base = q if q is not None else t.base
    s = f"{base}{t.array}{t.container}"
    return f"{s} {t.name}" if t.name else s


def _member_signature(svc: ServiceDef, m: MemberDef) -> str:
    s = ""
    if m.type is not None:
        s = _qualify_type(svc, m.type) + " "
    s += m.name
    if m.has_params:
        s += "(" + ", ".join(_qualify_type(svc, p) for p in m.params) + ")"
    if m.modifiers:
        s += " [" + ", ".join(m.modifiers) + "]"
    return s


class _Writer:
    def __init__(self, svc: ServiceDef, check: bool):
        self.svc = svc
        self.check = check
        self.lines: list[str] = []
        self.warnings: list[DocstringWarning] = []

    def directive(self, indent: str, name: str, argument: str, options=(), docstring: str = "",
                  target: str = "", lineno: Optional[int] = None, member: Optional[MemberDef] = None) -> str:
        self.lines.append(f"{indent}.. robdef:{name}:: {argument}")
        body = indent + INDENT
        for k, v in options:
            self.lines.append(f"{body}:{k}: {v}")
        doc = indent_docstring(docstring, body)
        if doc:
            self.lines.append("")
            self.lines.extend(doc)
        self.lines.append("")
        if self.check:
            for msg in check_docstring(docstring, member):
                self.warnings.append(DocstringWarning(self.svc.filename, lineno, target or argument, msg))
        return body

    def constant(self, indent: str, c: ConstantDef, scope: str) -> None:
        self.directive(indent, "constant", c.signature(), docstring=c.docstring,
                       target=f"{scope}.{c.name}", lineno=c.lineno)

    def enum(self, e: EnumDef) -> None:
        body = self.directive("", "enum", e.name, docstring=e.docstring,
                              target=f"{self.svc.name}.{e.name}", lineno=e.lineno)
        for v in e.values:
            self.directive(body, "enumvalue", f"{v.name} = {v.value_str()}", docstring=v.docstring,
                           target=f"{self.svc.name}.{e.name}.{v.name}", lineno=e.lineno)

    def exception(self, e: ExceptionDef) -> None:
        self.directive("", "exception", e.name, docstring=e.docstring,
                       target=f"{self.svc.name}.{e.name}", lineno=e.lineno)

    def entry(self, e: EntryDef) -> None:
        options = []
        if e.implements:
            impl = [self.svc.resolve_type_name(i) or i for i in e.implements]
            options.append(("implements", ", ".join(impl)))
        scope = f"{self.svc.name}.{e.name}"
        body = self.directive("", e.kind, e.name, options, e.docstring, target=scope, lineno=e.lineno)
        for c in e.constants:
            self.constant(body, c, scope)
        for m in e.members:
            self.directive(body, m.kind, _member_signature(self.svc, m), docstring=m.docstring,
                           target=f"{scope}.{m.name}", lineno=m.lineno, member=m)


def generate_rst(svc: ServiceDef, check: bool = True) -> tuple[str, list[DocstringWarning]]:
    """Return the RST document for a service definition and any docstring convention warnings."""
    w = _Writer(svc, check)
    src = Path(svc.filename).name if svc.filename else "a service definition"
    w.lines += [f".. This file was generated by robdef-sphinx from {src}. Do not edit.", ""]
    w.lines += _heading(svc.name, "=")

    options = []
    if svc.stdver:
        options.append(("stdver", svc.stdver))
    if svc.imports:
        options.append(("imports", ", ".join(svc.imports)))
    w.directive("", "service", svc.name, options, svc.docstring, target=svc.name)

    for title, getter in _SECTIONS:
        defs = getter(svc)
        if not defs:
            continue
        w.lines += _heading(title, "-")
        for d in defs:
            if isinstance(d, ConstantDef):
                w.constant("", d, svc.name)
            elif isinstance(d, EnumDef):
                w.enum(d)
            elif isinstance(d, ExceptionDef):
                w.exception(d)
            else:
                w.entry(d)

    while w.lines and w.lines[-1] == "":
        w.lines.pop()
    return "\n".join(w.lines) + "\n", w.warnings


def generate_index(service_names: Iterable[str], title: str = "Service Definitions", maxdepth: int = 1) -> str:
    lines = _heading(title, "=")
    lines += [".. toctree::", f"{INDENT}:maxdepth: {maxdepth}", ""]
    lines += [f"{INDENT}{name}" for name in sorted(service_names)]
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def generate_files(
    sources: Iterable[Union[str, Path]],
    output_dir: Union[str, Path],
    index: Optional[str] = None,
    index_title: str = "Service Definitions",
    check: bool = True,
) -> tuple[list[Path], list[DocstringWarning]]:
    """Parse robdef files (directories are searched recursively) and write one RST file per service.

    Files are only rewritten when their content changes so Sphinx does not
    rebuild unchanged pages. Returns the written paths and docstring warnings.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    warnings: list[DocstringWarning] = []
    names: list[str] = []
    for path in iter_robdef_files(list(sources)):
        svc = parse_robdef_file(path)
        if svc.name in names:
            raise RobdefParseError(f"Duplicate service definition {svc.name}", str(path))
        names.append(svc.name)
        text, warns = generate_rst(svc, check=check)
        warnings.extend(warns)
        dest = out / f"{svc.name}.rst"
        _write_if_changed(dest, text)
        written.append(dest)
    if index:
        dest = out / f"{index}.rst"
        _write_if_changed(dest, generate_index(names, index_title))
        written.append(dest)
    return written, warnings


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="robdef-sphinx", description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", nargs="+", help="robdef files or directories containing robdef files")
    ap.add_argument("-o", "--output-dir", required=True, help="directory for generated .rst files")
    ap.add_argument("--index", action="store_true", help="also write an index page with a toctree of all services")
    ap.add_argument("--index-name", default="index", help="index page name without .rst (default: index)")
    ap.add_argument("--index-title", default="Service Definitions")
    ap.add_argument("--no-check", action="store_true", help="do not check the docstring convention")
    ap.add_argument("--strict", action="store_true", help="exit with an error on docstring warnings")
    args = ap.parse_args(argv)
    try:
        written, warnings = generate_files(args.sources, args.output_dir,
                                           args.index_name if args.index else None, args.index_title,
                                           check=not args.no_check)
    except (RobdefParseError, OSError) as e:
        print(f"robdef-sphinx: error: {e}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"robdef-sphinx: wrote {len(written)} file(s) to {args.output_dir}")
    return 1 if (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
