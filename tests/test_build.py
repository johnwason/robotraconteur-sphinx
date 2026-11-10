"""End-to-end Sphinx builds with -W (warnings are errors) and -n (nitpicky)."""

import re
import shutil
from pathlib import Path

import pytest
from sphinx.cmd.build import build_main

from conftest import ROOT, STANDARD_ROBDEF_DIR, TEST_ROBDEF_DIR, requires_standard


def _build(srcdir: Path, outdir: Path, *extra: str) -> int:
    return build_main(["-W", "--keep-going", "-n", "-q", "-E", "-b", "html", *extra, str(srcdir), str(outdir)])


@requires_standard
def test_standard_and_test_robdefs_build_cleanly(tmp_path, monkeypatch):
    """Generate and build docs/ (all standard robdefs plus tests/robdef)."""
    src = tmp_path / "docs"
    shutil.copytree(ROOT / "docs", src, ignore=shutil.ignore_patterns("_build", "robdef"))
    (src / "conf.py").write_text(
        (src / "conf.py").read_text().replace('"../tests/robdef"', repr(str(TEST_ROBDEF_DIR)))
    )
    monkeypatch.setenv("ROBDEF_STANDARD_DIR", str(STANDARD_ROBDEF_DIR))
    out = tmp_path / "html"
    assert _build(src, out) == 0

    generated = sorted(p.stem for p in (src / "robdef").glob("*.rst"))
    assert "com.robotraconteur.testing.TestService4" in generated
    assert "com.robotraconteur.robotics.robot" in generated

    html = (out / "robdef" / "com.robotraconteur.testing.docstringexample.html").read_text()
    # fields rendered as Parameters / Returns / Return type / Raises with types from the signature
    for label in ("Parameters", "Returns", "Return type", "Raises"):
        assert f">{label}<" in html
    assert html.index(">Returns<") < html.index(">Return type<") < html.index(">Raises<")
    # types in signatures cross-reference other services; using aliases resolved
    assert 'href="com.robotraconteur.geometry.html#robdef-com.robotraconteur.geometry.Pose"' in html
    assert 'href="com.robotraconteur.geometry.html#robdef-com.robotraconteur.geometry.Vector3"' in html
    assert 'href="#robdef-com.robotraconteur.testing.docstringexample.AxisLimitException"' in html

    index = (out / "index.html").read_text()
    assert 'href="robdef/com.robotraconteur.geometry.html#robdef-com.robotraconteur.geometry.Pose"' in index
    genindex = (out / "genindex.html").read_text()
    assert "move_absolute() (robdef function in com.robotraconteur.testing.docstringexample.LinearAxis)" in \
        re.sub(r"<[^>]+>", "", genindex)
    assert (out / "robdef-serviceindex.html").is_file()


def _project(tmp_path: Path, robdef_text: str, index_extra: str = "") -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "x.robdef").write_text(robdef_text)
    (src / "conf.py").write_text(
        "extensions = ['robotraconteur_sphinx']\n"
        f"robdef_files = [{str(tmp_path / 'x.robdef')!r}]\n"
    )
    (src / "index.rst").write_text("Test\n====\n\n.. toctree::\n\n   robdef/index\n\n" + index_extra)
    return src


def test_docstring_convention_violation_fails_build(tmp_path):
    src = _project(tmp_path, "service a.b\n\nobject o\n    ## Summary.\n    ##\n    ## :type x: int32\n"
                             "    function void f(int32 x)\nend\n")
    assert _build(src, tmp_path / "out") != 0


def test_invalid_rst_in_docstring_fails_build(tmp_path):
    src = _project(tmp_path, "service a.b\n\n## Summary with `broken markup\nexception e\n")
    assert _build(src, tmp_path / "out") != 0


def test_unresolved_reference_fails_build(tmp_path):
    src = _project(tmp_path, "service a.b\n\nexception e\n", ":robdef:exception:`a.b.nope`\n")
    assert _build(src, tmp_path / "out") != 0


def test_handwritten_directives_and_roles(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text("extensions = ['robotraconteur_sphinx']\n")
    (src / "index.rst").write_text(
        """\
Test
====

.. robdef:service:: ex.svc

   Example.

.. robdef:struct:: S

   A struct.

   .. robdef:field:: double[3] v

      Vector, see :robdef:field:`v` and :robdef:type:`S`.

.. robdef:object:: O

   .. robdef:function:: ex.svc.S{list} f(int32 a)

      Do it.

      :param a: Count.
      :return: Items.
      :raises InvalidArgumentException: Bad count.

.. robdef:currentservice:: other.svc

:robdef:struct:`ex.svc.S`, :robdef:member:`~ex.svc.O.f`, :robdef:member:`ex.svc.S.v`,
:any:`ex.svc.O`.
"""
    )
    out = tmp_path / "out"
    assert _build(src, out) == 0
    html = (out / "index.html").read_text()
    text = re.sub(r"<[^>]+>", "", html)
    assert "a (int32) – Count." in text
    assert html.count('href="#robdef-ex.svc.S"') >= 3
    assert 'href="#robdef-ex.svc.S.v"' in html
    assert 'href="#robdef-ex.svc.O.f"' in html
    assert 'href="#robdef-ex.svc.O"' in html
