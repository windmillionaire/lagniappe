from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities.page import PageData
    from lagniappe.core.entities.entity import Entity
    from werkzeug.datastructures import MultiDict
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import Response, abort, g, request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.base_property import Property
from lagniappe.core.entities import Entities
from lagniappe.core.definitions.asset import ImageAsset
from lagniappe.core.definitions import (
    AI,
    FileConsumerLimitError,
)
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.site import public_pages as public_page_service
from lagniappe.core.tools.auth.references import (
    SubmittedReferenceResolver,
    UNAVAILABLE_REFERENCE_ERROR,
)
from lagniappe.core.tools.polling.forms import is_form_field, offline_replay_conflicts
from lagniappe.core.tools.forms import review as form_review
from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.web.auth import (
    authenticated_user,
    abort_public_user_action,
    logged_in,
    permission,
    require_ai_access,
)
from lagniappe.web.ai_display import auto_execute_site_enabled
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web import deferred_autofill
from lagniappe.web import experiments

from . import pages


def _is_public_users_own_page(page):
    return bool(
        getattr(current_user, "is_public", False)
        and getattr(getattr(current_user, "page", None), "key", None) == page.key
    )


def _load_page_settings_relations(page, *, restrictions=False):
    """Attach the group relations rendered by Page settings at the route boundary."""
    is_own_page = getattr(getattr(current_user, "page", None), "key", None) == page.key
    entities = [page.form] if restrictions and not is_own_page and page.form else []
    if page.user and current_user.is_admin and not is_own_page:
        entities.append(page.user)
    if entities:
        Entities.fetch(*entities, request=Fetch.direct())
    return page


def _page_view_fingerprint(page, user):
    """Empty-notes discovery changes initial HTML, not the Page's content revision."""
    base = f"{deferred_autofill.form_fingerprint(page, user)}:{int(page.has_notes)}"
    if getattr(page, "user", None):
        return f"{base}:{int(auto_execute_site_enabled())}"
    return base


def _user_settings_fingerprint(page, user):
    return f"{page.fingerprint}:{int(auto_execute_site_enabled())}"


@pages.route("<key>", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW, fingerprint=_page_view_fingerprint)
def view(key: str, **kwargs: Unpack[EntityContext[models.Page]]) -> ResponseReturnValue:
    page = _load_page_settings_relations(
        kwargs["entity"],
        restrictions=Resource.USER.allowed(Action.PERMISSIONS),
    )

    return responses.page(page)


@pages.route("<key>/info/replace", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW, fingerprint=deferred_autofill.form_fingerprint)
def info(key: str, **kwargs: Unpack[EntityContext[models.Page]]) -> ResponseReturnValue:
    page = kwargs["entity"]
    return responses.page_info(page)


@pages.route("<key>/user-settings/replace", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW, fingerprint=_user_settings_fingerprint)
def user_settings(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]
    is_own_page = getattr(getattr(current_user, "page", None), "key", None) == page.key
    if not page.user or not (is_own_page or Resource.USER.allowed(Action.PERMISSIONS)):
        abort(403)
    _load_page_settings_relations(
        page, restrictions=Resource.USER.allowed(Action.PERMISSIONS)
    )
    return responses.user_settings(page)


@pages.route("<key>/permissions/replace", methods=["GET"])
@permission(Resource.PAGE, Action.PERMISSIONS)
def permissions(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = _load_page_settings_relations(kwargs["entity"], restrictions=True)
    return responses.page_permissions(page)


@pages.route("<key>/document-settings/replace", methods=["GET"])
@permission(Resource.PAGE, Action.PUBLISH)
def document_settings(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    return responses.page_document_settings(kwargs["entity"])


@pages.route("<key>/tasks", methods=["GET"])
@permission(
    Resource.PAGE, Action.VIEW,
    fingerprint=deferred_autofill.page_tasks_fingerprint,
    context_keys=experiments.task_list_context_keys,
)
def tasks(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]
    if not g.get("task_list_prepared"):
        # Range/login invalidation may require a body after a matching ETag.
        deferred_autofill.prepare_form_states(page.tasks, authenticated_user())
    response = responses.page_tasks(page)
    deferred_autofill.finish_task_list_validation(page)
    return response


@pages.route("<key>/files", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def files(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]
    if _is_public_users_own_page(page):
        abort_public_user_action()

    return responses.page_files(page)


def _page_data(
    form: MultiDict[str, str], page: models.Page | None = None, category: models.Category | None = None,
) -> PageData:
    """Resolve form data into a dict suitable for Page.create() or Page.update()."""
    entities: list[Entity | str | None] = [page, category]
    # A user-Page save also persists its owning User, whose requirements use
    # groups, while Page.update() registers forms with the reserved Users model.
    # Make both entities direct roots without widening every Page update to a
    # nested fetch.
    if page and isinstance(page.model, Entities.USERS):
        entities.extend((page.model, page.user))
    for e in ["model", "group", "reassign-page"]:
        entities.extend(form.getlist(e))
    loaded = {
        e.urlsafe_key: e for e in Entities.fetch(*entities, request=Fetch.direct())
    }

    category_keys = form.getlist("category")
    form_key = form.get("form")
    resolver = SubmittedReferenceResolver(
        authenticated_user(),
        *category_keys,
        form_key,
    )
    current_categories = list(page.categories) if page else []
    categories = resolver.many(
        category_keys,
        expected=Entities.CATEGORY,
        action=Action.VIEW,
        existing=current_categories,
    )
    selected_category_keys = {selected.key for selected in categories}
    categories.extend(
        current
        for current in current_categories
        if current.key not in selected_category_keys
        and not current.allowed(Action.VIEW, user=current_user)
    )
    current_form = page.form if page else None
    selected_form = resolver.one(
        form_key,
        expected=Entities.FORM,
        action=Action.VIEW,
        existing=current_form,
        predicate=lambda candidate: candidate.form_type == "page",
    )
    if not form_key and current_form and not current_form.allowed(
        Action.VIEW, user=current_user
    ):
        selected_form = current_form

    model = loaded.get(category.urlsafe_key) if category else None
    page_data: PageData = {
        "name": form.get("name") if "name" in form else (page.name if page else None),
        "description": (
            form.get("description")
            if "description" in form
            else (page.description if page else None)
        ),
        "email": form.get("email"),
        "categories": categories,
        "form": selected_form,
        "model": model if isinstance(model, Entities.CATEGORY) else None,
        "groups": [group for k in form.getlist("group") if isinstance(group := loaded.get(k), Entities.USER_GROUP)],
    }
    if "reassign-page" in form:
        replacement = loaded.get(form.get("reassign-page") or "")
        page_data["reassign-page"] = replacement if isinstance(replacement, Entities.PAGE) else None
    if "remove-user" in form:
        page_data["remove-user"] = form.get("remove-user") == "true"
    if "ai_access" in form:
        page_data["ai_access"] = form.get("ai_access")
    if "notification_email_mode" in form:
        page_data["notification_email_mode"] = form.get("notification_email_mode")
    if "allow_site_email" in form:
        page_data["allow_site_email"] = form.get("allow_site_email") == "true"
    if "allow_auto_execute" in form:
        page_data["allow_auto_execute"] = form.get("allow_auto_execute") == "true"
    for toggle in ("allow_messages_and_mentions", "allow_task_assignments"):
        if toggle in form:
            page_data[toggle] = form.get(toggle) == "true"

    return page_data


def _page_form_submission_response(page):
    return responses.form_submission(page)


# @scaffolding testing/resources/page.py::Page.submit_and_verify_submission
def _apply_page_submission(page, form):
    page.form_submission(form, actor=current_user)


def _apply_page_metadata_update(page, page_data, user=None):
    page.update(page_data)
    if page.user:
        page.update_user(page_data, user=user)


def _apply_user_settings_update(page, page_data, user=None):
    if not page.user:
        return
    page.name = page_data.get("name")
    page.update_user(page_data, user=user)


def _offline_update_notification(page):
    notification = Entities.NOTIFICATION.create(
        {
            "parent": authenticated_user(),
            "target": page,
            "body": "Offline page update synced.",
        }
    )
    Entities.save(notification)
    return notification


def _is_offline_replay(form):
    return str(form.get("offline", "")).lower() == "true"


@pages.route("<key>/update", methods=["PUT", "GET"])
@permission(Resource.PAGE, Action.VIEW, fingerprint=deferred_autofill.form_fingerprint)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    if request.method == "GET":
        if request.values.get("form"):
            try:
                page.form = SubmittedReferenceResolver(
                    authenticated_user(),
                    request.values.get("form"),
                ).one(
                    request.values.get("form"),
                    expected=Entities.FORM,
                    action=Action.VIEW,
                    predicate=lambda candidate: candidate.form_type == "page",
                    required=True,
                )
            except exceptions.ValidationError:
                abort(404)
        return _page_form_submission_response(page)
    elif not page.allowed(Action.EDIT):
        abort(403)

    if offline_replay_conflicts(page, request.form):
        return responses.page_info(page, conflict=True)

    role = request.form.get("role")
    if role != "user-settings":
        if not form_review.stage_submission_guard(page, request.form):
            return deferred_autofill.conflict_response(page)
        locked = deferred_autofill.locked_response(page, request.form)
        if locked:
            return locked

    if role == "autofill-submit" and request.files.get("autofill-file"):
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    image = page.get_asset("image")
    old_image = image.path if image else None

    try:
        page_data = _page_data(request.form, page=page)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    if role == "user-settings":
        if request.form.get("restrictions") == "true" and not page.allowed(
            Action.PERMISSIONS
        ):
            abort(403)
        try:
            if request.form.get("restrictions") == "true":
                _apply_page_access_restrictions(page, request.form)
            _apply_user_settings_update(page, page_data, user=current_user)
        except PermissionError:
            abort(403)
        except (exceptions.ValidationError, ValueError) as error:
            return responses.error(str(error))
        page.save()
        if not page.user:
            return responses.json_response({"reload": True})
        _load_page_settings_relations(
            page, restrictions=Resource.USER.allowed(Action.PERMISSIONS)
        )
        return responses.user_settings(page)

    if role == "explain" or request.form.get("explain"):
        return responses.error("Initial Prompt is no longer available.")

    if role == "autofill-submit":
        require_ai_access(AI.CREATE)
        if getattr(page_data.get("form"), "key", None) != getattr(page.form, "key", None):
            return responses.error("Save the form selection before running autofill.")
        draft = None
        if page.form:
            try:
                draft = page.preview_form_submission(request, actor=current_user)
            except exceptions.ValidationError as error:
                return responses.error(str(error))
        target_context: dict[str, object] = {
            "name": page_data.get("name"),
            "description": page_data.get("description"),
        }
        return responses.entity_response(
            deferred_autofill.start_deferred_autofill(
                page,
                authenticated_user(),
                request.form,
                multipart_file=bool(request.files.get("autofill-file")),
                submission=draft["values"] if draft else None,
                prompt_submission=draft["ai_values"] if draft else None,
                target_context=target_context,
            ),
            page,
        )
    else:
        _apply_page_metadata_update(page, page_data, user=current_user)
        try:
            _apply_page_submission(page, request)
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    staged_file = None
    try:
        staged_file, staged_cleanup = deferred_autofill.staged_upload_for_update(
            page, authenticated_user(), request.form,
        )
        form_review.acknowledge_reviews(page, authenticated_user(), request.form.getlist("reviewed-operation"))
        if staged_file:
            Entities.save(staged_file, page)
        else:
            page.save()
    except exceptions.MutationConflict:
        if staged_file:
            storage_assets.cleanup_rejected_attempt(staged_file)
        return deferred_autofill.conflict_response(page)
    except (exceptions.ValidationError, storage_assets.DirectUploadError, FileConsumerLimitError) as error:
        if staged_file:
            storage_assets.cleanup_rejected_attempt(staged_file)
        return responses.error(str(error))
    deferred_autofill.cleanup_staged_uploads(staged_cleanup)
    if _is_offline_replay(request.form):
        _offline_update_notification(page)
        return responses.entity_response(
            responses.json_response({"ok": True}),
            page,
        )

    image = page.get_asset("image")
    new_image = image.path if image else None

    if old_image != new_image:
        return responses.json_response({"reload": True})

    return responses.page_info(page)


@pages.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def update_direct(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    locked = deferred_autofill.locked_response(kwargs["entity"], upload_data)
    if locked:
        return locked
    return direct_uploads.direct_upload_response()


@pages.route("<key>/patch", methods=["PATCH"])
@permission(Resource.PAGE, Action.EDIT)
def patch(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    patch_data = request.json
    schema_id = patch_data["schema_id"]
    value = patch_data["value"]
    column = patch_data.get("column")

    if is_form_field(page, schema_id):
        locked = deferred_autofill.locked_response(page)
        if locked:
            return locked
        if str(patch_data.get("form_generation", "0")) != str(page.generation):
            return responses.error("The form fields changed. Reload this table before editing the value.")

    if schema_id in page.properties:
        field = page.properties[schema_id]
        if not isinstance(field, Property) or not field.editable:
            return responses.error("Field cannot be edited")
        if schema_id == "name":
            cleaned_name = str(value or "").strip()
            if not cleaned_name:
                return responses.error("Page name cannot be empty.")
            value = cleaned_name
        if schema_id == "name" and page.user:
            try:
                page.update_user({"name": value}, user=current_user)
            except PermissionError:
                abort(403)
        field.value = value
    else:
        field = page.properties.submission.fields.get(schema_id)
        if not field or not field.editable:
            return responses.error("Field cannot be edited")
        try:
            page.validate_browser_submission_references(
                {schema_id: value},
                actor=current_user,
                normalized=True,
            )
        except exceptions.ValidationError as error:
            return responses.error(str(error))
        field = page.properties.submission.patch(schema_id, value)
        page.save_submission()

    page.save()

    return responses.entity_response(
        responses.cell(field, page, column=column),
        page,
        *page.page_list_owners,
    )


@pages.route("<key>/create", methods=["POST"])
@permission(Resource.CATEGORY, Action.EDIT)
def create(
    key: str, **kwargs: Unpack[EntityContext[models.Category]]
) -> ResponseReturnValue:
    """Create a page within a category. Key is the category key, not a page key."""
    category = kwargs["entity"]

    if not (request.form.get("name") or "").strip():
        return responses.error("Name this page before creating it.")

    try:
        create_data = _page_data(request.form, category=category)
        page = Entities.PAGE.create(create_data)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    role = request.form.get("role")

    if role == "autofill-submit" and request.files.get("autofill-file"):
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    if role == "explain" or request.form.get("explain"):
        return responses.error("Initial Prompt is no longer available.")

    if role == "autofill-submit":
        require_ai_access(AI.CREATE)
        if page.form:
            try:
                _apply_page_submission(page, request)
            except exceptions.ValidationError as error:
                return responses.error(str(error))
        page.save()
        deferred_response = deferred_autofill.start_deferred_autofill(
            page,
            authenticated_user(),
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


@pages.route("<key>/create/direct-upload", methods=["POST"])
@permission(Resource.CATEGORY, Action.EDIT)
def create_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    return direct_uploads.direct_upload_response()


@pages.route("create", methods=["POST"])
@logged_in
def create_from_home() -> ResponseReturnValue:
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

    try:
        create_data = _page_data(request.form, category=category)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    create_data["model"] = category
    create_data["categories"] = [
        c for c in create_data.get("categories", []) if c and c.key != category.key
    ]
    if not create_data.get("form") and category.form:
        if (
            category.form.form_type != "page"
            or not category.form.allowed(Action.VIEW, user=current_user)
        ):
            return responses.error(UNAVAILABLE_REFERENCE_ERROR)
        create_data["form"] = category.form

    page = Entities.PAGE.create(create_data)
    page.save()

    return responses.new_page(page)


@pages.route("<key>/delete", methods=["DELETE"])
@permission(Resource.PAGE, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
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


@pages.route("<key>/visibility", methods=["PUT"])
@permission(Resource.PAGE, Action.PUBLISH)
def visibility(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    page.is_public = request.form.get("visibility") == "public"
    if request.form.get("public-settings-present") == "true":
        preview = request.form.get("preview-image-asset") or None
        directory_category = request.form.get("directory-category") or None
        valid_images = {
            image.name for image in public_page_service.document_images(page)
        }
        if preview and preview not in valid_images:
            return responses.error("Preview image must be used in this page's document.")
        valid_categories = {category.urlsafe_key for category in page.categories}
        if directory_category and directory_category not in valid_categories:
            return responses.error(
                "Directory category must be attached to this page."
            )
        try:
            page.public_settings = {
                "allow_indexing": request.form.get("allow-indexing") == "true",
                "title": request.form.get("public-title"),
                "description": request.form.get("public-description"),
                "preview_image_asset": preview,
                "directory_category": directory_category,
                "directory_order": request.form.get("directory-order"),
            }
        except ValidationError as error:
            return responses.error(error)
    if page.is_public:
        _ = page.public_id
    Entities.save(page)

    return responses.page_document_settings(page)


@pages.route("public/<public_id>", methods=["GET"])
def public(public_id: str) -> ResponseReturnValue:
    public_pages = Entities.fetch(
        *database_get.public_pages(public_id), request=Fetch.root()
    )
    page = next((page for page in public_pages if isinstance(page, Entities.PAGE) and page.is_public), None)

    if not page:
        abort(404)

    return responses.public_document(page)


@pages.route("public/<public_id>/images/<asset_name>", methods=["GET", "HEAD"])
def public_image(public_id: str, asset_name: str) -> ResponseReturnValue:
    candidates = Entities.fetch(
        *database_get.public_pages(public_id),
        request=Fetch.root(),
    )
    page = next((candidate for candidate in candidates if isinstance(candidate, Entities.PAGE) and candidate.is_public), None)
    if not page:
        abort(404)

    asset_key = asset_name.split(".", 1)[0]
    referenced = {
        image.name: image for image in public_page_service.document_images(page)
    }
    if asset_key not in referenced:
        abort(404)
    asset = page.get_asset(asset_key)
    if not isinstance(asset, ImageAsset):
        abort(404)

    g.NO_CACHE = True
    if request.method == "HEAD":
        response = Response("", mimetype=asset.content_type)
        if asset.size is not None:
            response.headers["Content-Length"] = str(asset.size)
        return response
    content = asset.get()
    if content is None:
        abort(404)
    return Response(content, mimetype=asset.content_type)


def _apply_page_access_restrictions(page, form):
    admin_only = form.get("admin") in {"on", "true"}
    keys = [] if admin_only else form.getlist("group-key")
    groups = SubmittedReferenceResolver(authenticated_user(), *keys).many(
        keys, expected=Entities.USER_GROUP, action=Action.VIEW
    )
    page.groups = groups
    page.properties.restricted_to.materialize(admin_only=admin_only)


@pages.route("<key>/view-access", methods=["GET", "PUT"])
@permission(Resource.PAGE, Action.PERMISSIONS)
def view_access(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    page = kwargs["entity"]

    if request.method == "PUT":
        try:
            _apply_page_access_restrictions(page, request.form)
            page.save()
        except (exceptions.ValidationError, ValueError) as error:
            return responses.error(str(error))

    _load_page_settings_relations(page, restrictions=True)
    return responses.page_permissions(page)
