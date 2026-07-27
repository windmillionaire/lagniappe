from dataclasses import dataclass, field


@dataclass
class ProjectDefinition:
    name: str = ""
    description: str = ""
    description_for_ai: str = ""
    attributes: list = field(default_factory=lambda: ["tasks", "document"])

    @property
    def defaults(self):
        return ["tasks", "document"]


create_project = ProjectDefinition(
    name="Test Project",
    description="A standard test project created from home page.",
)

without_tasks = ProjectDefinition(
    name="Test Project Without Tasks",
    description="A test project created from home page without tasks.",
    attributes=["document"],
)

without_document = ProjectDefinition(
    name="Test Project Without Documents",
    description="A test project created from home page without documents.",
    attributes=["tasks"],
)

delete_project = ProjectDefinition(
    name="Deletable Project",
    description="A project created for testing deletion.",
)

ai_generated = ProjectDefinition(
    description_for_ai="Create a simple project for cleaning my bathroom.",
)

starred_project = ProjectDefinition(
    name="Starred Project",
    description="Project used for testing star/unstar functionality.",
)


edit_project_info = ProjectDefinition(
    name="Bananas",
    description="Bananas are a type of fruit.",
)

document_history = ProjectDefinition(
    name="Document History Project",
    description="Project used for testing document history functionality.",
)

document_history_created = ProjectDefinition(
    name="Document History Creation Project",
    description="Project used for testing automatic document history creation.",
)

document_history_pinned = ProjectDefinition(
    name="Pinned Document History Project",
    description="Project used for testing pinned document history cleanup.",
)

readonly_document_visibility = ProjectDefinition(
    name="Readonly Document Visibility Project",
    description="Project used for testing readonly document tab visibility.",
)

editor_markdown_table = ProjectDefinition(
    name="Editor Markdown Table Project",
    description="Project used for testing markdown table paste in the editor.",
)

editor_plain_html_paste = ProjectDefinition(
    name="Editor Plain HTML Paste Project",
    description="Project used for testing plain HTML paste in the editor.",
)

editor_common_markdown_paste = ProjectDefinition(
    name="Editor Common Markdown Paste Project",
    description="Project used for testing common markdown paste in the editor.",
)

editor_task_list = ProjectDefinition(
    name="Editor Task List Project",
    description="Project used for testing task lists in the editor.",
)

# Two model tasks (see model_task_definitions) for page-task combobox search tests
multi_model_project = ProjectDefinition(
    name="Multi Model Project",
    description="Project with multiple model tasks for task-tab combobox tests.",
)

filter_project = ProjectDefinition(
    name="Filter Project",
    description="Project with tasks for filter tests.",
)


attach_project_to_task = ProjectDefinition(
    name="Attach Project to Task",
    description="Project used for testing task creation with a project.",
)

sync_document_collaboration = ProjectDefinition(
    name="Sync Document Collaboration Project",
    description="Project used for two-user document sync tests.",
)

sync_document_presence = ProjectDefinition(
    name="Sync Document Presence Project",
    description="Project used for document sync presence tests.",
)

sync_document_contract = ProjectDefinition(
    name="Sync Document Contract Project",
    description="Project used for browser-visible document sync request tests.",
)

offline_document_replay = ProjectDefinition(
    name="Offline Document Replay Project",
    description="Project used for offline document replay order tests.",
)

offline_document_retry = ProjectDefinition(
    name="Offline Document Retry Project",
    description="Project used for failed offline replay retry tests.",
)

offline_document_reload = ProjectDefinition(
    name="Offline Document Reload Project",
    description="Project used for offline replay reload/dedupe tests.",
)
