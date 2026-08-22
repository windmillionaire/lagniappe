from flask import url_for

from ..definitions import Action, Fetch, MutationIntent, NotificationEmailMode
from ..entities import Entities
from ..mixins import AssetMixin, SubmitterMixin
from ..properties import (
    common_assets,
    common_entity,
    common_related,
    form_submission,
    page_assets,
    page_related,
)
from ..tools import database
from ..tools.auth.context import current_context_user
from ..tools.tasks.ordering import sort_tasks
from .entity import Entity


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_to_cache_public_user
# @features page, cache
# @dimensions public-user
class Page(AssetMixin, SubmitterMixin, Entity):
    entity_kind = "page"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tasks = None
        self._completed = None

    @property
    def exclude_from_index(self):
        exclude = {
            "submission",
            "description",
            "assets",
            "schema_version",
            "deferred_job",
        }
        return frozenset(exclude)

    @property
    def sync_ids(self):
        return {
            "document": {
                "id": self.properties.document.sync_id,
                "fingerprint": self.properties.document.fingerprint,
            },
        }

    def state(self, sync_id):
        if not self.allowed(Action.VIEW):
            return {}
        elif self._state is not None:
            return self._state

        self._state = {"timestamp": self.modified.timestamp()}
        self._state.update(
            {
                "ydoc": self.properties.document.ydoc,
                "fingerprint": self.properties.document.fingerprint,
            }
        )
        if not self._state.get("ydoc") and self.properties.document.html:
            self._state["markup"] = self.properties.document.html
        return self._state

    # @testable true
    # @tests tests_unit/test_009b_user_permissions.py::test_user_page_permissions_follow_users_only_or_attached_categories
    # @tests tests_unit/test_009f_page_view_access.py::test_user_page_uses_users_permissions_not_models_permissions
    # @features permissions users
    # @dimensions user-page models-scope users-scope
    @property
    def required(self):
        required = []
        if self.categories:
            required.append("models")

        user = getattr(self, "user")
        if user:
            required.extend(user.requires)

        required.append(self.hash)
        if self.categories:
            required.extend([c.hash for c in self.categories])
        return required

    @property
    def url(self):
        return url_for("pages.view", key=self.urlsafe_key)

    @property
    def to_cache(self):
        if self.user and self.user.is_public:
            return {}
        return super().to_cache

    # @testable true
    # @tests tests_unit/test_008_page_properties.py::test_page_details
    # @tests tests_unit/test_008_page_properties.py::test_page_attributes
    # @features page
    # @dimensions details, parent, kind, inheritance
    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "form": common_related.AttachedForm,
                "description": common_entity.Description,
                "model": page_related.PageModelCategory,
                "categories": page_related.PageCategories,
                "groups": common_related.Groups,
                "user": page_related.PageUser,
                "files": page_related.PageFiles,
                "document": common_assets.Document,
                "attributes": common_entity.Attributes,
                "image": page_assets.Image,
                "is_public": common_entity.IsPublic,
                "public_id": common_entity.PublicID,
                "submission": form_submission.FormSubmission,
                "deferred_job": common_entity.DeferredJobReference,
                "restricted_to": common_entity.RestrictedTo,
            }
        )
        return properties

    # @testable true
    # @tests tests_unit/test_009f_page_view_access.py::test_page_tasks_filtered_by_task_allowed
    # @features page, task, permissions
    # @dimensions task-visibility, restricted-access
    def _load_tasks(self):
        results = database.get.page_tasks(self)
        entities = {
            e.key: e for e in Entities.fetch(*results, self, request=Fetch.direct())
        }

        tasks = [
            e
            for e in entities.values()
            if isinstance(e, Entities.TASK) and e.allowed(Action.VIEW)
        ]

        self._completed = [t for t in tasks if t.completed]
        self._completed.sort(key=lambda x: x.modified, reverse=True)
        self._tasks = sort_tasks([t for t in tasks if not t.completed])

    @property
    def tasks(self):
        if self._tasks is None:
            self._load_tasks()

        return self._tasks

    @property
    def completed(self):
        if self._completed is None:
            self._load_tasks()

        return self._completed

    # @testable true
    # @tests tests_unit/test_009f_page_view_access.py::test_page_restricted_access_group_match
    # @tests tests_unit/test_009b_user_permissions.py::test_privileged_user_rows_are_owner_managed
    # @tests tests_unit/test_009f_page_view_access.py::test_page_view_does_not_require_loaded_owner
    # @pairs page:restricted-access page:group-match
    # @pairs admin:privileged-account admin:page owner:owner-only
    # @pair page:view-owner-short-circuit
    def allowed(self, action, user=None):
        user = current_context_user(user)
        if self.restricted_access(user):
            return False
        if action.value > Action.VIEW.value:
            target_user = self.user
            if target_user and target_user.is_admin and user and not user.is_owner:
                return False
        return super().allowed(action, user=user)

    # @testable true
    # @tests tests_unit/test_009f_page_view_access.py::test_page_view_access_owner_stored_only
    # @tests tests_unit/test_009f_page_view_access.py::test_page_view_access_returns_attached_groups
    # @tests tests_unit/test_009f_page_view_access.py::test_page_view_access_from_group_views
    # @tests tests_unit/test_009f_page_view_access.py::test_user_page_uses_users_permissions_not_models_permissions
    # @features page
    # @dimensions view-access, owner, attached-groups, group-views, db-load, user-page
    @property
    def view_access(self):
        if "owner" in self.properties.restricted_to.stored:
            return []
        elif self.groups:
            return self.groups
        else:
            return Entities.fetch(
                *database.get.group_view_access(self.required),
                request=Fetch.direct(),
            )

    @classmethod
    def create(cls, data):
        new_page = cls()
        new_page.kind = cls.entity_kind

        new_page.update(data)

        return new_page

    # @testable true
    # @tests tests_unit/test_008_page_properties.py::test_page_update_tracks_old_and_current_category_owners_for_save
    # @features page, category
    # @dimensions save-relations
    @property
    def page_list_owners(self):
        owners = [self.user, self.model, *self.categories]
        unique = []
        seen = set()
        for owner in owners:
            key = getattr(owner, "key", None)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(owner)
        return unique

    # @testable true
    # @tests tests_unit/test_008_page_properties.py::test_page_update_registers_form_with_model_category_for_filters
    # @tests tests_unit/test_008_page_properties.py::test_page_update_tracks_old_and_current_category_owners_for_save
    # @tests tests_unit/test_008_page_properties.py::test_page_update_keeps_current_user_before_page_without_dependency_cycle
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_select_includes_form_from_created_page
    # @features page, category, filters
    # @dimensions form-registration, related-forms, save-relations
    def update(self, data):
        previous_owners = self.page_list_owners

        if data.get("user"):
            self.user = data.get("user")

        self.categories = data.get("categories", [])
        if data.get("model"):
            self.model = data.get("model")
        self._ensure_category()

        self.form = data.get("form")
        if self.form:
            category_keys = set()
            for category in [self.model, *self.categories]:
                key = getattr(category, "key", None)
                if not key or key in category_keys:
                    continue
                category_keys.add(key)
                if category.properties.forms.add(self.form):
                    self.add_mutation_intents(
                        MutationIntent.patch(
                            category,
                            "forms",
                            reason="page-category-form-registration",
                        ),
                        MutationIntent.touch(
                            self.form,
                            reason="page-category-form-registration",
                        ),
                    )

        self.name = data.get("name")
        self.description = data.get("description")
        self.attributes = data.get("attributes")

        if data.get("submission"):
            self.properties.submission.value = data.get("submission")

        current_owner_keys = {owner.key for owner in self.page_list_owners}
        self.add_mutation_intents(
            *[
                MutationIntent.touch(owner, reason="page-previous-list-owner")
                for owner in previous_owners
                if owner.key not in current_owner_keys
            ]
        )

    # @testable true
    # @tests tests_unit/test_008_page_properties.py::test_page_update_defaults_empty_category_state_to_uncategorized
    # @features page
    # @dimensions default-category
    def _ensure_category(self):
        if not self.model and not self.categories:
            self.model = Entities.CATEGORY.get_uncategorized_pages()

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_page_update_user_authorization_rules
    # @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_edit_user_settings_on_other_user_page
    # @tests tests_e2e/008_users/test_008c_user_settings.py::test_owner_can_reassign_and_remove_user_from_page
    # @pairs user-settings:email-edit user-settings:ai-access user-settings:owner-own-page
    # @pairs user-settings:owner-other-page user-settings:page-preservation
    # @pairs user-settings:page-reassign user-settings:page-remove
    # @pairs notification-email:preference notification-email:user-only
    # @pair public-users:email-consent
    # @pair cache:invalidation-acknowledgement
    # @pair permissions:permission-recalc
    def update_user(self, data, user=None):
        user = current_context_user(user)
        target_user = self.user
        is_own_page = bool(
            user
            and user.is_authenticated
            and getattr(getattr(user, "page", None), "key", None) == self.key
        )
        is_owner_viewer = bool(user and user.is_owner)
        is_admin_viewer = bool(user and user.is_admin)
        target_is_privileged = bool(target_user and target_user.is_admin)
        can_manage_target = bool(
            is_admin_viewer and (is_owner_viewer or not target_is_privileged)
        )

        if target_is_privileged and not is_owner_viewer:
            submitted_name = data.get("name")
            if submitted_name is not None and submitted_name != target_user.name:
                raise PermissionError("Only the Owner can edit an Administrator.")
            protected_fields = {
                "ai_access",
                "groups",
                "remove-user",
                "reassign-page",
            }
            if protected_fields.intersection(data):
                raise PermissionError("Only the Owner can edit an Administrator.")
            submitted_email = data.get("email")
            if submitted_email is not None and submitted_email != target_user.email:
                raise PermissionError("Only the Owner can edit an Administrator.")

        ai_access = None
        if "ai_access" in data:
            if not can_manage_target:
                raise PermissionError(
                    "Only the owner or an authorized Administrator can change AI access."
                )
            from ..definitions import AI

            ai_access = AI.name_for(data.get("ai_access"))

        notification_email_mode = None
        if "notification_email_mode" in data:
            if not is_own_page or target_user.is_public:
                raise PermissionError(
                    "Only a managed user can change their own notification email "
                    "preference."
                )
            notification_email_mode = NotificationEmailMode.name_for(
                data.get("notification_email_mode")
            )

        allow_site_email = None
        if "allow_site_email" in data:
            if not is_own_page or not target_user.is_public:
                raise PermissionError(
                    "Only a public user can change their own site email preference."
                )
            allow_site_email = bool(data.get("allow_site_email"))

        if not target_is_privileged or is_owner_viewer:
            target_user.name = data.get("name")
        if ai_access is not None:
            target_user.ai_access = ai_access
        if notification_email_mode is not None:
            target_user.notification_email_mode = notification_email_mode
        if allow_site_email is not None:
            target_user.allow_site_email = allow_site_email
        inbound_toggles = {
            key: data[key]
            for key in ("allow_messages_and_mentions", "allow_task_assignments")
            if key in data
        }
        if inbound_toggles:
            if not (
                is_owner_viewer and is_own_page and target_user and target_user.is_owner
            ):
                raise PermissionError(
                    "Only the owner can change their inbound collaboration settings."
                )
            for key, value in inbound_toggles.items():
                setattr(target_user, key, value)
        self.add_mutation_intents(
            MutationIntent.standard(target_user, reason="page-user-update")
        )
        if not can_manage_target or is_own_page:
            return

        if "email" in data:
            if target_user.is_owner:
                raise PermissionError("The primary Owner email cannot be changed.")
            target_user.email = data.get("email")
        if "groups" in data:
            target_user.groups = data.get("groups", [])
        if data.get("remove-user"):
            target_user.page = None
        elif data.get("reassign-page") and data.get("reassign-page").key != self.key:
            target_user.page = data.get("reassign-page")

        if target_user.page.key != self.key:
            previous_users_category = Entities.USERS.get()
            self.user = None
            self.add_mutation_intents(
                MutationIntent.touch(
                    previous_users_category,
                    reason="page-previous-users-owner",
                ),
                MutationIntent.delete_from_search(
                    "user",
                    self,
                    reason="page-user-search-removal",
                ),
            )
            self.properties.categories.remove(previous_users_category)
            target_user.properties.permissions.create()

    # @testable true
    # @tests tests_unit/test_009a_user.py::test_user_page_default_form_submission_keeps_email_on_user
    # @features user-settings
    # @dimensions default-form email-canonical submission-preservation
    def save_submission(self):
        super().save_submission()
        self._sync_default_user_form_email()

    # @testable false
    # @covered-by lagniappe/core/entities/page.py::Page.save_submission
    # @reason helper identifies the reserved default user form for the user-email mirror
    def _uses_default_user_form(self):
        if not self.user or not isinstance(self.model, Entities.USERS) or not self.form:
            return False
        if not getattr(self.form, "reserved", False):
            return False

        fields = {field.get("id"): field for field in self.form.schema or []}
        return (
            set(fields) == {"name", "email"}
            and fields["name"].get("type") == "input"
            and fields["name"].get("input") == "text"
            and fields["email"].get("type") == "input"
            and fields["email"].get("input") == "email"
        )

    # @testable false
    # @covered-by lagniappe/core/entities/page.py::Page.save_submission
    # @reason helper keeps default user-form email data aligned with the user entity
    def _sync_default_user_form_email(self):
        if not self._uses_default_user_form():
            return

        email_field = self.properties.submission.fields.get("email")
        if not email_field:
            return

        user_email = self.user.email
        submitted_email = email_field.value

        if not user_email and submitted_email:
            self.user.email = submitted_email
            user_email = submitted_email

        if user_email and submitted_email != user_email:
            email_field.value = user_email
            self.properties.submission.value = self.properties.submission.db_value
