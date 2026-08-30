from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import General, Levels
from lagniappe.core.entities import Entities
from testing.definitions import Forms, Pages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.elements import HeaderSearch
from testing.resources import Page
from testing.utility.user_cache import acknowledge_user_cache_invalidation


pytestmark = pytest.mark.e2e


# @matrix search : permissions
# @pair cache:invalidation-acknowledgement
def test_search_matches_explicit_denial_and_administrator_content_access(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    user = get_user(
        UserDefinition(
            name=f"Search Authorization User {suffix[:8]}",
            email=f"search-authorization-{suffix}@example.test",
        ),
        creator=owner,
    )
    unrestricted_form = Forms.test_basic_inputs_form.get(owner)
    restricted_page = Pages.test_owner_restricted_page.get(owner)
    restricted_page.entity.properties.restricted_to.add("owner")
    restricted_page.entity.save()

    user.entity.properties.permissions.create({General.FORMS.value: Levels.NONE.name})
    user.entity.save()
    acknowledge_user_cache_invalidation(user)
    HeaderSearch(user).verify_entity_not_in_results(unrestricted_form)

    user.entity.is_admin = True
    user.entity.save()
    try:
        acknowledge_user_cache_invalidation(user)
        HeaderSearch(user).verify_entity_in_results(restricted_page)
        user.go(restricted_page)
        expect(user.locate(Page.PAGE_TITLE)).to_contain_text(
            restricted_page.definition.name
        )
    finally:
        user.entity = Entities.USER.load(user.email)
        user.entity.is_admin = False
        user.entity.save()
        acknowledge_user_cache_invalidation(user)
