"""Python source/template contracts retained from the Core startup suite."""

from pathlib import Path


def test_page_layout_is_visible_in_server_template():
    template = Path("lagniappe/web/templates/pages/page.html").read_text()
    layout = template.split('<div id="layout"', 1)[1].split(">", 1)[0]
    info_template = Path("lagniappe/web/templates/pages/info.html").read_text()
    info_prefix, info_suffix = info_template.split('data-widget="PageInfo"', 1)
    info_form = info_prefix.rsplit("<form", 1)[1] + info_suffix.split(">", 1)[0]

    assert 'data-visible="false"' not in layout
    assert 'data-visible="false"' not in info_form


def test_initial_replay_is_scheduled_after_view_readiness():
    services = Path("src/script/views/base/services.mjs").read_text()
    core = Path("src/script/views/base/core.mjs").read_text()
    load_body = core.split("\tasync load(component, route) {", 1)[1].split(
        "\n\t/**", 1
    )[0]

    assert "const start = view._publishedReady.then(() => view)" in services
    assert "afterFirstPaint" not in services
    assert "view.initialReplayReady = view.offlineQueueReady.then" in services
    assert "inspectOfflineWork(view)" in services
    assert "view.prefetch()" in services
    assert "offlineQueueReady.then(() => view.prefetch())" not in services
    assert "offlineQueue" not in load_body
    assert "ensureOfflineQueue" not in load_body
