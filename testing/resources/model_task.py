"""
Helper for the ModelTask entity.

Model tasks are workflow stages within a project that define a type of task
to be completed. They can have an attached form that provides fields for
tasks of this type.

Related Files:
    Application:
        - lagniappe/core/entities/model_task.py: ModelTask entity
        - lagniappe/web/routes/projects/tasks.py: Model task routes
        - lagniappe/web/templates/projects/model_tasks.html: Template
        - src/script/widgets/project.mjs: CreateModelTask, ModelTaskInfo widgets

    Test Framework:
        - testing/definitions/model_tasks.py: ModelTasks enum
        - testing/definitions/model_task_definitions.py: ModelTaskDefinition dataclass
"""

from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from ..elements import Buttons
from .core import SiteResource


class ModelTask(SiteResource):
    """
    Resource for ModelTask entity and interactions.

    Provides:
        - create(): Creates model task programmatically
        - open_info(): Opens the ModelInfo edit widget
        - info_form: Property to access the ModelInfo form element

    Selectors (for model task element):
        HEADER: Clickable header that toggles ModelInfo (lp-show)
        INFO_FORM: The edit form (data-widget='ModelInfo')
        TITLE: Title text span (data-role='title')
    """

    # --- Model Task Element Selectors ---
    HEADER = "[lp-show$='ModelTaskInfo']"
    INFO_FORM = "[data-widget='ModelTaskInfo']"
    TITLE = "span[data-role='title']"

    def create(self):
        """
        Create model task entity programmatically.

        Uses the same Entities.MODEL_TASK.create() path as the route handler
        in lagniappe/web/routes/projects/tasks.py.
        """
        assert self.definition, "Definition is required to create a model task"
        assert self.definition.project, "Project is required to create a model task"

        project = self.definition.project.get(self.user)
        form_resource = (
            self.definition.form.get(self.user) if self.definition.form else None
        )

        data = {
            "name": self.definition.name,
            "form": form_resource.entity if form_resource else None,
        }

        entity = Entities.MODEL_TASK.create(project.entity, data)
        entity.save()

        self.key = entity.urlsafe_key
        self.entity = entity

        return self

    @property
    def project(self):
        return self.definition.project.get(self.user)

    @property
    def element(self):
        """Get the model task list item element."""
        assert self.key, "Model task key is required to get the element"
        return self.user.locate(f"[data-key='{self.key}']")

    @property
    def info_form(self):
        """
        Get the ModelInfo form element.

        Returns:
            Locator: The ModelInfo form within this model task element
        """
        return self.element.locator(self.INFO_FORM)

    def open_info(self):
        """
        Open the ModelInfo widget by clicking the header.

        Clicks the header toggle to show the edit form. Verifies
        the form becomes visible after clicking.

        Returns:
            Locator: The visible ModelInfo form element
        """
        header = self.element.locator(self.HEADER)
        expect(header).to_be_visible()
        if not self.info_form.is_visible():
            header.click()

        expect(self.info_form).to_be_visible()
        return self.info_form

    def close_info(self):
        """
        Close the ModelInfo widget by clicking the close button.

        Clicks the LP_CLOSE button within the info form to hide it.
        """
        close_button = self.element.locator(Buttons.LP_CLOSE)
        expect(close_button).to_be_visible()
        close_button.click()

        expect(self.info_form).to_be_hidden()
