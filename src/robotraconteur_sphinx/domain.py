"""The ``robdef`` Sphinx domain for Robot Raconteur service definitions.

Directives
    ``robdef:service``, ``robdef:currentservice``, ``robdef:constant``,
    ``robdef:enum``, ``robdef:enumvalue``, ``robdef:exception``,
    ``robdef:struct``, ``robdef:pod``, ``robdef:namedarray``, ``robdef:field``,
    ``robdef:object`` and the object members ``robdef:property``,
    ``robdef:function``, ``robdef:event``, ``robdef:objref``, ``robdef:pipe``,
    ``robdef:callback``, ``robdef:wire``, ``robdef:memory``.

    Directive arguments use robdef declaration syntax without the leading
    keyword, e.g. ``.. robdef:function:: double{list} f(int32 a) [urgent]``.

Roles
    One role per object type (``:robdef:struct:``, ``:robdef:function:`` ...)
    plus ``:robdef:type:`` (any struct, pod, namedarray, enum or object),
    ``:robdef:member:`` (any field or object member) and ``:robdef:exc:``.
    Targets are resolved relative to the current entry, then the current
    service, then as fully qualified names. ``~`` shortens the title to the
    last name component, as in the Python domain.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any, NamedTuple, Optional

from docutils import nodes
from docutils.nodes import Element, Node
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.addnodes import desc_signature, pending_xref
from sphinx.directives import ObjectDescription
from sphinx.domains import Domain, Index, IndexEntry, ObjType
from sphinx.locale import _
from sphinx.roles import XRefRole
from sphinx.util import logging
from sphinx.util.docfields import Field, GroupedField, TypedField
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import make_id, make_refnode

from .parser import PRIMITIVE_TYPES

logger = logging.getLogger(__name__)

__all__ = ["RobdefDomain", "BUILTIN_EXCEPTIONS"]

#: Exceptions defined by Robot Raconteur itself; ``:raises:`` may name these
#: without a matching ``robdef:exception`` declaration.
BUILTIN_EXCEPTIONS = frozenset(
    """
    RobotRaconteurException RobotRaconteurRemoteException ConnectionException ProtocolException
    ServiceNotFoundException ObjectNotFoundException InvalidEndpointException
    EndpointCommunicationFatalException NodeNotFoundException ServiceException MemberNotFoundException
    MemberFormatMismatchException DataTypeMismatchException DataTypeException DataSerializationException
    MessageEntryNotFoundException MessageElementNotFoundException UnknownException
    InvalidOperationException InvalidArgumentException OperationFailedException NullValueException
    InternalErrorException SystemResourcePermissionDeniedException OutOfSystemResourceException
    SystemResourceException ResourceNotFoundException IOException BufferLimitViolationException
    ServiceDefinitionException OutOfRangeException KeyNotFoundException InvalidConfigurationException
    InvalidStateException RequestTimeoutException ReadOnlyMemberException WriteOnlyMemberException
    NotImplementedException MemberBusyException ValueNotSetException AuthenticationException
    ObjectLockedException PermissionDeniedException AbortOperationException OperationAbortedException
    StopIterationException OperationTimeoutException OperationCancelledException
    """.split()
)

_NAME = r"[a-zA-Z](?:\w*[a-zA-Z0-9])?"
_QNAME = rf"{_NAME}(?:\.{_NAME})*"
_TYPE = rf"{_QNAME}(?:\[[^\]]*\])?(?:\{{\w+\}})?"
_TYPE_PARTS_RE = re.compile(rf"^({_QNAME})(\[[^\]]*\])?(?:\{{(\w+)\}})?$")
_MODS = r"(?:[ \t]*\[(.*)\])?"
_VALUE_SIG_RE = re.compile(rf"^({_TYPE})[ \t]+({_NAME}){_MODS}[ \t]*$")
_FUNC_SIG_RE = re.compile(rf"^({_TYPE})[ \t]+({_NAME})[ \t]*\((.*)\){_MODS}[ \t]*$")
_EVENT_SIG_RE = re.compile(rf"^({_NAME})[ \t]*\((.*)\){_MODS}[ \t]*$")
_PARAM_RE = re.compile(rf"[ \t]*({_TYPE})[ \t]+({_NAME})[ \t]*(?:,|$)")
_CONSTANT_SIG_RE = re.compile(rf"^(\S+)[ \t]+({_NAME})[ \t]+(.+?)[ \t]*$")
_ENUMVALUE_SIG_RE = re.compile(rf"^({_NAME})(?:[ \t]*=[ \t]*(\S+))?[ \t]*$")
_NAME_SIG_RE = re.compile(rf"^({_NAME})$")
_SERVICE_SIG_RE = re.compile(rf"^({_QNAME})$")

ENTRY_TYPES = ("struct", "pod", "namedarray", "enum", "object")
MEMBER_TYPES = ("field", "property", "function", "event", "objref", "pipe", "callback", "wire", "memory")
TYPE_ROLE_OBJTYPES = ("struct", "pod", "namedarray", "enum", "object")


class ObjectEntry(NamedTuple):
    docname: str
    node_id: str
    objtype: str


def _context(env) -> dict[str, Optional[str]]:
    return {
        "robdef:service": env.ref_context.get("robdef:service"),
        "robdef:entry": env.ref_context.get("robdef:entry"),
    }


def _split_params(s: str) -> list[tuple[str, str]]:
    s = s.strip()
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        m = _PARAM_RE.match(s, pos)
        if m is None:
            raise ValueError(f"invalid parameter list: {s!r}")
        out.append((m.group(1), m.group(2)))
        pos = m.end()
    return out


def type_to_nodes(env, typestr: str) -> list[Node]:
    """Render a robdef type with a cross-reference for its named base type."""
    m = _TYPE_PARTS_RE.match(typestr.strip())
    if m is None:
        return [nodes.Text(typestr)]
    base, array, container = m.group(1), m.group(2), m.group(3)
    result: list[Node] = []
    if base in PRIMITIVE_TYPES:
        result.append(addnodes.desc_sig_keyword_type(base, base))
    else:
        service = env.ref_context.get("robdef:service")
        display = base
        if service and base.startswith(service + ".") and "." not in base[len(service) + 1:]:
            display = base[len(service) + 1:]
        ref = pending_xref(
            "", nodes.Text(display), refdomain="robdef", reftype="type", reftarget=base, refexplicit=False
        )
        for k, v in _context(env).items():
            ref[k] = v
        result.append(ref)
    if array:
        result.append(addnodes.desc_sig_punctuation("", "["))
        inner = array[1:-1]
        if inner:
            result.append(addnodes.desc_sig_literal_number(inner, inner))
        result.append(addnodes.desc_sig_punctuation("", "]"))
    if container:
        result.append(addnodes.desc_sig_punctuation("", "{"))
        result.append(addnodes.desc_sig_keyword_type(container, container))
        result.append(addnodes.desc_sig_punctuation("", "}"))
    return result


def _modifier_nodes(mods: Optional[str]) -> list[Node]:
    if not mods:
        return []
    text = " [" + ", ".join(p.strip() for p in mods.split(",") if p.strip()) + "]"
    text = re.sub(r",\s*(?=[^()]*\))", ",", text)  # keep modifier arguments compact
    return [addnodes.desc_annotation(text, text)]


def _keyword(signode: desc_signature, word: str) -> None:
    signode += addnodes.desc_annotation(
        word + " ", "", addnodes.desc_sig_keyword(word, word), addnodes.desc_sig_space()
    )


class RobdefObject(ObjectDescription[tuple[str, str]]):
    """Base for all robdef object descriptions."""

    option_spec = ObjectDescription.option_spec.copy()

    #: Whether the object is a block (struct, object ...) that sets ``robdef:entry`` for its content.
    is_entry = False

    doc_field_types = [
        TypedField(
            "parameter",
            label=_("Parameters"),
            names=("param", "parameter", "arg", "argument"),
            typerolename="type",
            typenames=("type",),
            can_collapse=True,
        ),
        Field("returnvalue", label=_("Returns"), has_arg=False, names=("returns", "return")),
        Field("returntype", label=_("Return type"), has_arg=False, names=("rtype",), bodyrolename="type"),
        GroupedField(
            "exceptions",
            label=_("Raises"),
            rolename="exc",
            names=("raises", "raise", "exception", "except"),
            can_collapse=True,
        ),
    ]

    # -- naming ---------------------------------------------------------------

    @property
    def current_service(self) -> Optional[str]:
        return self.env.ref_context.get("robdef:service")

    @property
    def current_entry(self) -> Optional[str]:
        return self.env.ref_context.get("robdef:entry")

    def qualify(self, name: str) -> str:
        parts = [p for p in (self.current_service, self.current_entry) if p]
        return ".".join(parts + [name])

    def parent_name(self) -> str:
        return ".".join(p for p in (self.current_service, self.current_entry) if p)

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        """Fill ``signode`` and return the unqualified name."""
        raise NotImplementedError

    def handle_signature(self, sig: str, signode: desc_signature) -> tuple[str, str]:
        if not self.current_service and self.objtype != "service":
            logger.warning(
                "robdef:%s declared outside a service; use robdef:service or robdef:currentservice first",
                self.objtype,
                location=signode,
                type="robdef",
                subtype="context",
            )
        try:
            name = self.parse_signature(sig.strip(), signode)
        except ValueError as e:
            logger.warning("invalid robdef:%s signature %r: %s", self.objtype, sig, e, location=signode,
                           type="robdef", subtype="signature")
            raise
        fullname = name if self.objtype == "service" else self.qualify(name)
        signode["service"] = self.current_service or (name if self.objtype == "service" else "")
        signode["entry"] = self.current_entry or ""
        signode["fullname"] = fullname
        return fullname, name

    # -- targets and index -----------------------------------------------------

    def add_target_and_index(self, name: tuple[str, str], sig: str, signode: desc_signature) -> None:
        fullname, short = name
        node_id = make_id(self.env, self.state.document, "robdef", fullname)
        signode["ids"].append(node_id)
        self.state.document.note_explicit_target(signode)
        domain: RobdefDomain = self.env.get_domain("robdef")  # type: ignore[assignment]
        domain.note_object(fullname, self.objtype, node_id, location=signode)
        if "no-index-entry" not in self.options and "noindexentry" not in self.options:
            parent = self.parent_name()
            if self.objtype == "service":
                text = _("%s (robdef service)") % fullname
            else:
                if self.objtype in ("function", "callback", "event"):
                    short += "()"
                text = _("%s (robdef %s in %s)") % (short, self.objtype, parent)
            self.indexnode["entries"].append(("single", text, node_id, "", None))

    # -- nesting ---------------------------------------------------------------

    def before_content(self) -> None:
        if self.is_entry and self.names:
            self.env.ref_context.setdefault("robdef:entries", []).append(self.current_entry)
            self.env.ref_context["robdef:entry"] = self.names[-1][1]

    def after_content(self) -> None:
        if self.is_entry and self.names:
            stack = self.env.ref_context.get("robdef:entries", [])
            prev = stack.pop() if stack else None
            if prev is None:
                self.env.ref_context.pop("robdef:entry", None)
            else:
                self.env.ref_context["robdef:entry"] = prev

    def _object_hierarchy_parts(self, sig_node: desc_signature) -> tuple[str, ...]:
        if "fullname" not in sig_node:
            return ()
        parts = [sig_node["service"]] if sig_node.get("service") else []
        if sig_node.get("entry"):
            parts.append(sig_node["entry"])
        if self.objtype != "service":
            parts.append(sig_node["fullname"].rsplit(".", 1)[-1])
        return tuple(parts)

    def _toc_entry_name(self, sig_node: desc_signature) -> str:
        parts = sig_node.get("_toc_parts")
        if not parts:
            return ""
        name = parts[-1]
        if self.objtype in ("function", "callback", "event"):
            return name + "()"
        return name


class RobdefService(RobdefObject):
    """``.. robdef:service:: com.example.service``; sets the current service."""

    option_spec = RobdefObject.option_spec.copy()
    option_spec.update({"stdver": directives.unchanged, "imports": directives.unchanged})

    def run(self) -> list[Node]:
        name = self.arguments[0].strip()
        self.env.ref_context["robdef:service"] = name
        self.env.ref_context.pop("robdef:entry", None)
        self.env.ref_context.pop("robdef:entries", None)
        return super().run()

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        if not _SERVICE_SIG_RE.match(sig):
            raise ValueError("expected a service name")
        _keyword(signode, "service")
        signode += addnodes.desc_name(sig, sig)
        return sig

    def transform_content(self, content_node: addnodes.desc_content) -> None:
        fields = nodes.field_list()
        if self.options.get("stdver"):
            fields += nodes.field(
                "",
                nodes.field_name("", _("Standard version")),
                nodes.field_body("", nodes.paragraph("", self.options["stdver"])),
            )
        imports = [i.strip() for i in self.options.get("imports", "").split(",") if i.strip()]
        if imports:
            para = nodes.paragraph()
            for i, imp in enumerate(imports):
                if i:
                    para += nodes.Text(", ")
                ref = pending_xref("", nodes.literal(imp, imp), refdomain="robdef", reftype="service",
                                   reftarget=imp, refexplicit=False)
                para += ref
            fields += nodes.field("", nodes.field_name("", _("Imports")), nodes.field_body("", para))
        if len(fields):
            content_node.insert(0, fields)


class RobdefCurrentService(SphinxDirective):
    """``.. robdef:currentservice:: name`` sets the service context without output."""

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec: dict = {}

    def run(self) -> list[Node]:
        name = self.arguments[0].strip()
        if name == "None":
            self.env.ref_context.pop("robdef:service", None)
        else:
            self.env.ref_context["robdef:service"] = name
        self.env.ref_context.pop("robdef:entry", None)
        self.env.ref_context.pop("robdef:entries", None)
        return []


class RobdefNamed(RobdefObject):
    """``exception`` and the block types ``struct``, ``pod``, ``namedarray``, ``enum``, ``object``."""

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        if not _NAME_SIG_RE.match(sig):
            raise ValueError("expected a name")
        _keyword(signode, self.objtype)
        signode += addnodes.desc_name(sig, sig)
        return sig


class RobdefEntry(RobdefNamed):
    is_entry = True


class RobdefObjectEntry(RobdefEntry):
    """``.. robdef:object:: Name`` with optional ``:implements: a.b.C, D``."""

    option_spec = RobdefEntry.option_spec.copy()
    option_spec.update({"implements": directives.unchanged})

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        name = super().parse_signature(sig, signode)
        impl = [i.strip() for i in self.options.get("implements", "").split(",") if i.strip()]
        if impl:
            signode += addnodes.desc_sig_space()
            signode += addnodes.desc_annotation(
                "implements ", "", addnodes.desc_sig_keyword("implements", "implements"),
                addnodes.desc_sig_space()
            )
            for i, t in enumerate(impl):
                if i:
                    signode += addnodes.desc_sig_punctuation("", ",")
                    signode += addnodes.desc_sig_space()
                signode += type_to_nodes(self.env, t)
        return name


class RobdefConstant(RobdefObject):
    """``.. robdef:constant:: double name 1.5``"""

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        m = _CONSTANT_SIG_RE.match(sig)
        if m is None:
            raise ValueError("expected 'type name value'")
        typ, name, value = m.groups()
        _keyword(signode, "constant")
        if typ == "struct":
            signode += addnodes.desc_sig_keyword("struct", "struct")
        else:
            signode += type_to_nodes(self.env, typ)
        signode += addnodes.desc_sig_space()
        signode += addnodes.desc_name(name, name)
        signode += addnodes.desc_annotation(" = " + value, " = " + value)
        return name


class RobdefEnumValue(RobdefObject):
    """``.. robdef:enumvalue:: name = 3``"""

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        m = _ENUMVALUE_SIG_RE.match(sig)
        if m is None:
            raise ValueError("expected 'name' or 'name = value'")
        name, value = m.groups()
        signode += addnodes.desc_name(name, name)
        if value is not None:
            signode += addnodes.desc_annotation(" = " + value, " = " + value)
        return name


class RobdefValueMember(RobdefObject):
    """``field``, ``property``, ``objref``, ``pipe``, ``wire`` and ``memory``: ``type name [modifiers]``."""

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        m = _VALUE_SIG_RE.match(sig)
        if m is None:
            raise ValueError("expected 'type name [modifiers]'")
        typ, name, mods = m.groups()
        _keyword(signode, self.objtype)
        signode += type_to_nodes(self.env, typ)
        signode += addnodes.desc_sig_space()
        signode += addnodes.desc_name(name, name)
        signode += _modifier_nodes(mods)
        return name


class RobdefCallable(RobdefObject):
    """``function``, ``callback`` (``rettype name(params) [modifiers]``) and ``event`` (``name(params)``)."""

    def parse_signature(self, sig: str, signode: desc_signature) -> str:
        if self.objtype == "event":
            m = _EVENT_SIG_RE.match(sig)
            if m is None:
                raise ValueError("expected 'name(params) [modifiers]'")
            rettype = None
            name, params, mods = m.groups()
        else:
            m = _FUNC_SIG_RE.match(sig)
            if m is None:
                raise ValueError("expected 'return_type name(params) [modifiers]'")
            rettype, name, params, mods = m.groups()
        parsed = _split_params(params)
        _keyword(signode, self.objtype)
        if rettype is not None:
            signode += type_to_nodes(self.env, rettype)
            signode += addnodes.desc_sig_space()
        signode += addnodes.desc_name(name, name)
        plist = addnodes.desc_parameterlist()
        for ptype, pname in parsed:
            param = addnodes.desc_parameter("", "")
            param += type_to_nodes(self.env, ptype)
            param += addnodes.desc_sig_space()
            param += addnodes.desc_sig_name(pname, pname)
            plist += param
        signode += plist
        signode += _modifier_nodes(mods)
        self._params = dict((pname, ptype) for ptype, pname in parsed)
        self._rettype = rettype
        return name

    def transform_content(self, content_node: addnodes.desc_content) -> None:
        """Supply parameter and return types from the signature to the field list."""
        params: dict[str, str] = getattr(self, "_params", {})
        rettype: Optional[str] = getattr(self, "_rettype", None)
        for field_list in content_node.findall(nodes.field_list):
            if field_list.parent is not content_node:
                continue
            documented: list[str] = []
            typed: set[str] = set()
            has_return = has_rtype = False
            return_index = len(field_list)
            for idx, fld in enumerate(field_list.children):
                if not isinstance(fld, nodes.field):
                    continue
                parts = fld[0].astext().split(None, 1)
                kind = parts[0]
                arg = parts[1].strip() if len(parts) > 1 else ""
                if kind in ("param", "parameter", "arg", "argument") and arg:
                    documented.append(arg.split()[-1])
                    if len(arg.split()) > 1:
                        typed.add(arg.split()[-1])
                elif kind == "type" and arg:
                    typed.add(arg)
                elif kind in ("return", "returns"):
                    has_return = True
                    return_index = idx + 1
                elif kind == "rtype":
                    has_rtype = True
            for pname in documented:
                if pname in typed:
                    continue
                if pname not in params:
                    logger.warning(
                        "robdef:%s parameter %r is documented but not in the signature",
                        self.objtype, pname, location=field_list, type="robdef", subtype="param",
                    )
                    continue
                field_list += nodes.field(
                    "",
                    nodes.field_name("", "type " + pname),
                    nodes.field_body("", nodes.paragraph("", "", *type_to_nodes(self.env, params[pname]))),
                )
            if has_return and not has_rtype and rettype and rettype != "void":
                field_list.insert(
                    return_index,
                    nodes.field(
                        "",
                        nodes.field_name("", "rtype"),
                        nodes.field_body("", nodes.paragraph("", "", *type_to_nodes(self.env, rettype))),
                    ),
                )


class RobdefXRefRole(XRefRole):
    def process_link(self, env, refnode: Element, has_explicit_title: bool, title: str,
                     target: str) -> tuple[str, str]:
        for k, v in _context(env).items():
            refnode[k] = v
        if not has_explicit_title:
            title = title.lstrip(".")
            target = target.lstrip("~")
            if title.startswith("~"):
                title = title[1:].rpartition(".")[2]
        if target.startswith("."):
            target = target[1:]
            refnode["refspecific"] = True
        return title, target


class RobdefServiceIndex(Index):
    """Index of all documented service definitions."""

    name = "serviceindex"
    localname = _("Robot Raconteur Service Definition Index")
    shortname = _("service definitions")

    def generate(self, docnames: Optional[Iterable[str]] = None) -> tuple[list[tuple[str, list[IndexEntry]]], bool]:
        content: dict[str, list[IndexEntry]] = {}
        domain: RobdefDomain = self.domain  # type: ignore[assignment]
        services = sorted(
            (name, entry) for name, entry in domain.objects.items() if entry.objtype == "service"
        )
        for name, entry in services:
            if docnames is not None and entry.docname not in docnames:
                continue
            group = name.rsplit(".", 1)[0] if "." in name else name
            content.setdefault(group, []).append(IndexEntry(name, 0, entry.docname, entry.node_id, "", "", ""))
        return sorted(content.items()), False


class RobdefDomain(Domain):
    """Robot Raconteur service definition domain."""

    name = "robdef"
    label = "Robot Raconteur"

    object_types = {
        "service": ObjType(_("service"), "service"),
        "constant": ObjType(_("constant"), "constant"),
        "enum": ObjType(_("enum"), "enum", "type"),
        "enumvalue": ObjType(_("enum value"), "enumvalue"),
        "exception": ObjType(_("exception"), "exception", "exc"),
        # struct, pod and namedarray roles resolve to any of the three value
        # types, so :robdef:struct:`Pose` works whichever kind Pose is.
        "struct": ObjType(_("struct"), "struct", "pod", "namedarray", "type"),
        "pod": ObjType(_("pod"), "pod", "struct", "namedarray", "type"),
        "namedarray": ObjType(_("namedarray"), "namedarray", "struct", "pod", "type"),
        "object": ObjType(_("object"), "object", "type"),
        "field": ObjType(_("field"), "field", "member"),
        "property": ObjType(_("property"), "property", "member"),
        "function": ObjType(_("function"), "function", "member"),
        "event": ObjType(_("event"), "event", "member"),
        "objref": ObjType(_("objref"), "objref", "member"),
        "pipe": ObjType(_("pipe"), "pipe", "member"),
        "callback": ObjType(_("callback"), "callback", "member"),
        "wire": ObjType(_("wire"), "wire", "member"),
        "memory": ObjType(_("memory"), "memory", "member"),
    }

    directives = {
        "service": RobdefService,
        "currentservice": RobdefCurrentService,
        "constant": RobdefConstant,
        "enum": RobdefEntry,
        "enumvalue": RobdefEnumValue,
        "exception": RobdefNamed,
        "struct": RobdefEntry,
        "pod": RobdefEntry,
        "namedarray": RobdefEntry,
        "object": RobdefObjectEntry,
        "field": RobdefValueMember,
        "property": RobdefValueMember,
        "function": RobdefCallable,
        "event": RobdefCallable,
        "objref": RobdefValueMember,
        "pipe": RobdefValueMember,
        "callback": RobdefCallable,
        "wire": RobdefValueMember,
        "memory": RobdefValueMember,
    }

    roles = {name: RobdefXRefRole() for name in list(object_types) + ["type", "member", "exc"]}

    initial_data: dict[str, Any] = {"objects": {}}

    indices = [RobdefServiceIndex]

    @property
    def objects(self) -> dict[str, ObjectEntry]:
        return self.data.setdefault("objects", {})

    def note_object(self, name: str, objtype: str, node_id: str, location: Any = None) -> None:
        if name in self.objects:
            other = self.objects[name]
            logger.warning(
                "duplicate robdef object description of %s, other instance in %s",
                name, other.docname, location=location, type="robdef", subtype="duplicate",
            )
        self.objects[name] = ObjectEntry(self.env.current_document.docname, node_id, objtype)

    def clear_doc(self, docname: str) -> None:
        for name, entry in list(self.objects.items()):
            if entry.docname == docname:
                del self.objects[name]

    def merge_domaindata(self, docnames, otherdata: dict[str, Any]) -> None:
        for name, entry in otherdata["objects"].items():
            if entry.docname in docnames:
                self.objects[name] = entry

    def process_field_xref(self, pnode: pending_xref) -> None:
        for k, v in _context(self.env).items():
            pnode[k] = v

    def _candidates(self, target: str, node: Element) -> Iterator[str]:
        service = node.get("robdef:service")
        entry = node.get("robdef:entry")
        if service and entry:
            yield f"{service}.{entry}.{target}"
        if service:
            yield f"{service}.{target}"
        yield target

    def find_obj(self, target: str, node: Element, objtypes: Iterable[str]) -> Optional[tuple[str, ObjectEntry]]:
        objtypes = set(objtypes)
        for name in self._candidates(target, node):
            entry = self.objects.get(name)
            if entry is not None and entry.objtype in objtypes:
                return name, entry
        return None

    def resolve_xref(self, env, fromdocname: str, builder, typ: str, target: str, node: pending_xref,
                     contnode: Element) -> Optional[Element]:
        found = self.find_obj(target, node, self.objtypes_for_role(typ) or [])
        if found is None:
            return None
        name, entry = found
        return make_refnode(builder, fromdocname, entry.docname, entry.node_id, contnode, name)

    def resolve_any_xref(self, env, fromdocname: str, builder, target: str, node: pending_xref,
                         contnode: Element) -> list[tuple[str, Element]]:
        found = self.find_obj(target, node, self.object_types)
        if found is None:
            return []
        name, entry = found
        role = "robdef:" + (self.role_for_objtype(entry.objtype) or entry.objtype)
        return [(role, make_refnode(builder, fromdocname, entry.docname, entry.node_id, contnode, name))]

    def get_objects(self) -> Iterator[tuple[str, str, str, str, str, int]]:
        for name, entry in self.objects.items():
            yield name, name, entry.objtype, entry.docname, entry.node_id, 0 if entry.objtype == "service" else 1

    def get_full_qualified_name(self, node: Element) -> Optional[str]:
        target = node.get("reftarget")
        if target is None:
            return None
        return next(self._candidates(target, node))


def missing_reference(app, env, node: pending_xref, contnode: Element) -> Optional[Element]:
    """Leave built-in types and Robot Raconteur exceptions as plain text without a warning."""
    if node.get("refdomain") != "robdef":
        return None
    target = node.get("reftarget", "")
    if node.get("reftype") in ("exc", "exception"):
        if target.rsplit(".", 1)[-1] in BUILTIN_EXCEPTIONS and (
            "." not in target or target.startswith("RobotRaconteur.")
        ):
            return contnode
    if node.get("reftype") == "type" and target in PRIMITIVE_TYPES:
        return contnode
    return None
