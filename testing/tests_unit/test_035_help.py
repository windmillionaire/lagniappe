"""Canonical help content, publication races, search boundaries and AI lookup."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
from types import SimpleNamespace

from bs4 import BeautifulSoup
import pytest
from redis.exceptions import ResponseError, ConnectionError

from lagniappe import CONFIG
from lagniappe import reference
from lagniappe.core.definitions import Restriction
from lagniappe.core.tools.cache import help as help_cache, query
from lagniappe.core.tools.cache.core import Cache
from lagniappe.core.tools.cache.keys import HELP_PREFIX, Keys
from lagniappe.core.tools.files.html import SafeHTML

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_topic_caches():
    functions = (reference._sources, reference.help_version, reference.topics, reference.topic_html, reference.topic_sections)
    for function in functions:
        function.cache_clear()
    yield
    for function in functions:
        function.cache_clear()


def test_topics_are_canonical_and_portable():
    corpus = reference.topics()
    assert 'form_creation' not in corpus
    assert {'navigation', 'search', 'filters', 'documents', 'offline',
            'messages_notifications', 'task_scheduling', 'task_history',
            'ai_email', 'external_ai', 'account_security', 'analytics',
            'backups_archives', 'notes', 'tables'} <= corpus.keys()
    for topic in corpus.values():
        assert topic.id not in topic.related
        assert all(related in corpus for related in topic.related)
        assert topic.category in reference.VALID_HELP_CATEGORIES
        assert topic.keywords and all(kw.strip() for kw in topic.keywords)
        assert topic.summary and '\n' not in topic.summary
        assert not re.search(r'<[^>]+>', topic.text)
        assert '{{' not in topic.markdown
        assert topic.url == f'/help/{topic.id}'
        assert json.loads(json.dumps(topic.as_dict()))['markdown'] == topic.markdown
        assert 'aliases' not in topic.as_dict()
    assert reference.get_topic('create_form') is corpus['create_form']
    catalog = reference.topic_catalog()
    assert {entry['id'] for entry in catalog} == set(corpus)
    assert all(entry['category'] in reference.VALID_HELP_CATEGORIES for entry in catalog)
    grouped_ids = {topic.id for _, _, _, items in reference.grouped_topics() for topic in items}
    assert grouped_ids == set(corpus)
    template_root = Path(reference.TOPIC_DIRECTORY).parent / 'web' / 'templates'
    help_attr = re.compile(r'(?:data-help|lp-help)="([^"]+)"')
    macro_help = re.compile(r'controls\.help\(\s*["\']([a-z0-9_]+)["\']')
    for template in template_root.rglob('*.html'):
        source = template.read_text(encoding='utf-8')
        for match in help_attr.findall(source):
            if match.startswith('{{'):
                continue
            assert match in corpus, f'Broken help trigger {match!r} in {template}'
        for match in macro_help.findall(source):
            assert match in corpus, f'Broken controls.help({match!r}) in {template}'


def test_help_version_changes_with_source_without_rendering(monkeypatch):
    monkeypatch.setattr(reference, 'render_markdown', lambda *_a: pytest.fail('versioning must not render'))
    monkeypatch.setattr(reference, '_sources', lambda: (('one', b'first'),))
    original = reference.help_version()
    reference.help_version.cache_clear()
    monkeypatch.setattr(reference, '_sources', lambda: (('one', b'changed'),))
    assert reference.help_version() != original
    reference.help_version.cache_clear()
    monkeypatch.setattr(reference, '_sources', lambda: (('renamed', b'first'),))
    assert reference.help_version() != original
    reference.help_version.cache_clear()
    monkeypatch.setattr(reference, 'PROJECTION_VERSION', 'next')
    assert reference.help_version() != original


@pytest.mark.parametrize('source', [
    b'No metadata',
    b'---\ntitle: One\naliases: [two]\n---\nSummary.',
    b'---\ntitle: One\nrelated: [absent]\n---\nSummary.',
    b'---\ntitle: One\nrelated: [one]\n---\nSummary.',
    b'---\ntitle: One\ncategory: nonexistent\n---\nSummary.',
    b'---\ntitle: One\nkeywords: [dup, dup]\n---\nSummary.',
    b'---\ntitle: One\nmanual_section: absent\n---\nSummary.',
    b'---\ntitle: One\n---\n# Heading first',
    b'---\ntitle: One\n---\n{{ CONFIG.SECRET }}',
    b'---\ntitle: One\n---\nSummary. [Bad link](/help/missing)',
    b'---\ntitle: One\n---\nSummary. [Bad manual](/manual/missing)',
])
def test_invalid_topic_sources_fail_validation(monkeypatch, source):
    monkeypatch.setattr(reference, '_sources', lambda: (('one', source),))
    with pytest.raises(ValueError):
        reference.topics()


@pytest.mark.parametrize('topic_id', ['form_creation', '../prompt', 'create_form.md', 'Create_Form', 'missing', None])
def test_topic_lookup_rejects_aliases_and_paths(topic_id):
    with pytest.raises(KeyError):
        reference.get_topic(topic_id)


def test_topic_rendering_preserves_safety_and_links(monkeypatch):
    source = b'---\ntitle: One\n---\nA summary.\n\n## Details\n\n[More](/help/one) and [Installation](/manual/installation)\n\n<script>secret()</script>'
    monkeypatch.setattr(reference, '_sources', lambda: (('one', source),))
    article = reference.topic_html('one')
    embedded = reference.topic_html('one', embedded=True)
    assert isinstance(article, SafeHTML) and isinstance(embedded, SafeHTML)
    assert '<h2>Details</h2>' in article
    assert '<h3>Details</h3>' in embedded
    for html in (article, embedded):
        assert 'href="/help/one"' in html
        assert 'href="/manual/installation"' in html
        assert 'script' not in html and 'secret()' not in html
    introduction, details = reference.topic_sections('one')
    assert isinstance(introduction, SafeHTML) and isinstance(details, SafeHTML)
    assert BeautifulSoup(introduction, 'html.parser').get_text() == 'A summary.'
    assert '<h2>Details</h2>' in details and 'secret()' not in details
    source = b'---\ntitle: One\n---\nA summary.\n\nDetails without a heading.\n\nOne more paragraph.'
    reference.topics.cache_clear()
    reference.topic_html.cache_clear()
    reference.topic_sections.cache_clear()
    introduction, details = reference.topic_sections('one')
    assert 'Details' not in introduction
    assert 'Details without a heading.' in details and 'One more paragraph.' in details


def test_context_is_separate_and_requires_authenticated_user(monkeypatch):
    monkeypatch.setattr(CONFIG, 'AI_EMAIL_PUBLIC', {'enabled': True, 'addresses': {'ai': 'ai@private.example'}})
    monkeypatch.setattr(CONFIG, 'AI_ENABLED', True)
    monkeypatch.setattr(CONFIG, 'EXTERNAL_AI_ENABLED', True)
    monkeypatch.setattr(CONFIG, 'MCP_RESOURCE', 'https://private.example/mcp')
    monkeypatch.setattr(CONFIG, 'MCP_NAME', 'private-site')
    monkeypatch.setattr(CONFIG, 'CUSTOM_DOMAIN', 'private.example')
    guest = SimpleNamespace(is_authenticated=False, is_public=True)
    member = SimpleNamespace(is_authenticated=True, is_public=False)
    public_user = SimpleNamespace(is_authenticated=True, is_public=True)
    assert reference.topic_context('ai_email', guest) == {}
    assert reference.topic_context('external_ai', public_user) == {}
    assert reference.topic_context('ai_email', member) == {'email_address': 'ai@private.example'}
    assert reference.topic_context('external_ai', member)['mcp_url'] == 'https://private.example/mcp'
    assert reference.topic_context('external_ai', member)['skill_url'].endswith('/api/v1/client-skill.md')
    assert all('private.example' not in topic.markdown + topic.text for topic in reference.topics().values())
    monkeypatch.setattr(CONFIG, 'AI_EMAIL_PUBLIC', {'enabled': False})
    monkeypatch.setattr(CONFIG, 'EXTERNAL_AI_ENABLED', False)
    assert reference.topic_context('ai_email', member) == {}
    assert reference.topic_context('external_ai', member) == {}


class MemoryRedis:
    def __init__(self, *, upgraded=True):
        self.values = {}
        self.hashes = {'workspace-page': {'name': 'Keep me'}}
        self.upgraded = upgraded
        self.events = []
        self.on_lock = None
        self.fail_write = False
        self.index_error = None
        self.exists = True
        self.metadata_maps = False

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.events.append(('ready', key))
        self.values[key] = value

    @contextmanager
    def lock(self, key, **kwargs):
        self.events.append(('lock', key))
        if self.on_lock:
            self.on_lock()
        yield
        self.events.append(('unlock', key))

    def ft(self, _name):
        return self

    def info(self):
        if self.index_error:
            raise self.index_error
        if not self.exists:
            raise ResponseError('unknown index name')
        definition = [b'prefixes', [HELP_PREFIX.encode()] if self.upgraded else [b'page:']]
        attributes = (
            [[b'attribute', b'help_version', b'type', b'TAG'], [b'attribute', b'keywords', b'type', b'TEXT']]
            if self.upgraded
            else [[b'attribute', b'help_version', b'type', b'TAG']]
        )
        if self.metadata_maps:
            definition = dict(zip(definition[::2], definition[1::2], strict=True))
            attributes = [dict(zip(row[::2], row[1::2], strict=True)) for row in attributes]
        return {'indexing': 0, 'index_definition': definition, 'attributes': attributes}

    def dropindex(self, *, delete_documents=False):
        assert delete_documents is False
        self.events.append(('drop', False))
        self.exists = False

    def create_index(self, schema, definition=None):
        assert HELP_PREFIX in definition.args
        assert any(field.name == 'help_version' for field in schema)
        assert any(field.name == 'keywords' for field in schema)
        self.events.append(('create',))
        self.exists = True
        self.upgraded = True

    @contextmanager
    def pipeline(self):
        commands = []
        def execute():
            if self.fail_write:
                raise ConnectionError('write failed')
            self.hashes.update(commands)
            self.events.append(('write', len(commands)))
        yield SimpleNamespace(hset=lambda key, mapping: commands.append((key, mapping)), execute=execute)

    def search(self, redis_query):
        match = re.search(r'@help_version:\{ (\w+) \}', redis_query._query_string)
        total = sum(row.get('help_version') == match[1] for row in self.hashes.values()) if match else 0
        return SimpleNamespace(total=total, docs=[])


@pytest.fixture
def memory_cache(monkeypatch):
    redis = MemoryRedis()
    instance = Cache()
    instance._redis = redis
    monkeypatch.setattr(help_cache, 'cache', instance)
    return redis


@pytest.mark.parametrize('metadata_maps', [False, True])
def test_index_upgrade_preserves_hashes_and_is_serialized(memory_cache, metadata_maps):
    memory_cache.metadata_maps = metadata_maps
    memory_cache.upgraded = False
    help_cache.ensure_help_index()
    assert memory_cache.hashes == {'workspace-page': {'name': 'Keep me'}}
    assert memory_cache.events[0] == ('lock', Keys.SEARCH_INDEX_LOCK.value)
    assert ('drop', False) in memory_cache.events
    before = list(memory_cache.events)
    help_cache.ensure_help_index()
    assert memory_cache.events == before


def test_index_upgrade_does_not_hide_provider_failures(memory_cache):
    memory_cache.index_error = ResponseError('permission denied')
    with pytest.raises(ResponseError, match='permission denied'):
        help_cache.ensure_help_index()
    assert not memory_cache.events


def test_population_is_versioned_atomic_and_skips_warm_start(memory_cache, monkeypatch):
    version = help_cache.ensure_help()
    assert len(memory_cache.hashes) == len(reference.topics()) + 1
    key = f'{HELP_PREFIX}{version}:create_form'
    row = memory_cache.hashes[key]
    assert row['topic_id'] == 'create_form' and row['kind'] == 'help'
    assert row['search_score'] == .60
    assert row['desc'] == reference.get_topic('create_form').summary
    assert row['keywords'] == ' '.join(reference.get_topic('create_form').keywords)
    assert not {'details_key', 'hash', 'parent_key', 'requires'} & row.keys()
    assert memory_cache.events[-2] == ('ready', Keys.HELP_READY.value.format(version))
    before = list(memory_cache.events)
    monkeypatch.setattr(help_cache, 'topics', lambda: pytest.fail('warm population parsed topics'))
    assert help_cache.ensure_help() == version
    assert memory_cache.events == before
    # Overlapping source versions retain old documents; the current query selects
    # only the new version and removed topics are not copied into it.
    monkeypatch.setattr(help_cache, 'help_version', lambda: 'nextversion')
    monkeypatch.setattr(help_cache, 'topics', lambda: {'create_form': reference.get_topic('create_form')})
    help_cache.ensure_help()
    assert key in memory_cache.hashes
    assert f'{HELP_PREFIX}nextversion:create_form' in memory_cache.hashes
    assert f'{HELP_PREFIX}nextversion:tasks' not in memory_cache.hashes
    assert 'nextversion' in help_cache.help_clause('nextversion')


def test_failed_population_is_retryable_and_cache_loss_repopulates(memory_cache):
    memory_cache.fail_write = True
    with pytest.raises(ConnectionError):
        help_cache.ensure_help()
    assert not memory_cache.values
    memory_cache.fail_write = False
    version = help_cache.ensure_help()
    assert memory_cache.values[Keys.HELP_READY.value.format(version)] == 'ready'
    memory_cache.hashes.clear()
    memory_cache.values.clear()
    assert help_cache.ensure_help() == version
    assert len(memory_cache.hashes) == len(reference.topics())


def test_population_rechecks_readiness_after_lock(memory_cache, monkeypatch):
    key = Keys.HELP_READY.value.format(reference.help_version())
    memory_cache.on_lock = lambda: memory_cache.values.update({key: 'ready'})
    monkeypatch.setattr(help_cache, 'topics', lambda: pytest.fail('another worker already populated'))
    help_cache.ensure_help()
    assert all(event[0] not in {'write', 'ready'} for event in memory_cache.events)


def test_help_search_unions_scope_before_pagination_and_keeps_its_details(monkeypatch):
    captured = []
    topic = reference.get_topic('create_form')
    doc = SimpleNamespace(id=f'{HELP_PREFIX}version:create_form', topic_id='create_form', kind='help', name=topic.title, desc='unhighlighted', doc='unhighlighted')
    monkeypatch.setattr(query, 'ensure_help', lambda: 'version')
    monkeypatch.setattr(query.cache, 'search', lambda q: captured.append(q) or SimpleNamespace(docs=[doc], total=21))
    monkeypatch.setattr(query, 'hydrate_search_results', lambda results: results)
    monkeypatch.setattr(query.cache, 'delete', lambda *_a: pytest.fail('help is not a stale entity'))
    results, total = query.search('forms', ['visible'], ['group'], page=2, include_help=True)
    assert total == 21 and results[0]['details']['url'] == '/help/create_form'
    assert results[0]['text'] == topic.summary
    sql = captured[0]._query_string
    assert '@requires:{ visible }' in sql and '@restricted_to_page:{ group }' in sql
    assert '| (@kind:{ help } @help_version:{ version })' in sql
    assert sql.endswith('=> { $weight: 0; }')
    assert captured[0]._offset == 10 and captured[0]._num == 10
    query.search('forms', [], Restriction.BELONGS_TO_NONE, kinds=['help'], include_help=True)
    assert '@requires' not in captured[-1]._query_string
    assert '@restricted_to' not in captured[-1]._query_string
    assert 'version' in captured[-1]._query_string
    query.search('forms', Restriction.UNRESTRICTED, Restriction.BELONGS_TO_ALL, kinds=['page'], include_help=True)
    assert '@help_version' not in captured[-1]._query_string


def test_entity_search_and_pickers_exclude_help_even_for_administrators(monkeypatch):
    captured = []
    monkeypatch.setattr(query.cache, 'search', lambda q: captured.append(q._query_string) or SimpleNamespace(docs=[], total=0))
    monkeypatch.setattr(query, 'hydrate_search_results', lambda results: results)
    monkeypatch.setattr(query, 'ensure_help', lambda: pytest.fail('entity discovery must not populate help'))
    args = ('forms', Restriction.UNRESTRICTED, Restriction.BELONGS_TO_ALL)
    query.search(*args)
    query.entity_search(*args)
    query.exact_name_search(*args)
    query.candidate_search(*args)
    assert all('(-@kind:{ help })' in sql for sql in captured)
    before = len(captured)
    assert query.kind_search('forms', 'help', *args[1:]) == []
    assert len(captured) == before
    from lagniappe.core.tools.ai.function_definitions.search import ALLOWED_SEARCH_KINDS
    assert 'help' not in ALLOWED_SEARCH_KINDS


def test_help_tool_is_bounded_source_backed_and_shared(monkeypatch):
    from lagniappe.core.tools.ai import functions
    from lagniappe.core.tools.ai.function_definitions import get_help
    from lagniappe.core.tools.ai.reporting.contracts.actions import READ_ONLY_CONTEXT_TOOLS
    from lagniappe.core.tools.ai.observability import KNOWN_TOOL_NAMES
    user = SimpleNamespace(is_authenticated=False)
    calls = []
    monkeypatch.setattr(get_help.cache, 'help_search', lambda value, **kw: calls.append((value, kw)) or ([{'id': 'task_history'}], 1))
    direct, parts = functions.execute_registered_tool('get_help', {'topic_id': 'task_history'}, user, external=True)
    assert not calls and not parts
    assert direct['topics'][0]['markdown'] == reference.get_topic('task_history').markdown
    found, _ = functions.execute_registered_tool('get_help', {'query': 'task history'}, user)
    assert found == direct
    assert calls == [('task history', {'limit': 3})]
    listed, _ = functions.execute_registered_tool('get_help', {'list_topics': True}, user, external=True)
    assert listed['topics'] == []
    assert {item['id'] for item in listed['catalog']} == set(reference.topics())
    catalog = functions.tool_catalog(names=['get_help'], transport='rest')[0]
    assert catalog['result_paths']['primary_collection'] == '$.topics'
    assert catalog['output_schema']['properties']['topics']['maxItems'] == 3
    assert 'catalog' in catalog['output_schema']['properties']
    assert 'get_help' in READ_ONLY_CONTEXT_TOOLS and 'get_help' in KNOWN_TOOL_NAMES


def test_help_tool_rejects_invalid_requests_and_reports_search_failure(monkeypatch):
    from lagniappe.core.tools.ai.function_definitions import get_help
    for args in (
        {},
        {'topic_id': 'form_creation'},
        {'topic_id': 'tasks', 'query': 'tasks'},
        {'list_topics': False},
        {'list_topics': True, 'query': 'tasks'},
        {'query': []},
        {'query': ' '},
        {'query': 'x' * 501},
        {'query': 'email', 'aliases': ['mail']},
    ):
        assert 'error' in get_help.execute_get_help(args, None)
    def unavailable(*_a, **_kw):
        raise ConnectionError('offline')
    monkeypatch.setattr(get_help.cache, 'help_search', unavailable)
    assert 'temporarily unavailable' in get_help.execute_get_help({'query': 'email'}, None)['error']
    assert get_help.execute_get_help({'topic_id': 'ai_email'}, None)['topics']


def test_help_search_strips_conversational_stopwords_and_relaxes_to_or(monkeypatch):
    captured = []
    monkeypatch.setattr(query, 'ensure_help', lambda: 'version')
    monkeypatch.setattr(query.cache, 'search', lambda q: captured.append(q._query_string) or SimpleNamespace(docs=[], total=0))
    assert query.help_search('the and !', limit=3) == ([], 0)
    assert captured == []

    assert query.help_search('how do I undo a completed task?', limit=3) == ([], 0)
    assert len(captured) == 2
    strict_sql, relaxed_sql = captured
    assert '(@keywords:undo | @keywords:undo*)' in strict_sql
    assert '@name:how' not in strict_sql and '@name:do' not in strict_sql
    assert ' | ((@name:task | @name:task*)' in relaxed_sql
    assert '((@kind:{ help } @help_version:{ version })) => { $weight: 0; }' in relaxed_sql
