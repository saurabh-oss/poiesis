"""Turn a failed check into something a Developer can act on.

A raw pytest run is mostly noise a model spends its attention on: pip's warnings
about running as root, forty Starlette frames between the test and the line that
raised, a deprecation summary. The signal — which tests failed, the `E` lines,
the frames inside the application — fits in a tenth of the space. `distill()`
keeps that tenth.

`coach()` goes one step further for the failures that recur across runs: it names
what the error means and the fix that usually applies, in the same words every
time, so the Developer does not need to infer from a traceback that a
`ResponseValidationError` on `('response', 'agent_name')` means the response
schema asks for a field the returned object does not have.
"""
from __future__ import annotations

import re

_NOISE = (
    "WARNING: Running pip as the 'root' user",
    "pip.pypa.io/warnings/venv",
    "--root-user-action",
    "[notice]",
    "DeprecationWarning",
    "_PortalFactoryType",
    "warnings summary",
    "-- Docs: https://docs.pytest.org",
    "PytestDeprecationWarning",
)
_FRAME_PATH = re.compile(r"^\s*(/usr/local/lib/|.*site-packages[/\\]|<frozen )")
_KEEP = re.compile(r"^\s*(E\s|FAILED|ERROR|PASSED|=+ |tests/|backend/|[0-9]+ (failed|passed|error))")


def distill(output: str, limit: int = 9000) -> str:
    """The failing tests, their assertions and the application's own frames."""
    out: list[str] = []
    skip_source = False
    blank = 0
    for line in output.splitlines():
        s = line.strip()
        if skip_source:
            # The source line that follows a framework frame path.
            skip_source = False
            if not _KEEP.match(line):
                continue
        if _FRAME_PATH.match(line):
            skip_source = True
            continue
        if any(n in s for n in _NOISE):
            continue
        if not s:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line.rstrip())
    text = "\n".join(out).strip()
    return text[-limit:] if len(text) > limit else text


_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ResponseValidationError.*?'loc': \('response',(?: \d+,)? '(\w+)'\)", re.S),
     "The endpoint's response_model requires `{0}`, but the object it returns has no attribute "
     "`{0}` — FastAPI reads the fields off the object and this one is missing. Either build the "
     "response yourself (return a dict or the schema class) with `{0}` filled in, for example "
     "from the related row, or remove `{0}` from the response schema. `from_attributes=True` only "
     "copies attributes that exist."),
    (re.compile(r"NameError: name '(\w+)' is not defined"),
     "`{0}` is used but never imported or defined in that file. Add the import. A NameError at "
     "module level breaks the whole application at import time, so every test fails until it "
     "is fixed — fix this first, then look at the test failures again."),
    (re.compile(r"ImportError while loading conftest|cannot import name '(\w+)'|No module named '([\w.]+)'"),
     "An import failed while the application was loading, so no test could run. Every name you "
     "import must exist in the module you import it from (see VERIFIED IMPORTS), every router "
     "module must import cleanly, and sibling imports use two dots (`from ..db import`)."),
    (re.compile(r"assert 405 ==|status_code == 405|405 Method Not Allowed"),
     "A test sends a method to a path that does not accept it (405). Compare the test's calls "
     "with VERIFIED ROUTES: the test is not yours to change, so add the endpoint it calls, with "
     "that method, at that exact path."),
    (re.compile(r"assert 404 == 2\d\d|assert 404 ==|status_code == 404\b(?!.*expected)"),
     "A path the test calls answers 404: the route is missing or its path differs from the one "
     "in the test (a prefix, a plural, a trailing segment). Declare exactly the path the test "
     "uses, as VERIFIED ROUTES will then show it."),
    (re.compile(r"assert 422 == 2\d\d"),
     "The request body the test sends is rejected by your request schema (422). The test "
     "follows the acceptance criteria, so change the schema's field names, types or optional "
     "fields to accept what the test sends, not the other way round."),
    (re.compile(r"IntegrityError.*?NOT NULL constraint failed: (\w+)\.(\w+)|NotNullViolation.*?column \"(\w+)\"", re.S),
     "A row was inserted without a value for a NOT NULL column. Give the column a default in "
     "models.py and init.sql, or set it in the endpoint before adding the row."),
    (re.compile(r"OperationalError.*?no such table: (\w+)", re.S),
     "The test database is built from the models, so `{0}` has no table: the model is missing "
     "from models.py, has a different __tablename__, or the module defining it is never "
     "imported. Define it in backend/app/models.py."),
    (re.compile(r"AttributeError: '(\w+)' object has no attribute '(\w+)'"),
     "`{0}` has no attribute `{1}`. Look at its definition in the shared files you were shown "
     "(models.py, schemas.py) and use the name that exists there, or add the column or field."),
    (re.compile(r"TypeError: .*?got an unexpected keyword argument '(\w+)'"),
     "Something is constructed with a `{0}=` it does not accept: the field names in "
     "schemas.py, models.py and the router disagree. Make them match."),
    (re.compile(r"ValidationError.*?Input should be a valid (\w+)", re.S),
     "A value has the wrong type for its schema field ({0} expected). Convert it in the "
     "endpoint or widen the schema type; dates and datetimes must be real date objects, not strings."),
    (re.compile(r"SyntaxError: (missing \) after argument list|Unexpected token[^\n]*|Unexpected end of input|missing \} after[^\n]*|Invalid or unexpected token)"),
     "A screen has a JavaScript syntax error: {0}. Every `h(` needs exactly one closing `)`, "
     "every string and template literal must be closed, and the file must keep the shape of "
     "frontend/screens/example.js. Rewrite the whole render() tree carefully rather than "
     "patching one line."),
    (re.compile(r"render\(\) never loads anything"),
     "The screen must fetch and draw its data inside render() itself, not only inside a click "
     "handler: a visitor opening the page sees the data immediately."),
    (re.compile(r"assert .* == \[\]|assert len\(.*\) == 0\s*$|assert \[\] == \[\{", re.M),
     "An endpoint returned an empty list where the test expected rows it had just created: "
     "check the query's filters and that the endpoint reads the same table the POST wrote to."),
]


_STATUS_DRIFT = re.compile(r"^(.*?) expects status \[(\d+)\] from (\w+) (\S+), which the route declares as \[(\d+)\]")


def for_developer(issue: str) -> str:
    """Rephrase a test-side finding as the change the Developer can make.

    test_issues() speaks to the Tester ("assert the status the contract states");
    shown to the Developer, who may not touch tests, that reads as a dead end.
    The Developer's version of the same fact is "declare that status".
    """
    m = _STATUS_DRIFT.search(issue)
    if m:
        who, expected, method, path, declared = m.groups()
        return (f"{who} expects {expected} from {method} {path}, but the route declares {declared}. "
                f"Add `status_code={expected}` to that route's decorator — the tests are not yours "
                f"to change, and a {method} that creates something returns 201.")
    return issue


def coach(output: str, limit: int = 5) -> str:
    """Plain-language explanations for the failure signatures in `output`, if any."""
    hints: list[str] = []
    for pattern, template in _HINTS:
        m = pattern.search(output)
        if not m:
            continue
        groups = [g for g in m.groups() if g] or [""]
        try:
            hint = template.format(*groups)
        except (IndexError, KeyError):
            hint = template
        if hint not in hints:
            hints.append(hint)
        if len(hints) >= limit:
            break
    if not hints:
        return ""
    return ("\n\nWHAT THE FAILURES MEAN (read this before editing):\n"
            + "\n".join(f"- {h}" for h in hints) + "\n")


def failed_tests(output: str) -> list[str]:
    """`tests/test_x.py::test_name` for every FAILED or ERROR line."""
    return re.findall(r"^(?:FAILED|ERROR) (tests/[\w./-]+::\w+)", output, re.M)
