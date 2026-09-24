"""Repository contract for server-rendered durable entity anchors."""

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, StrictUndefined, nodes


REPO_ROOT = Path(__file__).resolve().parents[2]
TAG_WITH_ENTITY = re.compile(r"<(?:(?!>).)*\blp-entity\b(?:(?!>).)*>", re.DOTALL)


def test_server_rendered_lp_entities_declare_fingerprints():
    missing = []
    templates = REPO_ROOT / "lagniappe" / "web" / "templates"
    for path in templates.rglob("*.html"):
        relative = path.relative_to(REPO_ROOT)
        for match in TAG_WITH_ENTITY.finditer(path.read_text()):
            if "data-fingerprint" not in match.group():
                line = path.read_text()[: match.start()].count("\n") + 1
                missing.append(f"{relative}:{line}")

    assert missing == [], "lp-entity tags missing data-fingerprint: " + ", ".join(
        missing
    )


def _edited_marker_routes(source):
    """Read declared url_for destinations, ignoring Jinja layout and comments."""
    routes = []
    for call in Environment().parse(source).find_all(nodes.Call):
        target = call.node
        if not (
            isinstance(target, nodes.Getattr)
            and target.attr == "edited_marker"
            and isinstance(target.node, nodes.Name)
            and target.node.name == "controls"
        ):
            continue
        route_keywords = [kw.value for kw in call.kwargs if kw.key == "route"]
        assert not (call.args and route_keywords)
        assert len(call.args) <= 2 and len(route_keywords) <= 1
        assert call.args or route_keywords, "edited_marker requires one focused route"
        route = call.args[0] if call.args else route_keywords[0]
        assert isinstance(route, nodes.Call) and isinstance(route.node, nodes.Name)
        assert route.node.name == "url_for", (
            "edited_marker must use a route destination"
        )
        assert route.args and isinstance(route.args[0], nodes.Const)
        # AST nodes compare by content, not quote style, whitespace, or line number.
        routes.append((route.args[0].value, {kw.key: kw.value for kw in route.kwargs}))
    return routes


@pytest.mark.parametrize(
    "source",
    [
        "{{ controls.edited_marker(url_for('tasks.get', key=t.urlsafe_key)) }}",
        "{{ controls.edited_marker(url_for('tasks.get', key=t.urlsafe_key), review_state) }}",
        '{{ controls.edited_marker(\n route=url_for("tasks.get", key=t.urlsafe_key)\n) }}',
        "{# controls.edited_marker() #}{{ controls.edited_marker(url_for('tasks.get', key=t.urlsafe_key)) }}",
    ],
)
def test_edited_marker_route_scan_accepts_equivalent_jinja(source):
    assert _edited_marker_routes(source) == [
        (
            "tasks.get",
            {"key": nodes.Getattr(nodes.Name("t", "load"), "urlsafe_key", "load")},
        )
    ]


def test_edited_marker_route_scan_rejects_missing_route():
    with pytest.raises(AssertionError, match="requires one focused route"):
        _edited_marker_routes("{{ controls.edited_marker() }}")


def test_edited_form_markers_cover_update_forms_with_focused_routes():
    templates = REPO_ROOT / "lagniappe" / "web" / "templates"
    required = {
        "users/tools.html": [
            "url_for('users.public_permissions')",
            "url_for('users.group_permissions', key=group.urlsafe_key)",
        ],
        "projects/model_tasks.html": [
            "url_for('projects.model_info', key=project_key, task_key=task_key)"
        ],
        "projects/info.html": ["url_for('projects.info', key=project.urlsafe_key)"],
        "pages/tasks.html": [
            "url_for('tasks.get', key=t.urlsafe_key)",
            "url_for('tasks.settings', key=t.urlsafe_key)",
        ],
        "pages/document.html": [
            "url_for('pages.document_settings', key=page.urlsafe_key)"
        ],
        "pages/info.html": [
            "url_for('pages.permissions', key=page.urlsafe_key)",
            "url_for('pages.user_settings', key=page.urlsafe_key)",
            "url_for('pages.info', key=page.urlsafe_key)",
        ],
        "files/info.html": ["url_for('files.info', key=file.urlsafe_key)"],
        "categories/tools.html": [
            "url_for('categories.info', key=category.urlsafe_key)"
        ],
    }
    actual = {
        path.relative_to(templates).as_posix(): _edited_marker_routes(
            path.read_text(encoding="utf-8")
        )
        for path in templates.rglob("*.html")
    }
    for path, expressions in required.items():
        for expression in expressions:
            expected = _edited_marker_routes(
                "{{ controls.edited_marker(" + expression + ") }}"
            )[0]
            assert expected in actual[path], (
                f"{path}: missing edited marker for {expression}"
            )


# @template controls.html::edited_marker
def test_edited_marker_renders_focused_route_and_reset_control():
    source = (REPO_ROOT / "lagniappe/web/templates/controls.html").read_text(
        encoding="utf-8"
    )
    environment = Environment(autoescape=True, undefined=StrictUndefined)
    environment.filters["yesno"] = lambda value: "true" if value else "false"
    tree = environment.parse(source)
    # Render the real macro; unrelated macros need application-only filters.
    tree.body = [
        node
        for node in tree.body
        if isinstance(node, nodes.Macro) and node.name == "edited_marker"
    ]
    module = environment.from_string(tree).make_module({"styles": {"message": ""}})
    route = "/l/tasks/settings?key=task-1&mode=review"
    state = {"operation": None, "reviews": [], "migration": None, "retry_operation": None}
    markup = BeautifulSoup(module.edited_marker(route, state), "html.parser")

    marker = markup.select_one("[lp-edited-marker]")
    assert marker is not None
    assert marker["data-edited-route"] == route
    assert marker["data-visible"] == "false"
    assert marker["aria-live"] == "polite"
    reset = marker.select_one('[data-role="edited-reset"]')
    assert reset is not None and reset["type"] == "button"
    assert not markup.select('[data-role="edited-reload"]')
    reviewed = BeautifulSoup(module.edited_marker(route, {**state, "reviews": [{}]}), "html.parser")
    assert reviewed.select_one("[lp-edited-marker]")["data-visible"] == "true"
    assert "Autofill is complete." in reviewed.select_one('[data-role="edited-message"]').get_text()
