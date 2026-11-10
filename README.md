# robotraconteur-sphinx

A Sphinx domain (`robdef`) and RST generator for Robot Raconteur service
definition (`.robdef`) files.

* `robotraconteur_sphinx.parser` – pure-Python robdef parser that keeps `##`
  docstrings. It matches the reference C++ parser's docstring rules and is
  cross-checked against `RobotRaconteur.ServiceDefinition` in the tests. No
  native Robot Raconteur install is needed to build docs.
* `robotraconteur_sphinx.generator` / `robdef-sphinx` – writes one `.rst` per
  service definition using `robdef` directives.
* `robotraconteur_sphinx.domain` – the `robdef` Sphinx domain.

## Docstring convention

Documentation comments are `##` blocks directly before a declaration
(robotraconteur_standards `draft/service_defintion.md`):

* First line: a one-line summary.
* Body: reStructuredText. Only these field-list fields are used:
  `:param name:`, `:return:`, `:raises ExcType:`.
* No `:type:` or `:rtype:`: types come from the robdef signature, and the
  domain fills them in for you.
* Document units, frames, array ordering, limits, blocking behavior, and
  whether the member moves hardware.
* ASCII only. The parser regex is `^[ \t]*##([ -~\t]*)$`.

```
object LinearAxis
    ## Move to an absolute position.
    ##
    ## Blocks until the move completes or faults. Moves hardware.
    ##
    ## :param position: Target position in meters, within ``info.limits``.
    ## :param speed: Speed in meters per second, ``0 < speed <= max_speed``.
    ## :return: Final measured position in meters.
    ## :raises AxisLimitException: ``position`` is outside the axis limits.
    function double move_absolute(double position, double speed)
end
```

The generator checks this convention and reports violations: a field list
before the summary, `:type:`/`:rtype:`, unsupported fields, `:param:` names
that are not in the signature, and `:return:` on members that don't return a
value. In a Sphinx build these are warnings, so `sphinx-build -W` fails on them.

## Usage

### As a Sphinx extension (generate at build time)

```python
# conf.py
extensions = ["robotraconteur_sphinx"]
robdef_files = ["../robdef/", "extra/*.robdef"]  # relative to conf.py; dirs are searched recursively
robdef_output_dir = "robdef"                     # relative to the source dir (default "robdef")
robdef_index = "index"                           # toctree page for all services, or None
robdef_index_title = "Service Definitions"
robdef_check_docstrings = True
```

Then add `robdef/index` to a toctree. Generated files are only rewritten when
their content changes.

### Command line

```
robdef-sphinx -o docs/robdef --index path/to/robdefs/ other.robdef
robdef-sphinx -o docs/robdef --strict ...   # exit 1 on docstring convention warnings
```

## Generated RST

```rst
.. robdef:service:: com.example.axis
   :stdver: 0.10
   :imports: com.robotraconteur.geometry

   Service docstring.

.. robdef:struct:: AxisInfo

   .. robdef:field:: com.robotraconteur.geometry.Pose mount

.. robdef:object:: LinearAxis
   :implements: com.robotraconteur.device.Device

   .. robdef:function:: double move_absolute(double position, double speed)

      Move to an absolute position.

      :param position: Target position in meters.
```

Docstrings have their common leading whitespace removed and are reindented
under each directive. Non-primitive types in signatures are written fully
qualified, with `using` aliases resolved. The domain renders them as
cross-references and shows names from the current service unqualified.

## The `robdef` domain

Directives: `service`, `currentservice`, `constant`, `enum`, `enumvalue`,
`exception`, `struct`, `pod`, `namedarray`, `field`, `object`, `property`,
`function`, `event`, `objref`, `pipe`, `callback`, `wire`, `memory`. Arguments
use robdef declaration syntax without the leading keyword.

Roles: one per object type (`:robdef:struct:`, `:robdef:function:`, ...), plus
`:robdef:type:` (struct, pod, namedarray, enum or object), `:robdef:member:`
(any field or member) and `:robdef:exc:`. Targets resolve relative to the
current entry, then the current service, then as fully qualified names. A
leading `~` shows only the last name component. The `struct`, `pod` and
`namedarray` roles match any of the three, so
`` :robdef:struct:`com.robotraconteur.geometry.Pose` `` works even though
`Pose` is a namedarray.

Field lists render as **Parameters** / **Returns** / **Return type** /
**Raises**, following the py domain's `TypedField`/`GroupedField` pattern.
Parameter and return types come from the signature. `:raises:` may name
Robot Raconteur built-in exceptions such as `OperationAbortedException`
without a link target, even in nitpicky mode.

Every object gets a general index entry. A service index is available at
`` :ref:`robdef-serviceindex` ``.

## Development

```
python -m venv .venv
.venv/bin/pip install -e '.[test]'
git clone https://github.com/robotraconteur/robotraconteur_standard_robdef .deps/robotraconteur_standard_robdef
.venv/bin/pytest
.venv/bin/sphinx-build -W -n -b html docs docs/_build/html
```

Set `ROBDEF_STANDARD_DIR` to use a different robotraconteur_standard_robdef
checkout. The docs project builds every standard robdef plus `tests/robdef/`,
which includes `com.robotraconteur.testing.TestService4.robdef` from the Robot
Raconteur repository.
