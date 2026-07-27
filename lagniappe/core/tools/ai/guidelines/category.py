"""
Category generation guidelines.
"""

CATEGORY_GENERATION_GUIDELINES = """
### Category Guidelines

- A category is a collection scope for conceptually related but distinct page
  subjects. It may represent a homogeneous collection of repeated items, or a
  shared owner, context, or domain containing different kinds of subjects.
- Do not generate a category default form by default. Omit `form_name` and
  `form_schema` unless the user's request or supplied evidence makes it
  unambiguous that pages will be repeated instances of one type and the same
  small, stable fields apply meaningfully to essentially every page.
- A category label alone is not enough evidence for a default form. If the
  category can naturally contain different subject types, or form fit is
  uncertain, return the category without a default form.
- When a default form is justified, its name should describe the repeated page
  type and its fields must add useful structured data beyond the page name,
  description, and category relationship.
- Never invent generic fields merely to make a category form possible.
"""

CATEGORY_OUTPUT_REQUIREMENTS = """
### Category Output Requirements

- Return only a valid JSON object with the following properties:
  - `category_name`: String
  - `category_description`: String
  - `form_name`: Optional string; include only for a justified category default form
  - `form_schema`: Optional non-empty array; include only with `form_name`
- Omitting the optional form fields means the category has no default form.
"""
