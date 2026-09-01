"""Page submission and report-document guidelines."""


SUBMISSION_OUTPUT_REQUIREMENTS = """
### Submission Output Requirements

- A valid submission is a JSON object with properties consisting of the `id` fields of the schema elements with values formatted according to the guidelines for that element's `type`.
- Submission objects should contain all properties from the partial submission (if provided) unaltered.
- Missing fields should be filled with data from your knowledge (including the web if search tools have been provided), attached file content, or user context if possible.
- If no relevant data is available for a field, do not add that field to the submission.
- Do not fill fields that are clearly intended for the user's personal input — fields like "want to read", "personal opinion", "my rating", "notes to self", "wishlist", "personal review", or similar subjective/user-action fields should always be left empty.
- If the role of a given schema element is unclear or confusing, do not add that field to the submission.
"""

REPORT_DOCUMENT_GUIDELINES = """
### Report Page Document Guidelines

- A page's name and description are always canonical. When a form is attached,
  its structured submission is the primary additional content.
- Only include `document_markdown` when freeform text adds meaningful value
  beyond the name, description, and form fields.
- Write ordinary Markdown. Trusted application code converts it through the
  shared sanitized, editor-compatible renderer before execution.
- Use headings, paragraphs, emphasis, links, block quotes, tables, fenced code,
  and Markdown task lists when they improve the document. Do not hand-author
  HTML.
- When a read tool returns both a related entity's `url` and `name`, Markdown
  links may use those exact values.
- Keep documents concise and complementary; do not duplicate structured form
  values merely to make the document longer.
"""
