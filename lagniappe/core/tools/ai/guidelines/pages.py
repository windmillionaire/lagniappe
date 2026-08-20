"""
Page generation and document guidelines.
"""

from .output import TASK_LIST_HTML_RULES


SUBMISSION_OUTPUT_REQUIREMENTS = """
### Submission Output Requirements

- A valid submission is a JSON object with properties consisting of the `id` fields of the schema elements with values formatted according to the guidelines for that element's `type`.
- Submission objects should contain all properties from the partial submission (if provided) unaltered.
- Missing fields should be filled with data from your knowledge (including the web if search tools have been provided), attached file content, or user context if possible.
- If no relevant data is available for a field, do not add that field to the submission.
- Do not fill fields that are clearly intended for the user's personal input — fields like "want to read", "personal opinion", "my rating", "notes to self", "wishlist", "personal review", or similar subjective/user-action fields should always be left empty.
- If the role of a given schema element is unclear or confusing, do not add that field to the submission.
"""

PAGE_GENERATION_RULES = """
1. Generate pages for the category described by the context provided.
2. If a user request has been provided, prioritize it over the category information to guide your pages.
3. If a category description has been provided, use it to understand the category and its purpose.
4. When a form schema is provided, it describes the structured fields on each page. When no form schema is provided, the pages have no form; do not invent a submission object.
5. Each page should be a JSON object with the following properties:
  - `name`: The page's canonical name
  - `description`: The page's canonical description
  - `document`: Optional HTML content
  - `submission`: A form submission object only when a form schema is provided
6. Tools are available to explore the workspace. A recommended workflow:
   - Call get_category_forms to see what content types (forms) exist in the category — forms act as tags that classify what a page is.
   - Call get_category_pages with a form_id to see example pages of a specific type — study their tone, style, and data patterns before generating similar content.
   - Use search_entities to find real-world information or discover related content elsewhere in the workspace.
   - Use get_entity to load full details of any specific entity found through search.

### Content Approach

- Determine from the category context and user request whether pages should reflect real-world data, original/creative content, or a mix.
- For real-world categories (e.g. restaurants, albums, places): prioritize accurate, verifiable information from your knowledge or search results. Do not invent or fabricate data.
- For creative or original categories (e.g. characters, recipes, story ideas): generate rich, thoughtful content that fits the category. Creativity is expected — produce substantive, well-crafted entries rather than generic filler.
- Ensure variety and diversity across pages when possible (different styles, characteristics, perspectives, etc.)
- Avoid pages that are too similar to each other unless that conflicts with the user request

### Form Submission Guidelines

1. When a form schema is provided, analyze it to understand the structure and type of content expected
2. Analyze the user request (if provided) to understand what information or content is needed
3. Use the search tool to find additional information when the category involves real-world data
4. Only when a form schema is provided, the submission should be a valid JSON object, with properties consisting of the `id` fields of the schema elements and values as specified by the guidelines for that element type.

### Data Integrity Rules

- For real-world data: only use information from your knowledge, the web, or provided sources — do not fabricate facts
- For creative content: produce original, high-quality content that fits the category naturally
- If you cannot determine a relevant value for a field, do not add that field to the submission
- Do not fill fields that are clearly intended for the user's personal input — fields like "want to read", "personal opinion", "my rating", "notes to self", "wishlist", "personal review", or similar subjective/user-action fields should always be left empty
"""

DOCUMENT_GUIDELINES = (
    """
### Document Guidelines

- A page's name and description are always canonical. When a form is attached,
  its structured submission is the primary additional content.
- Only include a document when freeform text content would add meaningful value beyond what the form fields capture
- Examples of when to include a document:
  - Unique historical significance, architectural details, or cultural context
  - Distinctive features, experiences, or selling points not captured by standard form fields
  - Rich descriptive content that helps distinguish this page from similar ones
- Most pages should work perfectly with just the structured form data
- If you do include a document, it should be clean, unstyled HTML that complements (not duplicates) the form data
- When tools are available, you can link to related entities in the document HTML using the `url` and `name` fields from tool results: `<a href="{{url}}">{{name}}</a>`

#### HTML Content Standards

- Generate clean, semantic HTML without CSS classes or inline styles
- Use appropriate elements: `<p>`, `<h1>` through `<h6>`, `<ul>`, `<ol>`, `<li>`, `<strong>`, `<em>`
- Structure content logically with proper hierarchy
- Never create empty list items
- Remove extra whitespace and ensure proper tag closure
"""
    + TASK_LIST_HTML_RULES
)

PAGE_GENERATION_OUTPUT_REQUIREMENTS = """
### Page Generation Output Requirements

- Return only a valid JSON array of page objects, each with the following properties:
  - `document`: Optional HTML content
  - `submission`: A form submission object only when a form schema is provided
  - `name`: A name for the page
  - `description`: A description for the page
"""
