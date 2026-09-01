"""Output format guidelines for JSON, Markdown, and plain text generation."""

JSON_OUTPUT_RULES = """
### JSON Output Requirements

1. Return ONLY valid JSON - no explanatory text, markdown formatting, or extra content
2. Ensure all JSON is properly formatted and parseable
3. Use double quotes for all strings and property names
4. Do not include trailing commas
5. Validate that the structure matches the expected format
6. If generating arrays, ensure each element follows the same structure
"""


MARKDOWN_GENERATION_RULES = """
### Markdown Output Requirements

- Return ordinary Markdown only; never return HTML or wrap the response in an
  outer code fence
- Use headings, paragraphs, emphasis, block quotes, fenced code blocks,
  tables, and ordinary ordered or unordered lists when they improve clarity
- Use `- [ ]` and `- [x]` for checkable task-list items; use ordinary `-`
  bullets for lists that should not be checkable
- Keep list items non-empty and use a logical heading hierarchy
- When tools return an entity `url` and `name`, create an internal link with
  `[name](url)` using those returned values exactly; do not invent links
"""


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
