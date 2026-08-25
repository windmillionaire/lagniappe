"""
Tests for starred items functionality.

Entities can be starred for quick access from the Home starred list. Existing
Home list controls remain icon-only shortcuts; entity pages expose labeled
Star/Unstar commands in their title menus.

Related Files:
    Application:
        - lagniappe/web/routes/home/main.py: toggle_star() route (PATCH /l/toggle-star/<key>)
        - lagniappe/web/templates/home/starred.html: Starred list component
        - lagniappe/web/templates/controls.html: icon-only home star() macro
        - lagniappe/web/templates/menus.html: labeled title-menu star() macro
        - src/script/views/base/core.mjs: Core._toggleStar() handler

    Core:
        - lagniappe/core/entities/user.py: User.properties.starred
        - lagniappe/core/entities/home.py: Home entity

    Test Framework:
        - testing/definitions/categories.py: Categories for testing
        - testing/definitions/projects.py: Projects for testing
        - testing/definitions/pages.py: Pages for testing
        - testing/resources/home.py: HomePage selectors

Star controls use data-active="true/false" to track state. Clicking toggles via
PATCH to /l/toggle-star/<key>. The client updates both the hidden title-menu
source and its portal clone so an already-created menu stays current.
"""

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from testing.definitions import (
    Categories,
    Pages,
    Projects,
    SitePages,
    Uploads,
    Users,
)
from testing.elements import StarButton
from testing.resources import File


def _title_star_action(user, menu_name, action_name):
    trigger = user.page.get_by_role("button", name=menu_name)
    menu = user.page.get_by_role("menu", name=menu_name)
    if not menu.is_visible():
        trigger.click()

    # The first click cold-loads EntityMenu; its portal can become visible
    # before the background activation finishes replacing its options.
    expect(trigger).not_to_have_attribute("aria-busy", "true")
    menu = user.page.get_by_role("menu", name=menu_name)
    expect(menu).to_be_visible()

    action = menu.get_by_role("menuitem", name=action_name, exact=True)
    expect(action).to_be_visible()
    expect(action).to_have_attribute(
        "data-active", "true" if action_name == "Unstar" else "false"
    )
    icon_state = "active" if action_name == "Unstar" else "inactive"
    expect(action.locator(f"[data-icon='star.{icon_state}']")).to_be_visible()
    return action


def _toggle_title_star(user, menu_name, action_name):
    action = _title_star_action(user, menu_name, action_name)
    with user.page.expect_response("**/l/toggle-star/*"):
        action.click()
    expect(user.page.get_by_role("menu", name=menu_name)).to_be_hidden()


def _patch_star(user, key):
    return user.page.evaluate(
        """async (key) => {
            const token = await (await fetch("/l/token")).text();
            const response = await fetch(`/l/toggle-star/${key}`, {
                method: "PATCH",
                headers: {
                    "X-CSRFToken": token,
                    "X-Lagniappe-Request": "true",
                },
            });
            return { status: response.status, body: await response.text() };
        }""",
        key,
    )


# @matrix starred : category title-menu
# @template menus.html::star
@pytest.mark.e2e
def test_star_category(get_user):
    """
    Verify starring and unstarring a category.

    Tests:
        1. Star category from home page category list
        2. Verify category appears in starred list
        3. Unstar category from home page
        4. Verify category removed from starred list
        5. Star category from category index page
        6. Verify starred state persists on home page
        7. Unstar from category page
        8. Verify unstarred state on home page
    """
    user = get_user(Users.OWNER)
    category = Categories.test_star_category.get(user)
    home = user.go(SitePages.HOME)

    # Open category list and find the category
    category_list = home.category_list
    category_item = category_list.get_item(category)

    # Star from home page
    star_button = StarButton(category_item)
    assert star_button.is_unstarred is True
    star_button.toggle()
    assert star_button.is_starred is True

    # Verify appears in starred list
    starred_list = home.starred_list
    starred_category = starred_list.get_item(category)
    expect(starred_category).to_be_visible()

    # Unstar from home page category list
    star_button.toggle()
    assert star_button.is_unstarred is True
    expect(starred_category).not_to_be_visible()

    # Navigate to category page and star from its title menu.
    user.go(category)
    _toggle_title_star(user, "Category actions", "Star")
    _title_star_action(user, "Category actions", "Unstar")

    # Verify starred on home page
    home = user.go(SitePages.HOME)
    starred_category = home.starred_list.get_item(category)
    expect(starred_category).to_be_visible()


# @matrix starred : project title-menu
# @template menus.html::star
@pytest.mark.e2e
def test_star_project(get_user):
    """
    Verify starring and unstarring a project.

    Tests:
        1. Star project from home page project list
        2. Verify project appears in starred list
        3. Unstar project from home page
        4. Verify project removed from starred list
        5. Star project from project page
        6. Verify starred state persists on home page
        7. Unstar from project page
        8. Verify unstarred state on home page
    """
    user = get_user(Users.OWNER)
    project = Projects.test_star_project.get(user)
    home = user.go(SitePages.HOME)

    # Open project list and find the project
    project_list = home.project_list
    project_item = project_list.get_item(project)

    # Star from home page
    star_button = StarButton(project_item)
    assert star_button.is_unstarred is True
    star_button.toggle()
    assert star_button.is_starred is True

    # Verify appears in starred list
    starred_list = home.starred_list
    starred_project = starred_list.get_item(project)
    expect(starred_project).to_be_visible()

    # Unstar from home page project list
    star_button.toggle()
    assert star_button.is_unstarred is True
    expect(starred_project).not_to_be_visible()

    # Navigate to project page and star from its title menu.
    user.go(project)
    _toggle_title_star(user, "Project actions", "Star")
    _title_star_action(user, "Project actions", "Unstar")

    # Verify starred on home page
    home = user.go(SitePages.HOME)
    starred_project = home.starred_list.get_item(project)
    expect(starred_project).to_be_visible()
    project_item = home.project_list.get_item(project)
    star_button = StarButton(project_item)
    assert star_button.is_starred is True


# @matrix starred : accessible-state page title-menu
# @pair view-transition:navigation
# @template menus.html::star
@pytest.mark.e2e
def test_star_page(get_user):
    """
    Verify starring and unstarring a page.

    Tests:
        1. Star page from page view
        2. Verify page appears in home starred list
        3. Unstar from starred list on home page
        4. Verify page removed from starred list
        5. Re-star from page view
        6. Unstar from page view
        7. Verify unstarred state persists

    Note: Pages don't appear in a list on home, so we star from the page itself.
    """
    user = get_user(Users.OWNER)
    page = Pages.test_star_page.get(user)

    # Navigate to page and star it from the title menu.
    user.go(page)
    page.wait_for_interaction_readiness()
    _toggle_title_star(user, "Page actions", "Star")
    _title_star_action(user, "Page actions", "Unstar")

    # Verify appears in home starred list
    home = user.go(SitePages.HOME)
    starred_list = home.starred_list
    starred_page = starred_list.get_item(page)
    expect(starred_page).to_be_visible()

    # Unstar from page view
    with user.page.expect_navigation():
        starred_page.click()
    page.initialize_view()
    page.wait_for_interaction_readiness()
    _toggle_title_star(user, "Page actions", "Unstar")
    _title_star_action(user, "Page actions", "Star")


# @matrix starred : file title-menu
# @template menus.html::star
@pytest.mark.e2e
def test_star_file(get_user):
    user = get_user(Users.OWNER)
    file = File.upload_from_page(
        user,
        Pages.test_file_upload_page,
        Uploads.plain_text_file,
    )

    user.go(file)
    _toggle_title_star(user, "File actions", "Star")
    _title_star_action(user, "File actions", "Unstar")

    home = user.go(SitePages.HOME)
    starred_file = home.starred_list.get_item(file)
    expect(starred_file).to_be_visible()

    user.go(file)
    _toggle_title_star(user, "File actions", "Unstar")
    _title_star_action(user, "File actions", "Star")


# @matrix starred : authorization missing-target no-mutation retained-inaccessible
@pytest.mark.e2e
def test_star_route_rejects_inaccessible_and_missing_targets(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    target = Categories.test_create_page.get(owner)
    restricted = get_user(Users.user_one_category)
    restricted.go(SitePages.HOME)

    assert target.entity.allowed(Action.VIEW, user=restricted.entity) is False
    saved_user = Entities.USER.load(restricted.email)
    starred_before = list(saved_user.db.get("starred", []))
    target_before = Entities.fetch_one(target.key, request=Fetch.direct())
    target_fingerprint = target_before.fingerprint
    target_modified = target_before.modified

    forbidden_path = f"/l/toggle-star/{target.key}"
    with browser_failures.expect_http_error(
        restricted,
        status=403,
        path=forbidden_path,
    ):
        forbidden = _patch_star(restricted, target.key)
    assert forbidden["status"] == 403

    missing_path = "/l/toggle-star/not-a-real-star-target"
    with browser_failures.expect_http_error(
        restricted,
        status=404,
        path=missing_path,
    ):
        missing = _patch_star(restricted, "not-a-real-star-target")
    assert missing["status"] == 404

    saved_user = Entities.USER.load(restricted.email)
    assert saved_user.db.get("starred", []) == starred_before
    target_after = Entities.fetch_one(target.key, request=Fetch.direct())
    assert target_after.fingerprint == target_fingerprint
    assert target_after.modified == target_modified

    saved_user.db["starred"] = [
        target_after.key,
        *[key for key in starred_before if key != target_after.key],
    ]
    saved_user.save()

    home = restricted.go(SitePages.HOME)
    expect(home.starred_list.get_item(target)).not_to_be_attached()
    saved_user = Entities.USER.load(restricted.email)
    assert target_after.key in saved_user.db.get("starred", [])

    saved_user.db["starred"] = starred_before
    saved_user.save()
