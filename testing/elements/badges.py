from enum import Enum

from playwright.sync_api import expect

"""
Entity badges on task rows (task_details in pages/tasks.html).

Badges render as ``div`` elements with ``data-kind`` matching the entity kind
(project, model, user, etc.) and visible name text from ``format_name``.

Related:
    - lagniappe/web/templates/pages/tasks.html: task_details macro
    - lagniappe/web/templates/badge.html: entity_badge macro
"""


class Badges(Enum):
    """Assertions for entity badges attached to a task row or container."""

    PROJECT = 'div[data-kind="project"]'
    MODEL_TASK = 'div[data-kind="model"]'
    USER = 'div[data-kind="user"]'
    TASK = 'div[data-kind="task"]'

    def visible(self, element, resource):
        """
        Assert a badge for ``resource`` (project, model task, user, …) is visible.

        Args:
            container: Locator scoped to the task row (e.g. the ``li`` for the task).
            resource: Test resource with ``entity.kind`` and ``definition.name``.
        """
        badge = element.locator(self.value).filter(has_text=resource.definition.name)
        expect(badge).to_be_visible()
        return badge

    def contains(self, element, text):
        badge = element.locator(self.value).filter(has_text=text)
        expect(badge).to_be_visible()
        return badge
