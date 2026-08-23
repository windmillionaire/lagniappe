import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Forms, SitePages, Users
from testing.elements import Dropdown, MobileTableControls
from testing.resources.site import FormIndex

pytestmark = pytest.mark.e2e


# @features table-controls
# @dimensions mobile-controls mobile-tools mutual-exclusion
# @template forms/index.html::view_header
# @template table.html::mobile_toggles
def test_form_index_mobile_tools_and_column_controls_are_exclusive(get_user):
    user = get_user(Users.OWNER)
    Forms.test_create_page_form.get(user)
    user.go(SitePages.FORM_INDEX)

    user.mobile = True
    controls = MobileTableControls(user)
    controls.open()
    expect(controls.row("name")).to_be_visible()
    expect(controls.row("form_type")).to_be_visible()

    dropdown_button = user.locate("[data-role='tools-dropdown']")
    expect(dropdown_button).to_be_visible()
    expect(dropdown_button).to_have_attribute("data-combobox-id", re.compile(".+"))

    Dropdown(dropdown_button).select_by_name("New Form")

    expect(controls.panel).to_be_hidden()
    create_form = user.locate(FormIndex.CREATE_FORM_WIDGET)
    expect(create_form).to_be_visible()
    expect(create_form.locator("input[name='name']")).to_be_visible()

    controls.open()

    expect(create_form).to_be_hidden()
    expect(controls.panel).to_be_visible()
