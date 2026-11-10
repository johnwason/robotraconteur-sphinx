import pytest
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.token import Comment, Error, Keyword, Name, Number, Whitespace
from sphinx.cmd.build import build_main

from robotraconteur_sphinx.lexer import RobdefLexer

from conftest import TEST_ROBDEF_DIR, all_robdef_files


@pytest.mark.parametrize("path", all_robdef_files(), ids=lambda p: p.name)
def test_lexes_without_errors(path):
    text = path.read_text()
    tokens = list(RobdefLexer().get_tokens(text))
    assert [v for t, v in tokens if t in Error] == []
    assert "".join(v for _, v in tokens) == text


def _significant(src):
    return [(t, v) for t, v in RobdefLexer().get_tokens(src) if t not in Whitespace and v.strip()]


def test_token_classes():
    toks = _significant(
        "## doc\n# note\nservice a.b\nusing c.d.Pose as P\nenum E\n    x = 0x1,\n    y\nend\n"
        "object O\n    property double[3]{list} p [readonly]\n"
        "    function P{generator} f(int32[16-] n) [urgent]\n    event e(string s)\nend\n"
    )
    assert (Comment.Special, "## doc") in toks
    assert (Comment.Single, "# note") in toks
    assert (Name.Namespace, "a.b") in toks
    assert (Name.Class, "c.d.Pose") in toks
    assert (Name.Constant, "x") in toks and (Name.Constant, "y") in toks
    assert (Number.Hex, "0x1") in toks
    assert (Keyword.Type, "double") in toks and (Keyword.Type, "list") in toks
    assert (Name.Variable, "p") in toks and (Name.Decorator, "readonly") in toks
    assert (Name.Function, "f") in toks and (Name.Variable, "n") in toks
    assert (Keyword.Type, "generator") in toks and (Name.Decorator, "urgent") in toks
    assert (Name.Function, "e") in toks and (Keyword.Type, "string") in toks


def test_pygments_entry_point():
    assert isinstance(get_lexer_by_name("robdef"), RobdefLexer)
    assert isinstance(get_lexer_for_filename("x.robdef"), RobdefLexer)


def test_sphinx_highlighting(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    robdef = TEST_ROBDEF_DIR / "com.robotraconteur.testing.docstringexample.robdef"
    (src / "axis.robdef").write_text(robdef.read_text())
    (src / "conf.py").write_text("extensions = ['robotraconteur_sphinx']\n")
    (src / "index.rst").write_text(
        "Test\n====\n\n.. code-block:: robdef\n\n   object O\n       property double x [readonly]\n   end\n\n"
        ".. literalinclude:: axis.robdef\n   :language: robdef\n"
    )
    out = tmp_path / "out"
    assert build_main(["-W", "-q", "-b", "html", str(src), str(out)]) == 0
    html = (out / "index.html").read_text()
    assert '<span class="kd">object</span>' in html
    assert '<span class="nd">readonly</span>' in html
    assert '<span class="nf">move_absolute</span>' in html
    assert '<span class="cs">## Move to an absolute position.</span>' in html
