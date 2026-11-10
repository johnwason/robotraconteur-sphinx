from robotraconteur_sphinx.docstring import check_docstring, clean_docstring
from robotraconteur_sphinx.generator import generate_files, generate_index, generate_rst, main
from robotraconteur_sphinx.parser import parse_robdef, parse_robdef_file

from conftest import TEST_ROBDEF_DIR

SERVICE = """\
service example.svc

stdver 0.10

import other.svc

using other.svc.Pose
using other.svc.Vector3 as Vec3

##   Summary line.
##
##   Body with nested block:
##
##       indented literal
object Obj
    implements other.svc.Base

    ## Do a thing.
    ##
    ## :param a: First.
    ## :return: Result.
    ## :raises other.svc.Err: On error.
    function Pose{list} f(Vec3 a, double[3,3] b, Local c) [urgent, mod(1, 2)]

    ## :param x: Not a summary.
    event e(int32 y)

    ## Bad fields.
    ##
    ## :type a: double
    ## :rtype: double
    ## :return: nothing
    ## :note: unsupported
    function void g(double a)
end

struct Local
    field double x
end
"""


def test_clean_docstring_strips_common_indent_only():
    assert clean_docstring("   a\n\n     b\n   c\n") == "a\n\n  b\nc"
    assert clean_docstring("\n x\n") == "x"
    assert clean_docstring("") == ""


def test_generate_rst_signatures_and_docstrings():
    svc = parse_robdef(SERVICE, "example.svc.robdef")
    rst, _ = generate_rst(svc)
    assert ".. robdef:service:: example.svc\n   :stdver: 0.10\n   :imports: other.svc\n" in rst
    assert ".. robdef:object:: Obj\n   :implements: other.svc.Base\n\n   Summary line.\n" in rst
    # common indentation removed, relative indentation kept, reindented under directive
    assert "\n   Body with nested block:\n\n       indented literal\n" in rst
    # using aliases resolved; local types fully qualified; modifiers kept
    assert (
        "   .. robdef:function:: other.svc.Pose{list} f(other.svc.Vector3 a, double[3,3] b, "
        "example.svc.Local c) [urgent, mod(1,2)]\n\n      Do a thing.\n" in rst
    )
    assert "      :param a: First.\n      :return: Result.\n" in rst
    assert "Structures\n----------\n\n.. robdef:struct:: Local\n\n   .. robdef:field:: double x\n" in rst


def test_docstring_convention_warnings():
    svc = parse_robdef(SERVICE, "example.svc.robdef")
    _, warnings = generate_rst(svc)
    msgs = {(w.target, w.message) for w in warnings}
    assert ("example.svc.Obj.e", "docstring must start with a one-line summary, not a field list") in msgs
    assert ("example.svc.Obj.e", ":param x: does not match a parameter in the signature") in msgs
    g = sorted(m for t, m in msgs if t == "example.svc.Obj.g")
    assert g == [
        ":note: is not a supported field; use :param:, :return: or :raises:",
        ":return: used on a declaration that does not return a value",
        ":rtype: is not used; types come from the robdef signature",
        ":type: is not used; types come from the robdef signature",
    ]
    assert not [w for w in warnings if w.target == "example.svc.Obj.f"]
    assert all(w.filename == "example.svc.robdef" and w.lineno for w in warnings)


def test_check_docstring_without_member():
    assert check_docstring(" Summary.\n\n :param x: y") == [
        ":param x: used on a declaration without parameters"
    ]


def test_test_robdefs_follow_convention():
    for path in TEST_ROBDEF_DIR.glob("*.robdef"):
        _, warnings = generate_rst(parse_robdef_file(path))
        assert warnings == [], [str(w) for w in warnings]


def test_generate_files_and_cli(tmp_path, capsys):
    written, warnings = generate_files([TEST_ROBDEF_DIR], tmp_path, index="index")
    names = sorted(p.name for p in written)
    assert "index.rst" in names
    assert "com.robotraconteur.testing.TestService4.rst" in names
    assert warnings == []
    mtime = (tmp_path / "index.rst").stat().st_mtime_ns
    generate_files([TEST_ROBDEF_DIR], tmp_path, index="index")
    assert (tmp_path / "index.rst").stat().st_mtime_ns == mtime  # unchanged files are not rewritten

    assert main(["-o", str(tmp_path / "cli"), "--index", str(TEST_ROBDEF_DIR)]) == 0
    assert (tmp_path / "cli" / "index.rst").is_file()

    bad = tmp_path / "bad.robdef"
    bad.write_text("service a.b\n\n## Summary.\n## :rtype: double\nexception e\n")
    assert main(["-o", str(tmp_path / "cli2"), str(bad)]) == 0
    assert main(["-o", str(tmp_path / "cli2"), "--strict", str(bad)]) == 1
    bad.write_text("service a.b\nbogus line\n")
    assert main(["-o", str(tmp_path / "cli3"), str(bad)]) == 2
    assert "bad.robdef:2:" in capsys.readouterr().err


def test_generate_index_sorted():
    assert generate_index(["b.c", "a.b"]).endswith("   a.b\n   b.c\n")
