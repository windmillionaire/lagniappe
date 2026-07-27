import pytest
from playwright.sync_api import expect

from config import SETTINGS
from testing.definitions import Categories, Projects, SitePages, Tasks, Users
from testing.elements import HeaderSearch, List
from testing.resources import Task

pytestmark = pytest.mark.e2e


# @features home permissions
# @dimensions anonymous-access
def test_anonymous_home_redirects_to_login(get_user):
    """The home permission wrapper redirects an anonymous request to login."""
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")

    anonymous.page.goto(f"{base_url}/")

    expect(anonymous.page).to_have_url(f"{base_url}/users/login?next=/")


# @features permissions
# @dimensions resource-gates search
def test_one_category_permissions(get_user):
    """
    Verify that a user with one category can access the home page and see their category
    but not the other categories and not the other lists.
    """
    user = get_user(Users.user_one_category)
    allowed_category = Categories.test_create_category_manual_mode.get(user)
    other_category = Categories.test_create_page.get(user)
    home = user.go(SitePages.HOME)

    task_list = List(user.locate(home.TASK_LIST))
    assert task_list.is_loaded

    expect(user.locate(home.TASK_LIST_TOGGLE)).not_to_be_disabled()
    expect(user.locate(home.PROJECT_LIST)).to_be_attached()
    expect(user.locate(home.PROJECT_LIST)).not_to_have_attribute("loaded", "")
    user.locate(home.PROJECT_LIST_TOGGLE).click()
    assert List(user.locate(home.PROJECT_LIST)).is_loaded
    expect(user.locate(home.PROJECT_LIST_TOGGLE)).not_to_have_attribute(
        "data-loading", "true"
    )
    expect(user.locate(home.PROJECT_LIST)).to_be_hidden()

    category_list = home.category_list
    expect(category_list.list.locator("li")).to_have_count(1)
    expect(category_list.get_item(allowed_category)).to_be_visible()
    expect(category_list.get_item(other_category)).not_to_be_attached()

    expect(user.locate(home.DIRECTORY_LIST).locator("li")).to_have_count(0)
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()

    search = HeaderSearch(user)
    search.verify_entity_in_results(allowed_category)
    search.verify_entity_not_in_results(other_category)


# @features permissions
# @dimensions owner global-resources
def test_admin_permissions(get_user):
    """
    Verify that an admin can access the home page and see model lists and tools.
    """
    user = get_user(Users.admin)
    cat_one = Categories.test_create_category_manual_mode.get(user)
    cat_two = Categories.test_create_page.get(user)
    project_one = Projects.test_create_project_manual_mode.get(user)
    home = user.go(SitePages.HOME)

    category_list = home.category_list
    expect(category_list.get_item(cat_one)).to_be_visible()
    expect(category_list.get_item(cat_two)).to_be_visible()

    project_list = home.project_list
    expect(project_list.get_item(project_one)).to_be_visible()

    directory_list = home.directory
    expect(directory_list.list.locator("li")).to_have_count(3)
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()

    expect(user.locate(home.TOOLS_COMPONENT)).to_be_attached()
    expect(user.locate("#ingress[lp-component]")).not_to_be_attached()


# @features permissions
# @dimensions global-resources
def test_directory_general_models_view_only(get_user):
    """Directory: Active Tasks; Manual is a standalone home link."""
    user = get_user(Users.general_models_view_only)
    home = user.go(SitePages.HOME)
    root = home.directory.list
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()
    expect(root.locator('a:has-text("Active Tasks")')).to_be_visible()
    expect(root.locator('a:has-text("Forms")')).not_to_be_attached()
    expect(root.locator('a:has-text("Users")')).not_to_be_attached()


# @features permissions
# @dimensions global-resources
def test_directory_general_forms_view_only(get_user):
    """Directory: Forms; Manual is a standalone home link."""
    user = get_user(Users.general_forms_view_only)
    home = user.go(SitePages.HOME)
    root = home.directory.list
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()
    expect(root.locator('a:has-text("Forms")')).to_be_visible()
    expect(root.locator('a:has-text("Active Tasks")')).not_to_be_attached()
    expect(root.locator('a:has-text("Users")')).not_to_be_attached()


# @features permissions
# @dimensions global-resources
def test_directory_general_users_view_only(get_user):
    """Directory: Users; Manual is a standalone home link."""
    user = get_user(Users.general_users_view_only)
    home = user.go(SitePages.HOME)
    root = home.directory.list
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()
    expect(root.locator('a:has-text("Users")')).to_be_visible()
    expect(root.locator('a:has-text("Active Tasks")')).not_to_be_attached()
    expect(root.locator('a:has-text("Forms")')).not_to_be_attached()


# @features permissions
# @dimensions global-resources
# @template home/categories.html::list
# @template home/home.html::links
def test_create_toggles_require_global_models_create(get_user):
    """Project and category create buttons require global model CREATE."""
    restricted = get_user(Users.user_one_category)
    Categories.test_create_category_manual_mode.get(restricted)
    home_r = restricted.go(SitePages.HOME)
    expect(restricted.locate(home_r.CREATE_PROJECT_TOGGLE)).not_to_be_attached()
    expect(restricted.locate(home_r.CREATE_CATEGORY_TOGGLE)).not_to_be_attached()
    admin = get_user(Users.admin)
    Categories.test_create_category_manual_mode.get(admin)
    home_a = admin.go(SitePages.HOME)
    expect(admin.locate(home_a.CREATE_PROJECT_TOGGLE)).to_be_attached()
    expect(admin.locate(home_a.CREATE_CATEGORY_TOGGLE)).to_be_attached()


# @features permissions
# @dimensions global-resources
def test_create_category_hides_form_picker_without_forms_view(get_user):
    """Create category form omits Default Form when user lacks General.FORMS VIEW."""
    user = get_user(Users.models_create_forms_none)
    home = user.go(SitePages.HOME)
    user.locate(home.CREATE_CATEGORY_TOGGLE).click()
    form = user.locate(home.CREATE_CATEGORY_FORM)
    expect(form).to_be_visible()
    expect(form.locator('[data-role="form-select"]')).not_to_be_attached()


# @features permissions
# @dimensions resource-gates home-actions
# @template home/categories.html::category
def test_category_home_rows_only_offer_star_controls(get_user):
    """Home category rows omit delete even when the user may delete the entity."""
    owner = get_user(Users.OWNER)
    cat_edit = Categories.test_create_category_manual_mode.get(owner)
    cat_delete = Categories.test_create_page.get(owner)

    subject = get_user(Users.two_categories_edit_and_delete)
    home = subject.go(SitePages.HOME)
    category_list = home.category_list

    for row in (category_list.get_item(cat_edit), category_list.get_item(cat_delete)):
        expect(row.locator("button[lp-control='star']")).to_be_attached()
        expect(row.locator("button[lp-control='delete']")).not_to_be_attached()


# @features home
# @dimensions permissions task-list view-only
# @template home/tasks.html::task
def test_home_task_list_shows_view_only_page_tasks_without_controls(get_user):
    """A readable page task appears on home without task action controls."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_home_view_only_page_task.get(owner)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(task)

    task_row = viewer.locate(f"[data-key='{task.key}']")
    expect(task_row).to_be_visible()
    complete_checkbox = task_row.locator(Task.COMPLETE_TASK_CHECKBOX)
    expect(complete_checkbox).to_be_visible()
    expect(complete_checkbox).to_be_disabled()

    home = viewer.go(SitePages.HOME)
    home_task = home.task_list.get_item(task)
    expect(home_task).to_be_visible()
    expect(home_task.locator(Task.COMPLETE_TASK_CHECKBOX)).not_to_be_attached()
    expect(home_task.locator("[data-role='change-due-date']")).not_to_be_attached()
