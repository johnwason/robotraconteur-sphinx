"""Cross-check the pure-Python parser against the reference RobotRaconteur parser."""

import pytest

from robotraconteur_sphinx.parser import RobdefParseError, parse_robdef, parse_robdef_file

from conftest import STANDARD_ROBDEF_DIR, TEST_ROBDEF_DIR, all_robdef_files, requires_standard, local_robdef_files

RR = pytest.importorskip("RobotRaconteur")
from RobotRaconteur.RobotRaconteurPython import MemberDefinitionUtil  # noqa: E402

_CASTS = [
    MemberDefinitionUtil.ToProperty,
    MemberDefinitionUtil.ToFunction,
    MemberDefinitionUtil.ToEvent,
    MemberDefinitionUtil.ToObjRef,
    MemberDefinitionUtil.ToPipe,
    MemberDefinitionUtil.ToCallback,
    MemberDefinitionUtil.ToWire,
    MemberDefinitionUtil.ToMemory,
]


def _rr_member_str(m):
    for cast in _CASTS:
        c = cast(m)
        if c is not None:
            return c.ToString()
    raise AssertionError("unknown member type")


def _rr_parse(path):
    d = RR.ServiceDefinition()
    d.FromString(path.read_text())
    return d


@pytest.mark.parametrize("path", all_robdef_files(), ids=lambda p: p.name)
def test_matches_reference_parser(path):
    ref = _rr_parse(path)
    svc = parse_robdef_file(path)

    assert svc.name == ref.Name
    assert svc.docstring == ref.DocString
    assert svc.imports == list(ref.Imports)
    assert sorted(svc.using.values()) == sorted(u.QualifiedName for u in ref.Using)

    assert [(c.name, c.docstring) for c in svc.constants] == [(c.Name, c.DocString) for c in ref.Constants]
    assert [c.to_robdef() for c in svc.constants] == [c.ToString() for c in ref.Constants]
    assert [(e.name, e.docstring) for e in svc.exceptions] == [(e.Name, e.DocString) for e in ref.Exceptions]

    assert [e.name for e in svc.enums] == [e.Name for e in ref.Enums]
    for e, re_ in zip(svc.enums, ref.Enums):
        assert e.docstring == re_.DocString
        assert [(v.name, v.value, v.docstring) for v in e.values] == [
            (v.Name, v.Value, v.DocString) for v in re_.Values
        ]

    for mine, theirs in (
        (svc.structs, ref.Structures),
        (svc.pods, ref.Pods),
        (svc.namedarrays, ref.NamedArrays),
        (svc.objects, ref.Objects),
    ):
        assert [e.name for e in mine] == [e.Name for e in theirs]
        for e, re_ in zip(mine, theirs):
            assert e.docstring == re_.DocString, e.name
            assert [svc.using.get(i, i) for i in e.implements] == list(re_.Implements)
            assert [(c.name, c.docstring) for c in e.constants] == [(c.Name, c.DocString) for c in re_.Constants]
            assert [m.name for m in e.members] == [m.Name for m in re_.Members]
            for m, rm in zip(e.members, re_.Members):
                assert m.docstring == rm.DocString, f"{e.name}.{m.name}"
                if e.kind == "object":
                    assert m.to_robdef() == _rr_member_str(rm)
                else:
                    ref_prop = MemberDefinitionUtil.ToProperty(rm)
                    assert m.to_robdef() == ref_prop.ToString(True)


def test_testservice4_docstrings():
    svc = parse_robdef_file(TEST_ROBDEF_DIR / "com.robotraconteur.testing.TestService4.robdef")
    assert svc.docstring == "\n service docstring line 1\n service docstring line 2\n\n service docstring line 3"
    (enum,) = svc.enums
    assert [v.docstring for v in enum.values] == [
        " enum_val1 docstring line1\n enum_val1 docstring line2",
        " enum_val2 docstring",
        " enum_val3 docstring",
        "",
    ]
    (struct,) = svc.structs
    assert struct.docstring == " struct docstring line 1\n\n struct docstring line 3"


def test_comment_clears_docstring_at_service_scope():
    svc = parse_robdef("service a.b\n## doc\n# comment\nexception e1\n")
    assert svc.exceptions[0].docstring == ""


def test_comment_in_block_acts_as_blank():
    svc = parse_robdef("service a.b\nstruct s\n## doc\n# comment\nfield double x\nend\n")
    assert svc.structs[0].members[0].docstring == " doc"


@pytest.mark.parametrize(
    "text",
    [
        "stdver 0.10\nservice a.b\n",
        "service a.b\nstruct s\nfield double x\n",
        "service a.b\nobject o\nfunction void f(int32)\nend\n",
        "service a.b\nexception eé\n",
    ],
)
def test_parse_errors(text):
    with pytest.raises(RobdefParseError):
        parse_robdef(text)


@requires_standard
def test_test_robdefs_pass_reference_verification():
    """The test robdefs must be valid service definitions, not only parseable.

    group2 is excluded: com.robotraconteur.a1.robotics.planning imports
    com.robotraconteur.a1.robotics.scene, but that file declares
    com.robotraconteur.robotics.scene upstream.
    """
    files = sorted((STANDARD_ROBDEF_DIR / "group1").glob("*.robdef")) + local_robdef_files()
    RR.RobotRaconteurNode.s.RegisterServiceTypes([f.read_text() for f in files])
