"""Docstring normalization and convention checks.

Docstring convention for ``##`` blocks (robotraconteur_standards
``draft/service_defintion.md``):

* The first line is a one-line summary.
* The body is reStructuredText. The only field-list fields are
  ``:param name:``, ``:return:`` and ``:raises ExcType:``.
* ``:type:`` and ``:rtype:`` are not used; types come from the robdef signature.
* Document units, frames, array ordering, limits, blocking behavior and
  whether the member moves hardware.
* ASCII only (the parser regex is ``^[ \\t]*##([ -~\\t]*)$``).
"""

from __future__ import annotations

import re
import textwrap
from typing import Optional

from .parser import MemberDef

__all__ = ["check_docstring", "clean_docstring", "indent_docstring"]

PARAM_FIELDS = ("param", "parameter", "arg", "argument")
RETURN_FIELDS = ("return", "returns")
RAISES_FIELDS = ("raises", "raise", "exception", "except")
TYPE_FIELDS = ("type", "rtype")

_FIELD_RE = re.compile(r"^:([A-Za-z]+)(?:[ \t]+([^:]+?))?[ \t]*:(?:[ \t]|$)")


def clean_docstring(docstring: str) -> str:
    """Strip the common leading whitespace and surrounding blank lines.

    ``##`` captures keep the text after the marker verbatim, so most lines
    start with a single space; nested indentation in the RST body is preserved
    relative to the least indented line.
    """
    lines = [line.rstrip() for line in docstring.expandtabs(8).split("\n")]
    text = textwrap.dedent("\n".join(lines))
    return text.strip("\n")


def indent_docstring(docstring: str, indent: str) -> list[str]:
    """Return cleaned docstring lines indented for a directive body."""
    text = clean_docstring(docstring)
    if not text:
        return []
    return [indent + line if line else "" for line in text.split("\n")]


def check_docstring(docstring: str, member: Optional[MemberDef] = None) -> list[str]:
    """Return human-readable convention violations for a docstring."""
    problems: list[str] = []
    text = clean_docstring(docstring)
    if not text:
        return problems
    first = text.split("\n", 1)[0]
    if _FIELD_RE.match(first):
        problems.append("docstring must start with a one-line summary, not a field list")

    param_names = {p.name for p in member.params} if member is not None else set()
    has_params = member is not None and member.has_params
    returns_value = (
        member is not None
        and member.kind in ("function", "callback")
        and member.type is not None
        and member.type.base != "void"
    )

    for line in text.split("\n"):
        m = _FIELD_RE.match(line)
        if m is None:
            continue
        name, arg = m.group(1), (m.group(2) or "").strip()
        if name in TYPE_FIELDS:
            problems.append(f":{name}: is not used; types come from the robdef signature")
        elif name in PARAM_FIELDS:
            if not has_params:
                problems.append(f":{name} {arg}: used on a declaration without parameters")
            elif len(arg.split()) != 1:
                problems.append(f":{name} {arg}: must name exactly one parameter, without a type")
            elif arg not in param_names:
                problems.append(f":{name} {arg}: does not match a parameter in the signature")
        elif name in RETURN_FIELDS:
            if not returns_value:
                problems.append(f":{name}: used on a declaration that does not return a value")
        elif name in RAISES_FIELDS:
            if not arg:
                problems.append(f":{name}: requires an exception type")
        else:
            problems.append(f":{name}: is not a supported field; use :param:, :return: or :raises:")
    return problems
