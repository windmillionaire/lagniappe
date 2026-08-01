import json
import re
from uuid import uuid4

import pytest

from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SitePages, Users
from testing.resources import SitePage

pytestmark = pytest.mark.e2e


SEARCH_INPUT = "[lp-search] input[name='q']"
SEARCH_RESULTS = "[data-role='results']"
SEARCH_FACETS = "[data-role='facets']"
SEARCH_FACET = "[data-role='attribute']"
SEARCH_TITLE = f"{SEARCH_RESULTS} a[data-role='title']"
PAGINATION_BUTTON = f"{SEARCH_RESULTS} button[data-role='pagination']"


def _unique(label):
    return f"test-search-{label}-{uuid4().hex[:8]}"


def _create_project(name, description=""):
    project = Entities.PROJECT.create(
        {
            "name": name,
            "description": description,
            "attributes": ["tasks", "document"],
        }
    )
    project.save()
    return project


def _create_category(name, description=""):
    category = Entities.CATEGORY.create(
        {
            "name": name,
            "description": description,
            "attributes": ["tasks", "document", "notes", "files"],
        }
    )
    category.save()
    return category


def _create_page(category, name):
    page = Entities.PAGE.create({"name": name, "model": category})
    page.save()
    return page


def _create_model_task(project, name):
    model_task = Entities.MODEL_TASK.create(project, {"name": name})
    model_task.save()
    return model_task


def _create_project_task(user, project, model_task, name):
    user_entity = Entities.fetch_one(user.entity, request=Fetch.direct())
    task = Entities.TASK.create(
        {
            "name": name,
            "page": user_entity.page,
            "model": model_task,
            "project": project,
        }
    )
    task = Entities.fetch_one(
        task,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    task.save()
    return task


def _result_titles(user):
    return user.locate(SEARCH_TITLE)


def _go_to_search_page(user, query):
    search_page = SitePage(url="/search-page")
    user.go(search_page, query_params={"q": query})
    results_view = user.locate("[lp-view][data-kind='results']")
    expect(results_view).to_be_visible()
    expect(results_view).to_have_attribute("initialized", "")


# @features search
# @dimensions anonymous-access
def test_search_page_requires_login(get_user):
    """Anonymous search requests redirect to login with the target preserved."""
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")
    anonymous.navigate(f"{base_url}/search-page?q=private-search")

    expect(anonymous.page).to_have_url(
        re.compile(r"/users/login\?next=.*search-page.*private-search")
    )


# @features search
# @dimensions navbar-submit page-navigation results
def test_search_from_navbar(get_user):
    """Test initiating search from navbar search input."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(SitePages.HOME)

    search_input = user.locate(SEARCH_INPUT)
    search_input.fill(project.definition.name)
    with user.page.expect_navigation(url="**/search-page**"):
        search_input.press("Enter")

    expect(user.page).to_have_url(re.compile(r".*/search-page\?q=.*"))
    expect(user.locate("[lp-view][data-kind='results']")).to_be_visible()
    expect(user.locate("[lp-view][data-kind='results']")).to_contain_text(
        project.definition.name
    )


# @features search
# @dimensions query-display
# @template search/search.html::main
def test_search_page_shows_query(get_user):
    """Test that search page shows the query term."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)

    _go_to_search_page(user, project.definition.name)
    expect(user.locate("[lp-view][data-kind='results']")).to_contain_text(
        project.definition.name
    )


# =============================================================================
# Search Results Tests
# =============================================================================


# @features search
# @dimensions results
def test_search_returns_results(get_user):
    """Test that search returns results for matching entities."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)

    _go_to_search_page(user, project.definition.name)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(project.definition.name)


# @features search
# @dimensions no-results
# @template search/results.html::search_results
def test_search_no_results(get_user):
    """Test display when search has no matching results."""
    user = get_user(Users.OWNER)

    _go_to_search_page(user, "zzz-no-search-results-here-zzz")
    expect(user.locate(SEARCH_RESULTS)).to_contain_text("No matches")


# @features search
# @dimensions result-title
# @template search/results.html::search_results
def test_search_result_titles(get_user):
    """Test that search results show entity titles."""
    user = get_user(Users.OWNER)
    name = _unique("title")
    _create_project(name, "Search result title fixture.")

    _go_to_search_page(user, name)

    title = _result_titles(user).filter(has_text=name)
    expect(title).to_be_visible()
    expect(title).to_have_attribute("data-kind", "project")


# @features search
# @dimensions primary-name-ranking
# @template search/results.html::search_results
def test_primary_name_matches_rank_above_file_name_and_description_matches(get_user):
    """Primary entity name matches rank above a file matching twice."""
    user = get_user(Users.OWNER)
    token = _unique("primary-rank").replace("-", "")
    category = _create_category(f"{token} category")
    page = _create_page(category, f"{token} page")
    _create_project(f"{token} project")
    file_entity = Entities.FILE.create(
        page=page,
        data={
            "name": f"{token} file",
            "description": f"The description also contains {token}.",
        },
    )
    file_entity.save()

    _go_to_search_page(user, token)

    titles = _result_titles(user)
    expect(titles).to_have_count(4)
    assert {
        titles.nth(index).get_attribute("data-kind") for index in range(3)
    } == {"category", "project", "page"}
    expect(titles.nth(3)).to_have_attribute("data-kind", "file")


# @features search
# @dimensions details-hydration parent-refresh
# @template search/results.html::search_results
def test_search_result_parent_details_refresh_after_category_rename(get_user):
    """Search hydrates result parents from the current detail cache."""
    user = get_user(Users.OWNER)
    page_name = _unique("parent-refresh-page")
    original_parent_name = _unique("original-parent")
    updated_parent_name = _unique("updated-parent")
    category = _create_category(original_parent_name)
    _create_page(category, page_name)

    _go_to_search_page(user, page_name)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(original_parent_name)

    category.name = updated_parent_name
    category.save()

    _go_to_search_page(user, page_name)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(updated_parent_name)
    expect(user.locate(SEARCH_RESULTS)).not_to_contain_text(original_parent_name)


# @features search
# @dimensions snippets
# @template search/results.html::search_results
def test_search_result_snippets(get_user):
    """Test that search results show relevant snippets."""
    user = get_user(Users.OWNER)
    snippet_term = _unique("snippet").replace("-", "")
    name = _unique("snippet-project")
    _create_project(
        name,
        f"The project description includes {snippet_term} so the highlighted "
        "search summary has real text to render.",
    )

    _go_to_search_page(user, snippet_term)

    result = user.locate(SEARCH_RESULTS).locator("li").filter(has_text=name)
    expect(result).to_be_visible()
    expect(result.locator("p").filter(has_text=snippet_term)).to_be_visible()
    expect(result.locator("b").filter(has_text=snippet_term)).to_be_visible()


# =============================================================================
# Facet Filtering Tests
# =============================================================================


# @features search
# @dimensions facets
# @template search/search.html::facet_button
def test_facets_displayed(get_user):
    """Test that facets (entity types) are displayed."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)

    _go_to_search_page(user, project.definition.name)
    expect(user.locate(SEARCH_FACETS)).to_be_visible()
    expect(user.locate(SEARCH_FACET)).not_to_have_count(0)


# @features search
# @dimensions facet-filter url-state results
# @template search/search.html::facet_button
def test_click_facet_filters_results(get_user):
    """Test that clicking a facet filters results by type."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)

    _go_to_search_page(user, project.definition.name)

    first_facet = user.locate(SEARCH_FACET).first
    kind = first_facet.get_attribute("data-kind")
    first_facet.click()

    selected_facet = user.locate(f"{SEARCH_FACET}[data-kind='{kind}']")
    expect(selected_facet).to_have_attribute("data-selected", "true")
    expect(user.page).to_have_url(re.compile(rf".*[?&]kind={re.escape(kind)}"))
    expect(user.locate(SEARCH_RESULTS)).to_be_visible()


# @features search
# @dimensions facet-state
# @template search/search.html::facet_button
def test_facet_selection_visual_state(get_user):
    """Test that selected facet has visual indication."""
    user = get_user(Users.OWNER)
    term = _unique("facet-state").replace("-", "")
    _create_project(f"{term} project", "Facet state project fixture.")
    _create_category(f"{term} category", "Facet state category fixture.")

    _go_to_search_page(user, term)

    project_facet = user.locate(f"{SEARCH_FACET}[data-kind='project']")
    category_facet = user.locate(f"{SEARCH_FACET}[data-kind='category']")
    project_facet.click()

    expect(user.locate(SEARCH_FACETS)).to_have_attribute("data-has-selection", "true")
    expect(project_facet).to_have_attribute("data-selected", "true")
    expect(project_facet).to_have_attribute("data-just-selected", "true")
    expect(category_facet).to_have_attribute("data-selected", "false")


# @features search
# @dimensions clear-facet
# @template search/search.html::main
def test_clear_facet_filter(get_user):
    """Test clearing facet filter shows all results."""
    user = get_user(Users.OWNER)
    term = _unique("facet-clear").replace("-", "")
    project = _create_project(f"{term} project", "Facet clear project fixture.")
    category = _create_category(f"{term} category", "Facet clear category fixture.")

    _go_to_search_page(user, term)
    expect(_result_titles(user)).to_have_count(2)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(project.name)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(category.name)

    project_facet = user.locate(f"{SEARCH_FACET}[data-kind='project']")
    project_facet.click()
    expect(project_facet).to_have_attribute("data-selected", "true")
    expect(_result_titles(user)).to_have_count(1)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(project.name)
    expect(user.locate(SEARCH_RESULTS)).not_to_contain_text(category.name)

    user.locate("[data-role='reset']").click()

    expect(user.locate(SEARCH_FACETS)).to_have_attribute("data-has-selection", "false")
    expect(project_facet).to_have_attribute("data-selected", "false")
    expect(_result_titles(user)).to_have_count(2)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(category.name)
    user.page.wait_for_function(
        "() => !new URL(window.location.href).searchParams.has('kind')"
    )


# @features search
# @dimensions facet-filter task-model result-links
# @template search/search.html::facet_button
# @template search/results.html::search_results
def test_task_facet_includes_task_and_model_results_with_links(get_user):
    """Task facet includes concrete tasks and model task stage links."""
    user = get_user(Users.OWNER)
    token = _unique("task-facet").replace("-", "")
    project = _create_project(
        f"{token} project",
        "Project fixture for the task search facet.",
    )
    model = _create_model_task(project, f"{token} model stage")
    task = _create_project_task(user, project, model, f"{token} concrete task")
    completed_task = _create_project_task(
        user,
        project,
        model,
        f"{token} completed task",
    )
    completed_task.completed = True
    completed_task.save()
    _go_to_search_page(user, token)
    user.locate(f"{SEARCH_FACET}[data-kind='task']").click()

    expect(user.page).to_have_url(re.compile(r".*[?&]kind=task"))

    model_link = _result_titles(user).filter(has_text=model.name)
    expect(model_link).to_be_visible()
    expect(model_link).to_have_attribute("data-kind", "model")
    expect(model_link).to_have_attribute(
        "href",
        (
            f"/projects/{project.urlsafe_key}/status/{model.urlsafe_key}"
            "?completed=false"
        ),
    )

    task_link = _result_titles(user).filter(has_text=task.name)
    expect(task_link).to_be_visible()
    expect(task_link).to_have_attribute("data-kind", "task")
    expect(task_link).to_have_attribute(
        "href",
        re.compile(rf"/tasks/{re.escape(task.urlsafe_key)}$"),
    )
    task_row = task_link.locator("xpath=ancestor::li")
    expect(task_row.locator("span[data-icon='unselected']")).to_have_count(1)
    expect(task_row.locator("span[data-icon='selected']")).to_have_count(0)

    completed_link = _result_titles(user).filter(has_text=completed_task.name)
    expect(completed_link).to_be_visible()
    completed_row = completed_link.locator("xpath=ancestor::li")
    expect(completed_row.locator("span[data-icon='selected']")).to_have_count(1)
    expect(completed_row.locator("span[data-icon='unselected']")).to_have_count(0)

# @pair search:navbar-results
# @pair search:task-model
# @pair search:result-links
# @pair template-formatting:tojson
# @pair template-formatting:safe-json
# @template nav.html::search_results
# @template common.html::format_name
def test_navbar_task_results_render_current_completion_state(get_user):
    user = get_user(Users.OWNER)
    token = _unique("navbar-task").replace("-", "")
    project = _create_project(f"{token} project")
    model = _create_model_task(project, f"{token} model stage")
    completed_task = _create_project_task(
        user,
        project,
        model,
        f"{token} completed task",
    )
    completed_task.completed = True
    completed_task.save()
    active_task = _create_project_task(
        user,
        project,
        model,
        f"{token} active task",
    )

    user.go(SitePages.HOME)
    navbar_search = user.locate("[lp-search] input[name='q']")
    navbar_search.fill(active_task.name)
    active_option = user.page.get_by_role("option").filter(
        has_text=active_task.name
    )
    expect(active_option).to_be_visible()
    expect(active_option.locator("span[data-icon='unselected']")).to_have_count(1)
    active_details = json.loads(active_option.get_attribute("data-result"))["details"]
    assert active_details.get("completed", False) is False

    navbar_search.fill(completed_task.name)
    completed_option = user.page.get_by_role("option").filter(
        has_text=completed_task.name
    )
    expect(completed_option).to_be_visible()
    expect(completed_option.locator("span[data-icon='selected']")).to_have_count(1)


# =============================================================================
# Search Result Navigation Tests
# =============================================================================


# @features search
# @dimensions result-navigation
# @template search/results.html::search_results
def test_click_result_navigates(get_user):
    """Test that clicking search result navigates to entity."""
    user = get_user(Users.OWNER)
    name = _unique("navigate")
    project = _create_project(name, "Search result navigation fixture.")

    _go_to_search_page(user, name)
    link = _result_titles(user).filter(has_text=name)

    with user.page.expect_navigation(url=f"**/projects/{project.urlsafe_key}"):
        link.click()

    expect(user.page).to_have_url(re.compile(rf".*/projects/{project.urlsafe_key}$"))
    expect(user.locate("[lp-view][data-kind='project']")).to_be_visible()
    expect(user.locate("[data-nav='view'] [data-role='title']")).to_contain_text(name)


# @features search
# @dimensions result-links
# @template search/results.html::search_results
def test_result_links_correct(get_user):
    """Test that result links point to correct entity URLs."""
    user = get_user(Users.OWNER)
    name = _unique("link")
    project = _create_project(name, "Search result link fixture.")

    _go_to_search_page(user, name)

    link = _result_titles(user).filter(has_text=name)
    expect(link).to_have_attribute(
        "href",
        re.compile(rf"/projects/{re.escape(project.urlsafe_key)}$"),
    )


# =============================================================================
# Pagination Tests
# =============================================================================


# @features search
# @dimensions pagination
# @template search/results.html::footer
def test_pagination_controls_visible(get_user):
    """Test that pagination controls are visible for many results."""
    user = get_user(Users.OWNER)
    term = _unique("pagination").replace("-", "")
    for index in range(12):
        _create_project(
            f"{term} result {index:02d}",
            "Search pagination fixture.",
        )

    _go_to_search_page(user, term)

    expect(user.locate(SEARCH_RESULTS).locator("li")).to_have_count(10)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(
        re.compile(r"Showing\s+1\s+to\s+10\s+of\s+12\s+results")
    )
    expect(user.locate(f"{PAGINATION_BUTTON}[data-page='1']")).to_be_visible()


# @features search
# @dimensions pagination-next
# @template search/results.html::footer
def test_next_page(get_user):
    """Test navigating to next page of results."""
    user = get_user(Users.OWNER)
    term = _unique("next-page").replace("-", "")
    for index in range(12):
        _create_project(
            f"{term} result {index:02d}",
            "Search next-page pagination fixture.",
        )

    _go_to_search_page(user, term)
    user.locate(f"{PAGINATION_BUTTON}[data-page='1']").click()

    expect(user.page).to_have_url(re.compile(r".*[?&]page=1"))
    expect(user.locate(SEARCH_RESULTS).locator("li")).to_have_count(2)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(
        re.compile(r"Showing\s+11\s+to\s+12\s+of\s+12\s+results")
    )


# @features search
# @dimensions pagination-previous
# @template search/results.html::footer
def test_previous_page(get_user):
    """Test navigating to previous page of results."""
    user = get_user(Users.OWNER)
    term = _unique("previous-page").replace("-", "")
    for index in range(12):
        _create_project(
            f"{term} result {index:02d}",
            "Search previous-page pagination fixture.",
        )

    _go_to_search_page(user, term)
    user.locate(f"{PAGINATION_BUTTON}[data-page='1']").click()
    expect(user.locate(f"{PAGINATION_BUTTON}[data-page='0']")).to_be_visible()

    user.locate(f"{PAGINATION_BUTTON}[data-page='0']").click()

    expect(user.page).to_have_url(re.compile(r".*[?&]page=0"))
    expect(user.locate(SEARCH_RESULTS).locator("li")).to_have_count(10)
    expect(user.locate(SEARCH_RESULTS)).to_contain_text(
        re.compile(r"Showing\s+1\s+to\s+10\s+of\s+12\s+results")
    )


# =============================================================================
# Search Query Tests
# =============================================================================


# @features search
# @dimensions exact-match
def test_search_exact_match(get_user):
    """Test search with exact entity name."""
    user = get_user(Users.OWNER)
    name = _unique("exact")
    _create_project(name, "Exact search fixture.")

    _go_to_search_page(user, name)

    expect(_result_titles(user).filter(has_text=name)).to_be_visible()


# @features search
# @dimensions partial-match
def test_search_partial_match(get_user):
    """Test search with partial text matches."""
    user = get_user(Users.OWNER)
    token = f"partial{uuid4().hex[:10]}"
    name = f"{token} complete project"
    _create_project(name, "Partial search fixture.")

    _go_to_search_page(user, token[:8])

    expect(_result_titles(user).filter(has_text=name)).to_be_visible()


# @features search
# @dimensions special-characters
def test_search_special_characters(get_user):
    """Test search handles special characters."""
    user = get_user(Users.OWNER)
    token = uuid4().hex[:8]
    name = f"Special Search {token}: Pipe|Slash/Colon Value"
    _create_project(name, "Special character search fixture.")

    _go_to_search_page(user, f"{token}: Pipe|Slash/Colon")

    expect(_result_titles(user).filter(has_text=name)).to_be_visible()
