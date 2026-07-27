"""Browser resource for AI report detail pages."""

from playwright.sync_api import expect

from .core import SiteResource


class Report(SiteResource):
    """Navigate and interact with a persisted AI report."""

    _initialize = True

    VIEW = "[lp-view][data-kind='report']"
    TITLE = "[data-nav='view'] [data-role='title']"
    STATUS = "[data-role='report-status']"
    ANSWER = "[data-role='ask-answer']"
    ANSWER_HTML = "[data-role='ask-answer-html']"
    ANSWER_SUMMARY = "[data-role='ask-answer-summary']"
    PROPOSAL_ACTION = "[data-role='proposal-action']"
    RESULT = "[data-role='report-result']"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entity = kwargs.get("entity")

    @classmethod
    def for_entity(cls, user, entity):
        return cls(user=user, entity=entity)

    @property
    def url_suffix(self):
        return f"tools/reports/{self.key}"

    def initialize_view(self):
        expect(self.user.locate(self.VIEW)).to_have_attribute("initialized", "")

    @property
    def title_element(self):
        return self.user.locate(self.TITLE)

    @property
    def answer(self):
        return self.user.locate(self.ANSWER)

    @property
    def proposal_actions(self):
        return self.user.locate(self.PROPOSAL_ACTION)

    @property
    def result(self):
        return self.user.locate(self.RESULT)

    @property
    def execute_button(self):
        return self.user.page.get_by_role("button", name="Execute Proposal")

    def execute(self, timeout=30000):
        with self.user.page.expect_navigation(timeout=timeout):
            self.execute_button.click()
        self.initialize_view()
        return self

    def expand_json(self, label):
        accordion = self.user.locate("[data-role='accordion']").filter(has_text=label)
        panel = accordion.locator("[data-role='accordion-panel']")
        expect(panel).not_to_be_visible()
        accordion.locator("[lp-expand]").click()
        expect(panel).to_be_visible()
        return panel
