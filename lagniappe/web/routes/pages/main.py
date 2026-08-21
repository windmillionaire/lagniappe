from flask import abort, request
from flask_login import current_user

from lagniappe.core.entities import Entities
from lagniappe.core.definitions import (
    AI,
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)
from lagniappe.core.tools import ai, database
from lagniappe.core.tools.form_state import is_form_field, offline_replay_conflicts
from lagniappe.core.definitions import PageAttributes, Action, Fetch, Resource
from lagniappe.web.auth import (
    abort_public_user_action,
    logged_in,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web import deferred_autofill

from . import pages


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_own_page_hides_photo_and_file_surfaces
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_file_and_photo_actions_are_forbidden
# @features public-users
# @dimensions own-page file-photo-gates
def _is_public_users_own_page(page):
    return bool(
        getattr(current_user, "is_public", False)
        and getattr(getattr(current_user, "page", None), "key", None) == page.key
    )


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_preloads_existing_groups
# @pair user-settings:group-selector
# @pair user-settings:preload
# @pair user-settings:relation-loading
def _load_user_settings_groups(page):
    """Attach group relations needed by another user's settings selector."""
    is_own_page = getattr(getattr(current_user, "page", None), "key", None) == page.key
    if page.user and current_user.is_admin and not is_own_page:
        Entities.fetch_one(page.user, request=Fetch.direct())
    return page


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_restricted_schedules_are_forbidden
# @features public-users
# @dimensions attribute-preservation
def _preserve_public_user_page_attributes(page, page_data):
    if not getattr(current_user, "is_public", False):
        return

    preserved = {"photo", "files"}
    submitted = set(page_data.get("attributes") or [])
    existing = {attribute.name for attribute in page.attributes if attribute.active}
    if _is_public_users_own_page(page):
        page_data["attributes"] = sorted(existing)
        return

    page_data["attributes"] = sorted(submitted | (existing & preserved))


# @testable true
# @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_is_forbidden_without_model_or_page_permission
# @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_reads_page_without_page_editing_affordances
# @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_sees_document_tab_only_when_content_exists
# @features pages
# @dimensions load tabs permission-gates readonly document-tab
@pages.route("<key>", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def view(key, **kwargs):
    page = _load_user_settings_groups(kwargs["entity"])

    return responses.page(page)


# @testable true
# @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
# @pairs ai:autofill ai:deferred ai:completion-refresh
@pages.route("<key>/info/replace", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def info(key, **kwargs):
    page = kwargs["entity"]
    return responses.page_info(page)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::user_settings
@pages.route("<key>/user-settings/replace", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def user_settings(key, **kwargs):
    page = _load_user_settings_groups(kwargs["entity"])
    is_own_page = getattr(getattr(current_user, "page", None), "key", None) == page.key
    if not page.user or not (is_own_page or Resource.USER.allowed(Action.PERMISSIONS)):
        abort(403)
    return responses.user_settings(page)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::page_permissions
@pages.route("<key>/permissions/replace", methods=["GET"])
@permission(Resource.PAGE, Action.PERMISSIONS)
def permissions(key, **kwargs):
    return responses.page_permissions(kwargs["entity"])


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::page_document_settings
@pages.route("<key>/document-settings/replace", methods=["GET"])
@permission(Resource.PAGE, Action.PUBLISH)
def document_settings(key, **kwargs):
    return responses.page_document_settings(kwargs["entity"])


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_basic_page_task
# @features tasks
# @dimensions create basic
@pages.route("<key>/tasks", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def tasks(key, **kwargs):
    page = kwargs["entity"]

    return responses.page_tasks(page)


# @testable true
# @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_sees_empty_files_tab_without_upload_affordances
# @features files
# @dimensions readonly empty-state permission-gates async-load
@pages.route("<key>/files", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def files(key, **kwargs):
    page = kwargs["entity"]
    if _is_public_users_own_page(page):
        abort_public_user_action()

    return responses.page_files(page)


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::create
# @covered-by lagniappe/web/routes/pages/main.py::update
# @reason page form parsing helper owned by page create/update workflows
def _page_data(form, page=None, category=None):
    """Resolve form data into a dict suitable for Page.create() or Page.update()."""
    entities = [page, category]
    # A user-Page save also persists its owning User, whose requirements use
    # groups, while Page.update() registers forms with the reserved Users model.
    # Make both entities direct roots without widening every Page update to a
    # nested fetch.
    if page and isinstance(page.model, Entities.USERS):
        entities.extend((page.model, page.user))
    for e in ["category", "form", "model", "group", "reassign-page"]:
        entities.extend(form.getlist(e))
    loaded = {
        e.urlsafe_key: e for e in Entities.fetch(*entities, request=Fetch.direct())
    }

    attributes = [a.name for a in PageAttributes if form.get(a.name)]

    page_data = {
        "name": form.get("name"),
        "description": form.get("description"),
        "email": form.get("email"),
        "attributes": attributes,
        "categories": [
            loaded.get(k) for k in form.getlist("category") if loaded.get(k)
        ],
        "form": loaded.get(form.get("form")),
        "model": loaded.get(category.urlsafe_key) if category else None,
        "groups": [loaded.get(k) for k in form.getlist("group") if loaded.get(k)],
    }
    if "reassign-page" in form:
        page_data["reassign-page"] = loaded.get(form.get("reassign-page"))
    if "remove-user" in form:
        page_data["remove-user"] = form.get("remove-user") == "true"
    if "ai_access" in form:
        page_data["ai_access"] = form.get("ai_access")
    if "notification_email_mode" in form:
        page_data["notification_email_mode"] = form.get(
            "notification_email_mode"
        )
    if "allow_site_email" in form:
        page_data["allow_site_email"] = form.get("allow_site_email") == "true"
    for toggle in ("allow_messages_and_mentions", "allow_task_assignments"):
        if toggle in form:
            page_data[toggle] = form.get(toggle) == "true"

    return page_data


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::create
# @covered-by lagniappe/web/routes/pages/main.py::update
# @reason autofill prompt data assembly is part of page create/update request flow
def _autofill_data(page, request, create=False):
    file = request.files.get("autofill-file") or direct_uploads.direct_upload_file(
        "autofill-file", consumer=FileConsumer.AI_INLINE
    )
    if file:
        try:
            enforce_file_consumer(
                file,
                FileConsumer.AI_INLINE,
                filename=getattr(file, "filename", None),
            )
        except FileConsumerLimitError as error:
            abort(422, description=str(error))
    return ai.autofill_prompt_data(
        page,
        current_user,
        user_context=request.form.get("autofill-description"),
        file=file,
        mimetype=request.form.get("mimetype"),
        create=create,
    )


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_switch_page_form
# @features pages
# @dimensions form-switch info-form
def _page_form_submission_response(page):
    return responses.form_submission(page)


# @testable true
# @scaffolding testing/resources/page.py::Page.submit_and_verify_submission
# @pairs pages:submission pages:default-form pages:basic-inputs
# @pairs pages:selection-fields pages:link-field
def _apply_page_submission(page, form):
    page.form_submission(form)


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_category_to_page
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_remove_category_from_page
# @features pages
# @dimensions category-add category-remove
def _apply_page_metadata_update(page, page_data, user=None):
    page.update(page_data)
    if page.user:
        page.update_user(page_data, user=user)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_submit_preserves_attached_form_and_categories
# @features user-settings
# @dimensions submit-boundary attached-form categories restrictions
def _apply_user_settings_update(page, page_data, user=None):
    if not page.user:
        return
    page.name = page_data.get("name")
    page.update_user(page_data, user=user)


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::update
# @reason notification persistence policy belongs to page update replay handling
def _offline_update_notification(page):
    notification = Entities.NOTIFICATION.create(
        {
            "parent": current_user,
            "target": page,
            "body": "Offline page update synced.",
        }
    )
    Entities.save(notification)
    return notification


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::update
# @reason form flag parsing is a route coordination detail
def _is_offline_replay(form):
    return str(form.get("offline", "")).lower() == "true"


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::_page_form_submission_response
# @covered-by lagniappe/web/routes/pages/main.py::_apply_page_submission
# @covered-by lagniappe/web/routes/pages/main.py::_apply_page_metadata_update
# @reason endpoint coordinates request flow while focused helpers own page form and submission behavior
@pages.route("<key>/update", methods=["PUT", "GET"])
@permission(Resource.PAGE, Action.VIEW)
def update(key, **kwargs):
    page = kwargs["entity"]

    if request.method == "GET":
        if request.values.get("form"):
            page.form = Entities.fetch_one(
                request.values.get("form"), request=Fetch.direct()
            )
        return _page_form_submission_response(page)
    elif not page.allowed(Action.EDIT):
        abort(403)

    if offline_replay_conflicts(page, request.form):
        return responses.page_info(page, conflict=True)

    role = request.form.get("role")
    if role != "user-settings":
        locked = deferred_autofill.locked_response(page, request.form)
        if locked:
            return locked

    if role == "autofill-submit" and request.files.get("autofill-file"):
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    old_attributes = [a.name for a in page.attributes if page.has(a.name)]
    old_image = page.image.path if page.image else None

    page_data = _page_data(request.form, page=page)
    _preserve_public_user_page_attributes(page, page_data)

    if role == "user-settings":
        try:
            _apply_user_settings_update(page, page_data, user=current_user)
        except PermissionError:
            abort(403)
        except ValueError as error:
            return responses.error(str(error))
        page.save()
        if not page.user:
            return responses.json_response({"reload": True})
        return responses.user_settings(page)

    if role in ["autofill-submit", "explain"]:
        require_ai_access(AI.CREATE)
        _apply_page_metadata_update(page, page_data, user=current_user)
        if page.form:
            _apply_page_submission(page, request)
        if role == "explain":
            try:
                prompt = ai.form_autofill_prompt(**_autofill_data(page, request))
                return responses.explain(prompt)
            finally:
                direct_uploads.cleanup_direct_uploads(
                    request.form, input_name="autofill-file"
                )

        page.save()
        return responses.entity_response(
            deferred_autofill.start_deferred_autofill(
                page,
                current_user,
                request.form,
                multipart_file=bool(request.files.get("autofill-file")),
            ),
            page,
        )
    else:
        _apply_page_metadata_update(page, page_data, user=current_user)
        _apply_page_submission(page, request)

    page.save()
    if _is_offline_replay(request.form):
        _offline_update_notification(page)
        return responses.entity_response(
            responses.json_response({"ok": True}),
            page,
        )

    new_attributes = [a.name for a in page.attributes if page.has(a.name)]
    new_image = page.image.path if page.image else None

    if set(old_attributes) != set(new_attributes) or old_image != new_image:
        return responses.json_response({"reload": True})

    return responses.page_info(page)


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::update
# @reason route permission mirrors page update for autofill uploads
@pages.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def update_direct(key, **kwargs):
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    locked = deferred_autofill.locked_response(kwargs["entity"], request.form)
    if locked:
        return locked
    return direct_uploads.direct_upload_response()


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::set_attribute
# @reason attribute-set persistence is owned by the page attribute endpoint
def _set_page_attribute(page, attribute, active):
    active_attributes = {item.name for item in page.attributes if page.has(item.name)}
    if active:
        active_attributes.add(attribute)
    else:
        active_attributes.discard(attribute)
    page.attributes = [
        item.name for item in page.attributes if item.name in active_attributes
    ]


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_page_attribute_toggle_updates_tabs_without_reload
# @tests tests_e2e/005_pages/test_005f_page_image.py::test_empty_page_photo_prompt_can_disable_photo_without_reload
# @features pages
# @dimensions attributes-live-toggle photo-prompt photo-disable tabs no-reload
@pages.route("<key>/attributes/<attribute>", methods=["PUT"])
@permission(Resource.PAGE, Action.EDIT)
def set_attribute(key, attribute, **kwargs):
    if attribute not in PageAttributes.__members__:
        abort(404)

    page = kwargs["entity"]
    if getattr(current_user, "is_public", False) and attribute in {"photo", "files"}:
        abort_public_user_action()

    data = request.get_json(silent=True) or {}
    active = bool(data.get("active"))

    _set_page_attribute(page, attribute, active)
    page.save()

    return responses.entity_response(
        responses.json_response({"attribute": attribute, "active": active}),
        page,
    )


# @testable true
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_quick_edit_updates_text_cell
# @features category-index
# @dimensions quick-edit editable-cell
@pages.route("<key>/patch", methods=["PATCH"])
@permission(Resource.PAGE, Action.EDIT)
def patch(key, **kwargs):
    page = kwargs["entity"]

    patch_data = request.json
    schema_id = patch_data["schema_id"]
    value = patch_data["value"]
    column = patch_data.get("column")

    if is_form_field(page, schema_id):
        locked = deferred_autofill.locked_response(page)
        if locked:
            return locked

    if schema_id in page.properties:
        field = page.properties[schema_id]
        if not field.editable:
            return responses.error("Field cannot be edited")
        field.value = value
    else:
        field = page.properties.submission.fields.get(schema_id)
        if not field or not field.editable:
            return responses.error("Field cannot be edited")
        field = page.properties.submission.patch(schema_id, value)
        page.save_submission()

    page.save()

    return responses.entity_response(
        responses.cell(field, page, column=column),
        page,
        *page.page_list_owners,
    )


# @testable true
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_from_category_index
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
# @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_tools_dropdown_opens_new_page_form
# @features pages
# @dimensions create category-index mobile-tools
@pages.route("<key>/create", methods=["POST"])
@permission(Resource.CATEGORY, Action.EDIT)
def create(key, **kwargs):
    """Create a page within a category. Key is the category key, not a page key."""
    category = kwargs["entity"]

    create_data = _page_data(request.form, category=category)
    page = Entities.PAGE.create(create_data)
    role = request.form.get("role")

    if role == "autofill-submit" and request.files.get("autofill-file"):
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    if role in ["autofill-submit", "explain"]:
        require_ai_access(AI.CREATE)
        if role == "explain":
            try:
                prompt = ai.form_autofill_prompt(
                    **_autofill_data(page, request, create=True)
                )
                return responses.explain(prompt)
            finally:
                direct_uploads.cleanup_direct_uploads(
                    request.form, input_name="autofill-file"
                )

        if page.form:
            _apply_page_submission(page, request)
        page.save()
        deferred_response = deferred_autofill.start_deferred_autofill(
            page,
            current_user,
            request.form,
            multipart_file=bool(request.files.get("autofill-file")),
            key=category.urlsafe_key,
            source_widget="CreatePage",
            destination="table:IndexTable",
        )
        if not isinstance(deferred_response, tuple):
            return responses.entity_response(deferred_response, category)

        response, status = deferred_response
        payload = response.get_json()
        payload.pop("locked", None)
        payload.pop("scope", None)
        payload["background"] = True
        payload["html"] = responses.rows(page, category.index())[0]
        return responses.entity_response(
            responses.json_response(payload, status=status), category
        )

    page.save()

    return responses.entity_response(
        responses.rows(page, category.index()),
        category,
    )


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::create
# @reason route permission mirrors page create for upload-backed form data
@pages.route("<key>/create/direct-upload", methods=["POST"])
@permission(Resource.CATEGORY, Action.EDIT)
def create_direct(key, **kwargs):
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/002_home/test_002k_home_pages.py::test_create_page_from_home
# @features home pages
# @dimensions create category-select default-category
@pages.route("create", methods=["POST"])
@logged_in
def create_from_home():
    """Create a page from the homepage, using a selected or default category."""
    if not current_user.properties.restrictions.category_edit_restrictions:
        abort(403)

    if not (request.form.get("name") or "").strip():
        return responses.error("Name this page before creating it.")

    category_key = request.form.get("category")
    if category_key:
        category = Entities.fetch_one(category_key, request=Fetch.direct())
        if not isinstance(category, Entities.CATEGORY):
            return responses.error("Choose a category before creating this page.")
        if not category.allowed(Action.EDIT, current_user):
            abort(403)
    else:
        category = Entities.CATEGORY.get_uncategorized_pages()
        if not category.allowed(Action.EDIT, current_user):
            return responses.error("Choose a category before creating this page.")

    create_data = _page_data(request.form, category=category)
    create_data["model"] = category
    create_data["categories"] = [
        c for c in create_data.get("categories", []) if c and c.key != category.key
    ]
    if not create_data.get("form") and category.form:
        create_data["form"] = category.form

    page = Entities.PAGE.create(create_data)
    page.save()

    return responses.new_page(page)


# @testable true
# @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_cascades_dependents_assets_and_cache
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_delete_page_from_title_menu
# @features pages
# @dimensions delete title-menu parentless
@pages.route("<key>/delete", methods=["DELETE"])
@permission(Resource.PAGE, Action.DELETE)
def delete(key, **kwargs):
    page = kwargs["entity"]
    if not page:
        return responses.error("page not found")

    categories = list(page.categories)
    editable_categories = [c for c in categories if c.allowed(Action.EDIT)]
    retained_categories = [c for c in categories if c not in editable_categories]
    notify_hashes = set()

    for category in editable_categories:
        page.properties.categories.remove(category)
        notify_hashes.add(category.hash)

    if not retained_categories:
        Entities.delete(page)
        Entities.save(*categories)
    else:
        page.save()
        Entities.save(*editable_categories)

    return responses.ok()


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_document_visibility_can_toggle_public_private
# @features pages
# @dimensions document-visibility public private
@pages.route("<key>/visibility", methods=["PUT"])
@permission(Resource.PAGE, Action.PUBLISH)
def visibility(key, **kwargs):
    page = kwargs["entity"]

    page.is_public = True if request.form["visibility"] == "public" else False
    if page.is_public:
        page.public_id
    Entities.save(page)

    return responses.page_document_settings(page)


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_public
# @tests tests_unit/test_008_page_properties.py::test_page_to_cache_public_user
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_document_visibility_can_toggle_public_private
# @features pages
# @dimensions public-document
@pages.route("public/<public_id>", methods=["GET"])
def public(public_id):
    public_pages = Entities.fetch(
        *database.get.public_pages(public_id), request=Fetch.root()
    )
    page = next((page for page in public_pages if page.is_public), None)

    if not page:
        abort(404)

    return responses.public_document(page)


# @testable true
# @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_owner_can_open_page_permissions_panel
# @features pages
# @dimensions permissions-panel permission-gates
def _page_view_access_response(page):
    return responses.page_view_access(page)


# @testable true
# @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_owner_restricted_page_is_hidden_from_model_viewer
# @features pages
# @dimensions access-restrictions owner-restricted
def _apply_owner_access_restriction(page, owner):
    if owner == "add":
        page.groups = None
        page.properties.restricted_to.add("owner")
    elif owner == "remove":
        page.properties.restricted_to.remove("owner")


# @testable true
# @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_group_restricted_page_opens_for_member_only
# @features pages
# @dimensions access-restrictions group-restricted
def _apply_group_access_restriction(page, group_action, group_key):
    group = Entities.fetch_one(group_key, request=Fetch.direct())
    if not group:
        abort(404)
    if group_action == "add":
        page.properties.groups.add(group)
    elif group_action == "remove":
        page.properties.groups.remove(group)


# @testable false
# @covered-by lagniappe/web/routes/pages/main.py::_page_view_access_response
# @covered-by lagniappe/web/routes/pages/main.py::_apply_owner_access_restriction
# @covered-by lagniappe/web/routes/pages/main.py::_apply_group_access_restriction
# @reason endpoint coordinates page access requests while focused helpers own response and mutation behavior
@pages.route("<key>/view-access", methods=["GET", "PUT"])
@permission(Resource.PAGE, Action.PERMISSIONS)
def view_access(key, **kwargs):
    page = kwargs["entity"]

    if request.method == "PUT":
        owner = request.form.get("owner")
        group = request.form.get("group")
        if owner:
            _apply_owner_access_restriction(page, owner)
        elif group:
            _apply_group_access_restriction(page, group, request.form.get("group-key"))
        page.save()
        return _page_view_access_response(page)

    return _page_view_access_response(page)
