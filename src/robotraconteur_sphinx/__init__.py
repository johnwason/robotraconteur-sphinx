"""Sphinx support for Robot Raconteur service definitions (``.robdef``).

Add ``"robotraconteur_sphinx"`` to ``extensions`` in ``conf.py`` to register
the ``robdef`` domain. To generate pages at build time, also set::

    robdef_files = ["path/to/robdefs/", "other.robdef"]  # relative to conf.py; globs allowed
    robdef_output_dir = "robdef"           # relative to the source dir
    robdef_index = "index"                 # toctree page name, or None
    robdef_index_title = "Service Definitions"
    robdef_check_docstrings = True         # report docstring convention issues as warnings
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

__version__ = "0.1.0"


def _generate(app) -> None:
    from sphinx.util import logging

    from .generator import generate_files
    from .parser import RobdefParseError

    logger = logging.getLogger(__name__)
    cfg = app.config
    if not cfg.robdef_files:
        return
    sources: list[Path] = []
    for pattern in cfg.robdef_files:
        full = str(Path(app.confdir, pattern))
        matches = sorted(glob.glob(full, recursive=True)) if glob.has_magic(full) else [full]
        if not matches or not all(Path(m).exists() for m in matches):
            logger.warning("robdef_files entry %r matched no files", pattern, type="robdef", subtype="config")
        sources.extend(Path(m) for m in matches if Path(m).exists())
    out = Path(app.srcdir, cfg.robdef_output_dir)
    try:
        _, warnings = generate_files(sources, out, cfg.robdef_index, cfg.robdef_index_title,
                                     check=cfg.robdef_check_docstrings)
    except RobdefParseError as e:
        logger.warning("%s", e.message, location=f"{e.filename}:{e.lineno}" if e.filename else None,
                       type="robdef", subtype="parse")
        return
    for w in warnings:
        logger.warning("%s: %s", w.target, w.message,
                       location=f"{w.filename}:{w.lineno}" if w.filename else None,
                       type="robdef", subtype="docstring")


def setup(app) -> dict[str, Any]:
    from .domain import RobdefDomain, missing_reference

    app.add_domain(RobdefDomain)
    app.add_config_value("robdef_files", [], "env", types=frozenset({list, tuple}))
    app.add_config_value("robdef_output_dir", "robdef", "env", types=frozenset({str}))
    app.add_config_value("robdef_index", "index", "env", types=frozenset({str, type(None)}))
    app.add_config_value("robdef_index_title", "Service Definitions", "env", types=frozenset({str}))
    app.add_config_value("robdef_check_docstrings", True, "env", types=frozenset({bool}))
    app.connect("builder-inited", _generate)
    app.connect("missing-reference", missing_reference)
    return {"version": __version__, "env_version": 1, "parallel_read_safe": True, "parallel_write_safe": True}
