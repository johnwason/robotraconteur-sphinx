"""Pygments lexer for Robot Raconteur service definition (``.robdef``) files.

Registered with Sphinx as ``robdef`` by the extension, and with Pygments
through the ``pygments.lexers`` entry point, so ``.. code-block:: robdef`` and
``.. literalinclude:: x.robdef`` with ``:language: robdef`` are highlighted.
"""

from __future__ import annotations

from pygments.lexer import RegexLexer, bygroups, include, this, using, words
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Whitespace,
)

__all__ = ["RobdefLexer"]

_NAME = r"[a-zA-Z](?:\w*[a-zA-Z0-9])?"
_QNAME = rf"{_NAME}(?:\.{_NAME})*"
_TYPE = rf"{_QNAME}(?:\[[^\]\n]*\])?(?:\{{\w+\}})?"
_PRIMITIVES = (
    "void", "double", "single", "int8", "uint8", "int16", "uint16", "int32", "uint32",
    "int64", "uint64", "string", "cdouble", "csingle", "bool", "varvalue", "varobject",
)


class RobdefLexer(RegexLexer):
    """Lexer for Robot Raconteur service definitions."""

    name = "Robot Raconteur Service Definition"
    aliases = ["robdef", "robotraconteur"]
    filenames = ["*.robdef"]
    mimetypes = ["text/x-robdef"]
    url = "https://github.com/robotraconteur/robotraconteur_standards"

    tokens = {
        "comments": [
            # ## documentation comments are distinguished from # comments
            (r"^([ \t]*)(##.*?)$", bygroups(Whitespace, Comment.Special)),
            (r"^([ \t]*)(#.*?)$", bygroups(Whitespace, Comment.Single)),
        ],
        "literals": [
            (r'"(?:\\.|[^"\\\n])*"', String.Double),
            (r"[+\-]?0x[0-9a-fA-F]+", Number.Hex),
            (r"[+\-]?(?:(?:0|[1-9]\d*)\.\d*|\.\d+)(?:[eE][+\-]?\d+)?", Number.Float),
            (r"[+\-]?(?:0|[1-9]\d*)[eE][+\-]?\d+", Number.Float),
            (r"[+\-]?(?:0|[1-9]\d*)", Number.Integer),
        ],
        "root": [
            include("comments"),
            (r"\n", Whitespace),
            (r"[ \t]+", Whitespace),
            (r"\\\n", Whitespace),  # line continuation
            (rf"\b(service|import)([ \t]+)({_QNAME})", bygroups(Keyword.Namespace, Whitespace, Name.Namespace)),
            (
                rf"\b(using)([ \t]+)({_QNAME})(?:([ \t]+)(as)([ \t]+)({_NAME}))?",
                bygroups(Keyword.Namespace, Whitespace, Name.Class, Whitespace, Keyword.Namespace, Whitespace,
                         Name.Class),
            ),
            (r"\b(stdver)([ \t]+)([\d.]+)", bygroups(Keyword.Namespace, Whitespace, Number)),
            (r"\b(option)\b(.*?)$", bygroups(Keyword, using(this, state="literal_line"))),
            (rf"\b(enum)([ \t]+)({_NAME})", bygroups(Keyword.Declaration, Whitespace, Name.Class), "enum"),
            (rf"\b(struct|pod|namedarray|object)([ \t]+)({_NAME})",
             bygroups(Keyword.Declaration, Whitespace, Name.Class)),
            (rf"\b(exception)([ \t]+)({_NAME})", bygroups(Keyword.Declaration, Whitespace, Name.Exception)),
            (rf"\b(implements)([ \t]+)({_QNAME})", bygroups(Keyword, Whitespace, Name.Class)),
            (r"\bend\b", Keyword),
            (
                rf"\b(constant)([ \t]+)(struct|{_TYPE})([ \t]+)({_NAME})",
                bygroups(Keyword.Declaration, Whitespace, using(this, state="type"), Whitespace, Name.Constant),
            ),
            (
                rf"\b(field|property|wire|memory|pipe|objref)([ \t]+)({_TYPE})([ \t]+)({_NAME})",
                bygroups(Keyword.Declaration, Whitespace, using(this, state="type"), Whitespace, Name.Variable),
                "after_member",
            ),
            (
                rf"\b(function|callback)([ \t]+)({_TYPE})([ \t]+)({_NAME})",
                bygroups(Keyword.Declaration, Whitespace, using(this, state="type"), Whitespace, Name.Function),
                "after_member",
            ),
            (rf"\b(event)([ \t]+)({_NAME})", bygroups(Keyword.Declaration, Whitespace, Name.Function),
             "after_member"),
            include("literals"),
            (r"[{}():,=\[\]\-]", Punctuation),
            (_QNAME, Name),
        ],
        "after_member": [
            # Parameter list and/or modifier list after a member name, up to end of line.
            (r"\n", Whitespace, "#pop"),
            (r"[ \t]+", Whitespace),
            (r"\\\n", Whitespace),
            (r"\(", Punctuation, "params"),
            (r"\[", Punctuation, "modifiers"),
        ],
        "params": [
            (r"[ \t]+", Whitespace),
            (r"\\\n", Whitespace),
            (r"\)", Punctuation, "#pop"),
            (r",", Punctuation),
            (rf"({_TYPE})([ \t]+)({_NAME})", bygroups(using(this, state="type"), Whitespace, Name.Variable)),
        ],
        "modifiers": [
            (r"[ \t]+", Whitespace),
            (r"\]", Punctuation, "#pop"),
            (r"[,()]", Punctuation),
            include("literals"),
            (_NAME, Name.Decorator),
        ],
        "type": [
            (words(_PRIMITIVES, suffix=r"\b"), Keyword.Type),
            (r"struct\b", Keyword.Type),
            (_QNAME, Name.Class),
            (r"(\{)(list|int32|string|generator)(\})", bygroups(Punctuation, Keyword.Type, Punctuation)),
            (r"\d+", Number.Integer),
            (r"[\[\],*\-]", Punctuation),
        ],
        "enum": [
            include("comments"),
            (r"\n", Whitespace),
            (r"[ \t]+", Whitespace),
            (r"\bend\b", Keyword, "#pop"),
            (r"=", Operator),
            (r",", Punctuation),
            include("literals"),
            (_NAME, Name.Constant),
        ],
        "literal_line": [
            (r"[ \t]+", Whitespace),
            include("literals"),
            (r"[^ \t]+", Name),
        ],
    }
