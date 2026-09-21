"""Shared help through real Redis, authenticated articles, modals and REST tools."""

import json
import re
from uuid import uuid4

from bs4 import BeautifulSoup
import pytest
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Restriction
from lagniappe.core.tools.cache import query
from lagniappe.core.tools.cache.core import cache
from lagniappe.core.tools.cache.help import ensure_help
from lagniappe.core.tools.cache.keys import HELP_PREFIX, Keys, Search
from lagniappe.reference import get_topic
from testing.definitions import Users
from testing.elements import HeaderSearch
from testing.resources import SitePage

pytestmark = pytest.mark.e2e


def _body(html, topic_id):
    node = BeautifulSoup(html, 'html.parser').select_one(f'[data-role="help-body"][data-topic="{topic_id}"]')
    assert node is not None
    return ' '.join(node.stripped_strings).translate(str.maketrans({'’': "'", '“': '"', '”': '"'}))


def _get(user, path):
    # Use the browser's authenticated session, including secure localhost cookies.
    return user.page.evaluate('''async path => {
        const response = await fetch(path);
        return {status: response.status, text: await response.text()};
    }''', path)


# @template help/macros.html::body
# @template reference/macros.html::modal
# @style help.content
# @pair help:navigation
def test_help_article_navigation_and_canonical_ids(get_user, browser_failures):
    user = get_user(Users.OWNER)
    user.go(SitePage(url='/help/create_form'))
    expect(user.locate('[lp-view][data-kind="help"]')).to_have_attribute('initialized', '')
    expect(user.page.get_by_role('heading', name='Creating Forms', exact=True)).to_be_visible()
    expect(user.locate('.help-summary')).to_be_visible()
    expect(user.locate('.help-section')).not_to_have_count(0)
    article = _body(user.page.content(), 'create_form')
    modal = _get(user, '/reference/section/create_form')
    assert modal['status'] == 200
    assert _body(modal['text'], 'create_form') == article
    assert 'id="modal"' in modal['text']
    user.page.get_by_role('link', name='Close', exact=True).click()
    expect(user.page).to_have_url(SETTINGS.test_config['BASE_URL'].rstrip('/') + '/')
    for path in ('/help/form_creation', '/reference/section/form_creation', '/help/missing', '/reference/section/env_variables'):
        with browser_failures.expect_http_error(user, status=404, path=path):
            assert _get(user, path)['status'] == 404


# @pair help:context-permissions
def test_help_requires_login_but_general_admin_guidance_is_readable(get_user, browser_failures):
    base = SETTINGS.test_config['BASE_URL'].rstrip('/')
    anonymous = get_user(Users.ANONYMOUS)
    anonymous.navigate(base + '/help/site_configuration')
    expect(anonymous.page).to_have_url(re.compile(r'/users/login\?next=.*help'))
    user = get_user(Users.user_no_access)
    user.go(SitePage(url='/help/site_configuration'))
    expect(user.page.get_by_role('heading', name='Configuration and Recovery Settings')).to_be_visible()
    expect(user.locate('[data-role="environment-variables"]')).to_have_count(0)
    expect(user.page.get_by_role('link', name='Download Settings File')).to_have_count(0)
    with browser_failures.expect_http_error(user, status=403, path='/reference/download-settings'):
        assert _get(user, '/reference/download-settings')['status'] == 403


# @source lagniappe/core/tools/cache/query.py::search
# @source lagniappe/web/routes/home/search.py::search_bar
# @source lagniappe/web/routes/home/search.py::_search_page_results
# @template search/search.html::facet_button
# @style dropdown.icon
# @matrix search : results navbar-results
def test_help_search_facet_snippet_and_mobile_navigation(get_user):
    user = get_user(Users.user_no_access)
    user.go(SitePage(url='/l/search-page'), query_params={'q': 'reopening', 'kind': 'help'})
    expect(user.locate('[data-role="attribute"][data-kind="help"]')).to_have_attribute('data-selected', 'true')
    results = user.locate('[data-role="results"]')
    link = results.locator('a[data-role="title"][href="/help/task_history"]')
    expect(link).to_be_visible()
    expect(results.locator('[data-icon="help"]')).not_to_have_count(0)
    expect(results.locator('b').filter(has_text=re.compile('reopen', re.I))).not_to_have_count(0)
    base = SETTINGS.test_config['BASE_URL'].rstrip('/')
    navbar = HeaderSearch(user)
    navbar.search('reopening')
    suggestion = navbar.panel.locator('[data-url="/help/task_history"]')
    expect(suggestion).to_be_visible()
    glyph = suggestion.locator('[data-icon="help"] .icon-glyph')
    expect(glyph).to_have_css('font-size', '16px')
    row = suggestion.locator('p').first
    icon_box = suggestion.locator('[data-icon="help"]').bounding_box()
    row_box = row.bounding_box()
    line_height = row.evaluate('element => parseFloat(getComputedStyle(element).lineHeight)')
    assert abs(icon_box['y'] + icon_box['height'] / 2 - row_box['y'] - line_height / 2) <= 1
    title = link.locator('xpath=..')
    expect(title.locator('xpath=..')).to_have_css('align-items', 'center')
    user.locate('[lp-search] input[name="q"]').press('Escape')
    user.mobile = True
    link.click()
    expect(user.locate('[lp-view][data-kind="help"]')).to_have_attribute('initialized', '')
    expect(user.locate('[data-role="help-body"]')).to_contain_text('fresh submission')
    assert user.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    user.page.get_by_role('link', name='Close', exact=True).click()
    expect(user.page).to_have_url(base + '/')


# @source lagniappe/core/tools/cache/help.py::ensure_help
# @source lagniappe/core/tools/cache/query.py::search
# @source lagniappe/core/tools/cache/query.py::candidate_search
# @source lagniappe/core/tools/cache/query.py::exact_name_search
# @matrix search : permissions pagination
# @matrix help : publication version
def test_redis_help_versions_permissions_pagination_and_record_exclusion():
    version = ensure_help()
    topic = get_topic('task_history')
    token = uuid4().hex
    entity_ids = {kind: f'{token}{kind}' for kind in ('category', 'task', 'file')}
    keys = [Search[kind].value.format(entity_id) for kind, entity_id in entity_ids.items()]
    old = f'{HELP_PREFIX}old{token}:task_history'
    hashes = [f'{token}{kind}' for kind in entity_ids]
    try:
        with cache.pipeline() as pipe:
            for kind, entity_id in entity_ids.items():
                pipe.hset(Search[kind].value.format(entity_id), mapping={
                    'name': topic.title, 'kind': kind, 'requires': token,
                    'desc': topic.summary, 'doc': topic.text,
                    'details_key': token + kind,
                    'search_score': {'category': 1, 'task': .65, 'file': .55}[kind],
                })
                pipe.hset(Keys.ENTITY_HASHES.value, token + kind, json.dumps({
                    'id': entity_id, 'kind': kind, 'name': topic.title, 'hash': token + kind,
                }))
            pipe.hset(old, mapping={
                'name': topic.title, 'kind': 'help', 'topic_id': 'task_history',
                'help_version': 'old' + token, 'search_score': 1,
            })
            pipe.execute()
        found, total = query.search(topic.title, [token], Restriction.BELONGS_TO_NONE, include_help=True, limit=100)
        sequence = [(item['kind'], item['id']) for item in found]
        assert sequence.count(('help', 'task_history')) == 1
        assert sequence.index(('category', entity_ids['category'])) < sequence.index(('task', entity_ids['task']))
        assert sequence.index(('task', entity_ids['task'])) < sequence.index(('help', 'task_history')) < sequence.index(('file', entity_ids['file']))
        limited, limited_total = query.search(topic.title, [], Restriction.BELONGS_TO_NONE, include_help=True, page=1, limit=1)
        assert limited_total >= 1 and limited[0]['kind'] == 'help'
        assert total > limited_total
        for function in (query.entity_search, query.exact_name_search, query.candidate_search):
            matches = function(topic.title, Restriction.UNRESTRICTED, Restriction.BELONGS_TO_ALL)
            assert all(item['kind'] != 'help' for item in matches)
        help_only, _ = query.search(topic.title, [], Restriction.BELONGS_TO_NONE, kinds=['help'], include_help=True)
        assert all(item['kind'] == 'help' for item in help_only)
        assert cache.redis.get(Keys.HELP_READY.value.format(version))
    finally:
        cache.redis.delete(*keys, old)
        cache.redis.hdel(Keys.ENTITY_HASHES.value, *hashes)


def test_rest_help_lookup_is_plan_free_and_uses_canonical_sources(monkeypatch, get_user):
    from lagniappe.core.tools.auth import agent_api as agent_auth
    from lagniappe.core.tools.ai import external_api
    from lagniappe.web import app
    user = get_user(Users.OWNER)
    monkeypatch.setattr(agent_auth, 'authenticate_credential', lambda _token: (user.entity, {'active': True}))
    monkeypatch.setattr(external_api, 'create_plan', lambda *_a, **_kw: pytest.fail('help must not create a plan'))
    client = app.test_client()
    response = client.post('/api/v1/tools/get_help', headers={'Authorization': 'Bearer test-help'}, json={'arguments': {'topic_id': 'ai_email'}})
    assert response.status_code == 200
    result = response.get_json()['result']['topics'][0]
    assert result['id'] == 'ai_email' and result['markdown'] == get_topic('ai_email').markdown
    assert result['url'] == '/help/ai_email'
