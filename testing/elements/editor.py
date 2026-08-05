from dataclasses import dataclass
from enum import Enum

from playwright.sync_api import expect

from .combobox import Dropdown, Select


@dataclass
class EditorOption:
    title: str = ""
    menu: str = ""
    option: str = ""


class EditorToggleOptions(Enum):
    BOLD = EditorOption(title="Bold")
    ITALIC = EditorOption(title="Italic")
    BULLET_LIST = EditorOption(title="Bullet List")
    ORDERED_LIST = EditorOption(title="Ordered List")
    TASK_LIST = EditorOption(title="Task List")
    UNDO = EditorOption(title="Undo")
    REDO = EditorOption(title="Redo")
    FOCUS = EditorOption(title="Toggle Focus")

    def click(self, editor):
        option = editor.toolbar.locator(f"button[title='{self.value.title}']")
        expect(option).to_be_visible()
        option.click()
        editor.wait_for_render()

    def toggle(self, editor):
        option = editor.toolbar.locator(f"button[title='{self.value.title}']")
        expect(option).to_be_visible()
        active = option.get_attribute("data-active") == "true"
        option.click()
        expect(option).to_have_attribute("data-active", "false" if active else "true")
        editor.wait_for_render()


class EditorMenuOptions(Enum):
    # Style menu
    UNDERLINE = EditorOption(menu="Style", title="Underline")
    STRIKE = EditorOption(menu="Style", title="Strikethrough")
    SUPERSCRIPT = EditorOption(menu="Style", title="Superscript")
    SUBSCRIPT = EditorOption(menu="Style", title="Subscript")
    CLEAR_FORMAT = EditorOption(menu="Style", title="Clear Format")

    # Headings menu
    HEADING_1 = EditorOption(menu="Headings", title="Heading 1")
    HEADING_2 = EditorOption(menu="Headings", title="Heading 2")
    HEADING_3 = EditorOption(menu="Headings", title="Heading 3")
    PARAGRAPH = EditorOption(menu="Headings", title="Paragraph")

    # Insert menu
    HORIZONTAL_RULE = EditorOption(menu="Insert", title="Horizontal Rule")
    CODE_BLOCK = EditorOption(menu="Insert", title="Code Block")
    BLOCKQUOTE = EditorOption(menu="Insert", title="Blockquote")

    # Align menu
    ALIGN_LEFT = EditorOption(menu="Align", title="Align Left")
    ALIGN_CENTER = EditorOption(menu="Align", title="Align Center")
    ALIGN_RIGHT = EditorOption(menu="Align", title="Align Right")
    ALIGN_JUSTIFY = EditorOption(menu="Align", title="Align Justify")

    def click(self, editor):
        dropdown = Dropdown(editor.toolbar.locator(f"[title='{self.value.menu}']"))
        dropdown.select_by_name(self.value.title)
        editor.wait_for_render()


class EditorFormOptions(Enum):
    FONT_FAMILY = EditorOption(
        menu="Style", title="Font Family", option="setFontFamily"
    )
    COLOR = EditorOption(menu="Style", title="Text Color", option="setColor")
    LINK = EditorOption(menu="Insert", title="Link", option="addLink")
    IMAGE = EditorOption(menu="Insert", title="Image", option="addImage")
    YOUTUBE = EditorOption(menu="Insert", title="YouTube Video", option="addYouTube")
    GENERATE_TEXT = EditorOption(
        menu="Insert", title="Generate Text", option="generateText"
    )

    def form(self, editor):
        dropdown = Dropdown(editor.toolbar.locator(f"[title='{self.value.menu}']"))
        dropdown.select_by_name(self.value.title)
        form = editor.toolbar.locator(f"[data-option='{self.value.option}']")
        expect(form).to_be_visible()
        return form


class EditorAddLink:
    URL_INPUT = "input[name='link']"
    SUBMIT = "button[type='submit']"

    def __init__(self, editor, open_form=True):
        self.editor = editor
        if open_form:
            self.form = EditorFormOptions.LINK.form(editor)
        else:
            self.form = editor.toolbar.locator(
                f"[data-option='{EditorFormOptions.LINK.value.option}']"
            )
        expect(self.form).to_be_visible()
        self.combobox = Select(self.form.locator(self.URL_INPUT))
        if open_form:
            self.editor.select_text()

    @classmethod
    def from_shortcut(cls, editor):
        editor.text_entry.press("Control+K")
        form = cls(editor, open_form=False)
        expect(form.input).to_be_visible()
        expect(form.input).to_be_editable()
        form.input.focus()
        return form

    @property
    def input(self):
        return self.form.locator(self.URL_INPUT)

    def fill(self, url):
        self.input.fill(url)

    def submit(self, select=False):
        if select:
            self.editor.select_text()
        if self.input.get_attribute("aria-expanded") == "true":
            self.input.press("Escape")
        self.form.locator(self.SUBMIT).evaluate("(button) => button.click()")
        self.editor.wait_for_render()

    def select_search_result(self, query, text):
        self.input.fill(query)
        panel = self.combobox.panel
        expect(panel).to_be_visible()
        option = panel.get_by_role("option").filter(has_text=text).first
        expect(option).to_be_visible()
        option.click()


class EditorAddYouTube:
    URL_INPUT = "input[name='url']"
    SUBMIT = "button[type='submit']"

    def __init__(self, editor):
        self.form = EditorFormOptions.YOUTUBE.form(editor)
        expect(self.form).to_be_visible()

    def fill(self, url):
        self.form.locator(self.URL_INPUT).fill(url)

    def submit(self):
        self.form.locator(self.SUBMIT).click()


class EditorAddImage:
    PROMPT = "textarea[name='prompt']"
    GENERATE_SUBMIT = "button[data-role='generate']"
    GENERATE_CANCEL = "button[data-role='cancel']"
    DROPZONE = "div[data-role='dropzone']"
    FORM = "form[data-option='addImage']"

    def __init__(self, editor):
        self.editor = editor
        self.form = EditorFormOptions.IMAGE.form(editor)
        expect(self.form).to_be_visible()

    def set_file(self, upload):
        """Set a file using the configured upload method."""
        upload.set(self.form)


class EditorGenerateTextMode(Enum):
    REPLACE_DOCUMENT = "replace"
    APPEND_TO_DOCUMENT = "append"
    PREPEND_TO_DOCUMENT = "prepend"
    ADD_AS_QUOTE = "quote-top"
    ADD_AT_CURSOR = "cursor"
    REPLACE_SELECTION = "replace-selection"

    def set(self, form):
        radio = form.locator(f'input[value="{self.value}"]')
        expect(radio).to_be_visible()
        radio.check()


class EditorGenerateText:
    TEXT_AREA = "textarea[name='prompt']"
    SUBMIT = "button[type='submit']:not([data-role='explain'])"
    EXPLAIN = "button[data-role='explain']"

    def __init__(self, editor):
        self.form = EditorFormOptions.GENERATE_TEXT.form(editor)
        expect(self.form).to_be_visible()

    def set_mode(self, mode):
        mode.set(self.form)

    def fill_prompt(self, prompt):
        self.form.locator(self.TEXT_AREA).fill(prompt)

    def submit(self):
        self.form.locator(self.SUBMIT).click()

    def explain(self):
        self.form.locator(self.EXPLAIN).click()


class EditorColorOptions(Enum):
    BLACK = EditorOption(title="Black")
    SLATE = EditorOption(title="Slate")
    RED = EditorOption(title="Red")
    ORANGE = EditorOption(title="Orange")
    YELLOW = EditorOption(title="Yellow")
    GREEN = EditorOption(title="Green")
    CYAN = EditorOption(title="Cyan")
    BLUE = EditorOption(title="Blue")
    PURPLE = EditorOption(title="Purple")
    PINK = EditorOption(title="Pink")

    def click(self, editor):
        form = EditorFormOptions.COLOR.form(editor)
        expect(form).to_be_visible()
        editor.select_text()
        form.locator(f"[title='{self.value.title}']").click()
        editor.wait_for_render()


class EditorFontFamilyOptions(Enum):
    SERIF = EditorOption(title="Serif")
    SANS = EditorOption(title="Sans")
    MONO = EditorOption(title="Mono")

    def click(self, editor):
        form = EditorFormOptions.FONT_FAMILY.form(editor)
        expect(form).to_be_visible()
        editor.select_text()
        form.locator(f"[title='{self.value.title}']").click()
        editor.wait_for_render()


class EditorImageSettings(Enum):
    ALIGN_LEFT = EditorOption(title="Align Left")
    ALIGN_CENTER = EditorOption(title="Align Center")
    ALIGN_RIGHT = EditorOption(title="Align Right")
    ALIGN_JUSTIFY = EditorOption(title="Align Justify")
    FLOAT_LEFT = EditorOption(title="Float Left")
    FLOAT_RIGHT = EditorOption(title="Float Right")
    FLOAT_NONE = EditorOption(title="Float None")
    SIZE_SMALL = EditorOption(title="Size Small")
    SIZE_MEDIUM = EditorOption(title="Size Medium")
    SIZE_LARGE = EditorOption(title="Size Large")

    @staticmethod
    def form(editor):
        """Return the setImage form element."""
        return editor.toolbar.locator("[data-option='setImage']")

    def click(self, editor):
        """Click this image setting option."""
        form = self.form(editor)
        form.locator(f"button[title='{self.value.title}']").click()
        editor.wait_for_render()


class Editor:
    """
    Helper for the rich text editor component.

    Provides methods for typing, formatting, and interacting with
    toolbar options and forms.
    """

    EDITOR = "[data-role='editor']"
    TEXT_ENTRY = ".ProseMirror"
    TOOLBAR = "[data-role='toolbar']"
    LINK_POPOVER = "[data-role='editor-link-popover']"
    TRAILING_BREAK = "br.ProseMirror-trailingBreak"

    def __init__(self, document):
        self.document = document
        self.editor = document.locator(self.EDITOR)
        self.toolbar = document.locator(self.TOOLBAR)
        self.wait_until_ready()

    def wait_until_ready(self):
        """Wait for the collaborative editor surface to be interactive."""
        expect(self.editor).to_be_visible()
        expect(self.editor).to_have_attribute("loaded", "")
        expect(self.editor).to_have_attribute("initialized", "")
        expect(self.toolbar).to_be_visible()
        expect(self.toolbar).to_have_attribute("initialized", "")
        expect(self.text_entry).to_be_visible()

    @property
    def text_entry(self):
        text_entry = self.editor.locator(self.TEXT_ENTRY)
        expect(text_entry).to_have_attribute("contenteditable", "true")
        return text_entry

    @property
    def history(self):
        dropdown = Dropdown(self.toolbar.locator("[title='History']"))
        with self.editor.page.expect_response("**/history?**"):
            dropdown.click()
        panel = dropdown.panel
        expect(panel).to_be_visible()
        return panel

    def focus(self):
        """Move focus to the end of the document."""
        self.text_entry.click()
        self.text_entry.press("Control+End")

    def type_text(self, text: str):
        """Type text into the editor."""
        self.text_entry.press_sequentially(text)
        return self.text_entry

    def paste(self, text: str, html: str | None = None, focus: bool = True):
        """Paste clipboard data into the editor."""
        if focus:
            self.focus()
        self.text_entry.evaluate(
            """(element, payload) => {
                const data = new DataTransfer();
                data.setData("text/plain", payload.text);
                if (payload.html !== null) data.setData("text/html", payload.html);

                const event = new ClipboardEvent("paste", {
                    bubbles: true,
                    cancelable: true,
                    clipboardData: data,
                });

                if (!event.clipboardData) {
                    Object.defineProperty(event, "clipboardData", { value: data });
                }

                element.dispatchEvent(event);
            }""",
            {"text": text, "html": html},
        )
        self.wait_for_render()
        return self.text_entry

    def clear_text(self):
        """Clear all text from the editor."""
        self.focus()
        self.select_text()
        self.text_entry.press("Delete")
        self.wait_for_render()
        return self.text_entry

    def get_text(self):
        """Get the plain text content."""
        return self.text_entry.evaluate(
            """(element) => element
                .closest('[data-widget]')
                ._lp_widget
                .editor
                .getText()"""
        )

    def wait_for_render(self):
        """Wait for the editor to be fully rendered."""
        return self.text_entry.evaluate(
            """(element) => element
                .closest('[data-widget]')
                ._lp_widget
                .waitForRender()"""
        )

    def get_element(self, selector):
        return self.text_entry.locator(selector)

    @property
    def link_popover(self):
        popover = self.editor.page.locator(self.LINK_POPOVER)
        expect(popover).to_be_visible()
        return popover

    def link_popover_action(self, action):
        self.link_popover.locator(f"button[data-action='{action}']").click()
        self.wait_for_render()

    def blur(self):
        with self.editor.page.expect_response("**/l/sync"):
            self.text_entry.blur()

    def select_text(self):
        self.text_entry.press("Control+A")
        return self.text_entry

    def enter(self):
        self.text_entry.press("Enter")
        return self.text_entry
