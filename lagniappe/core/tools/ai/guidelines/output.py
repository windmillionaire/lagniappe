"""
Output format guidelines for JSON, HTML, and text generation.
"""

JSON_OUTPUT_RULES = """
### JSON Output Requirements

1. Return ONLY valid JSON - no explanatory text, markdown formatting, or extra content
2. Ensure all JSON is properly formatted and parseable
3. Use double quotes for all strings and property names
4. Do not include trailing commas
5. Validate that the structure matches the expected format
6. If generating arrays, ensure each element follows the same structure
"""


TASK_LIST_HTML_RULES = """
### Editable Document Checklists

- When the user asks for a checklist, shopping list, packing list, todo list,
  or similar checkable document list, use editor task-list HTML instead of a
  plain `<ul>`
- Use this exact structure so the editor can display checkboxes and preserve
  checked state:
  `<ul data-type="taskList"><li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label><div><p>Item text</p></div></li></ul>`
- For checked/completed items, set `data-checked="true"` on the `<li>` and add
  `checked="checked"` to the checkbox input
- Keep each checklist item text inside the nested `<div><p>...</p></div>`
- Use ordinary `<ul>` or `<ol>` for lists that should not be checkable
"""


HTML_GENERATION_RULES = (
    """
### HTML Structure and Semantics

- Generate clean, semantic HTML without CSS classes or inline styles
- Use appropriate HTML elements: `<p>`, `<h1>` through `<h6>`, `<ul>`, `<ol>`, `<li>`, `<strong>`, `<em>`, `<br>`
- Structure content logically with proper headings hierarchy
- Use `<strong>` for emphasis, `<em>` for slight emphasis
- Use `<code>` for inline code or technical terms
- Use `<blockquote>` for quotes or highlighted information

### HTML Quality Standards

- **Lists**: Never create empty list items (`<li></li>` or `<li> </li>`) - every `<li>` must contain actual text content
- **Spacing**: Remove extra whitespace and empty lines between HTML elements
- **Clean Output**: Do not add unnecessary `<br>` tags or empty paragraphs
- **Structure**: Ensure all tags are properly opened and closed
- **Minimal Formatting**: Generate clean, minimal HTML without extra spacing or line breaks at start/end
- **Organization**: Keep content concise and well-organized

### Internal Links

- When tools are available and results have been returned, you can create links to internal entities using the `url` and `name` fields from tool results (search_entities, get_entity, get_category_pages, etc.)
- Format: `<a href="{{url}}">{{name}}</a>` where `url` and `name` come from the tool result dictionaries
"""
    + TASK_LIST_HTML_RULES
)


SAFETY_RULES = """
### Content Safety Rules
- Generate appropriate, professional content
- Avoid controversial, harmful, or inappropriate material
- Respect privacy and do not generate personal information
- Focus on helpful, accurate, and relevant information
- When uncertain about appropriateness, err on the side of caution
"""


TEXT_OUTPUT_RULES = """
### Text Output Requirements

- Return only plain text with no formatting (no bold, italics, bullet points, or special characters)
"""
