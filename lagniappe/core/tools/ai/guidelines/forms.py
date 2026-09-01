"""
Form-related guidelines for schema generation, requirements, and content.
"""

PAGE_FORM_SCHEMA_FORMAT = """
### Form Schema Guidelines

A form schema is an **array of element objects**. Each element object contains:
- `id` (required): Unique identifier 
- `type` (required): Element type from the available options
- `title` (required): Display label for the element
- Additional properties based on element type (see Element Schema below)

### Element Schema

#### Available Element Types

- `input` - Text input fields
- `textarea` - Multi-line text areas  
- `checkbox` - Single checkbox
- `radio` - Radio button groups
- `select` - Dropdown selections
- `table` - Dynamic rows of data
- `link` - Internal or external links
- `location` - Address inputs with Google Places autocomplete

#### Element Properties

##### Universal Properties (all elements)

- `id`: Format `"{{type}}-{{identifier}}"` where identifier is a unique alphanumeric string starting with a letter
- `type`: One of the available element types
- `title`: Display label for the element
- `placeholder`: Hint text (when appropriate)

##### Input Element Additional Properties

- `input`: Specify input type from: `text`, `tel`, `number`, `email`, `date`, `time`

##### Selection Element (radio/select) Additional Properties

- `options`: Array of `{{"label": string, "value": string}}` objects
- `value` must be unique within the options array
- `multiple`: Boolean (select only) - allows multiple selections

##### Link Element Additional Properties

- `location`: Either `out` (external link) or `in` (internal page search)
- `title`: Display title for the link (only for external links)

##### Table Element Additional Properties

- `columns`: Array of column schema elements with these restrictions:
  - Column types limited to: `input`, `link`, `checkbox` only
  - Column `id` format: `"row-{{identifier}}"` (not `"{{type}}-{{identifier}}"`)
  - All other element properties and rules apply normally
- The `columns` array is essentially a mini-schema that defines the structure for each table row

##### Location Element Additional Properties

- Automatically provides Google Places API integration for address autocomplete
"""

TASK_FORM_SCHEMA_FORMAT = """
### Form Schema Guidelines

A form schema is an **array of element objects**. Each element object contains:
- `id` (required): Unique identifier 
- `type` (required): Element type from the available options
- `title` (required): Display label for the element
- Additional properties based on element type (see Element Schema below)

### Element Schema

#### Available Element Types

- `input` - Text input fields
- `textarea` - Multi-line text areas  
- `checkbox` - Single checkbox
- `radio` - Radio button groups
- `select` - Dropdown selections
- `table` - Dynamic rows of data
- `todo` - Ordered task checklist
- `link` - Internal or external links
- `location` - Address inputs with Google Places autocomplete
- `signature` - Electronic signature capture
- `html` - Static formatted content/instructions

#### Element Properties

##### Universal Properties (all elements)

- `id`: Format `"{{type}}-{{identifier}}"` where identifier is 8-character alphanumeric starting with letter
- `type`: One of the available element types
- `title`: Display label for the element
- `placeholder`: Hint text (when appropriate)

##### Input Element Additional Properties

- `input`: Specify input type from: `text`, `tel`, `number`, `email`, `date`, `time`

##### Selection Element (radio/select) Additional Properties

- `options`: Array of `{{"label": string, "value": string}}` objects
- `value` must be unique within the options array
- `multiple`: Boolean (select only) - allows multiple selections

##### Link Element Additional Properties

- `location`: Either `out` (external link) or `in` (internal page search)
- `title`: Display title for the link (only for external links)

##### Table Element Additional Properties

- `id`: Format `"table-{{identifier}}"` (follows standard format)
- `columns`: Array of column schema elements with these restrictions:
  - Column types limited to: `input`, `link`, `checkbox` only
  - Column `id` format: `"row-{{identifier}}"` (not `"{{type}}-{{identifier}}"`)
  - All other element properties and rules apply normally
- The `columns` array is essentially a mini-schema that defines the structure for each table row

##### HTML Element Additional Properties

- `content_markdown`: Non-empty Markdown content. Never return an `html` field
- HTML elements should only be used for specific essential information without which the form would have no meaning — legal disclaimers, regulatory notices, compliance text, safety warnings, or critical procedural instructions
- Do not use HTML elements for generic filler instructions like "fill in the fields below" or "please complete this form"

##### Location Element

- `address`: Full formatted address

##### Signature Elements

- Provides electronic signature capture functionality
"""

PAGE_FORM_REQUIREMENTS = """
### Form Requirements

- Page forms add structured data to a page. The page already has a name,
  description, category, attached files, tasks, and optional document content
  outside the form.
- Avoid fields that merely duplicate page name, title, description, category,
  attached files, tasks, or document content unless the user explicitly asks for
  a separate structured field.
- Internal link fields are appropriate when they identify related pages that are
  meaningful to this page's domain, beyond the page's category membership.
- Focus on additional repeatable data that helps sort, filter, review, or use
  the page.
"""

TASK_FORM_REQUIREMENTS = """
### Form Requirements

- Task forms add structured data to a task. The task already has a name,
  description, page relationship, project/model-task relationship when
  applicable, assignee, and due date outside the form.
- Avoid fields that merely duplicate task name, title, description, page,
  project, model task, due date, or assignee unless the user explicitly asks for
  a separate structured field.
- Internal link fields are appropriate when they identify related pages or
  records that are meaningful to completing the task, beyond the task's own
  page/project/model-task relationships.
- Add `required`: Boolean for fields needed before task completion
- Focus on action-specific data that helps complete, review, or filter the task.
"""

TASK_FORM_CONTENT_GUIDELINES = """
### Content Strategy

- Analyze the user's request to identify all necessary data points
- Create elements that fully characterize the subject matter
- Use table elements for variable-length lists (contacts, items, etc.)
- Include HTML elements only for essential information without which the form would lose meaning (legal text, regulatory notices, safety warnings) — do not use them for generic instructions or filler

### Element Selection

- Use `input` with appropriate type for single-line data
- Use `textarea` for longer text content
- Use `select`/`radio` for predefined choices
- Use `table` for repeating data structures
- Use `todo` for a simple ordered checklist of actions without table columns
- Use `location` for any address-related fields
- Use `signature` for consent/approval requirements

### Static Content Standards

- Put static content in `content_markdown`; never generate raw HTML
- Use Markdown paragraphs, headings, ordinary lists, emphasis, links, tables,
  block quotes, fenced code, and `- [ ]`/`- [x]` task lists as appropriate
- Structure content with a logical heading hierarchy
- Never create empty list items
- Keep the content concise and avoid generic filler instructions
"""


PAGE_FORM_CONTENT_GUIDELINES = """
### Content Strategy

- Analyze the user's request to identify all necessary data points
- Create elements that fully characterize the subject matter
- Use table elements for variable-length lists (contacts, items, etc.)

### Element Selection

- Use `input` with appropriate type for single-line data
- Use `textarea` for longer text content
- Use `select`/`radio` for predefined choices
- Use `table` for repeating data structures
- Use `location` for any address-related fields
"""


FORM_AUTOFILL_RULES = """
### Autofill Job

- Complete exactly one structured submission for the supplied target record.
- Preserve every non-empty value in the existing submission unchanged. Treat
  blank or absent values as the fields available for autofill.
- Use exact schema field ids as keys and follow each field type's value format.
- Fill only fields supported by the supplied evidence or appropriate public
  facts. If a field lacks support, omit it and continue with the other fields.
- This is not a workspace discovery or planning task. Do not seek task history,
  previous completions, sibling tasks, or unrelated workspace entities.

### Data Source Priority

Use sources in this order when they conflict:

1. User-provided context and a one-off inline file
2. Target, parent-page, category, and page-document context
3. Summaries in the attached-files context
4. Focused Google Search results when the missing fact is public
5. Extracted text or an original attached file returned by `get_file`
6. Existing knowledge or careful inference

Assume factual data already supplied in the prompt is accurate unless the user
explicitly asks for correction. Do not use tools to verify higher-priority
context.

When sources at the same priority conflict and no supplied rule resolves them,
omit the disputed field rather than choosing a value. Preserve the conflict for
human review when the surrounding workflow supports review actions.

### Attached Files

- Attached-files entries are the complete readable metadata projections for
  files attached directly to the target. A summary is optional.
- Use a file summary directly when it answers the relevant schema field.
- Call `get_file` only when it is available, a specific missing field is likely
  answered by a listed attachment, and the answer is unavailable from the
  prompt, its summary, or appropriate public search.
- First call `get_file` without `include_original` and use its extracted text.
  Request the same file with `include_original=true` only when extracted text
  is unavailable or insufficient and direct visual/file analysis is necessary.
- Batch independent file requests whose hashes are already known. Stop after
  the needed evidence has been retrieved.

### Web Search

- Search only for a specific missing public fact that the supplied context and
  attached files do not answer.
- Most autofills need no search. When public research is necessary, one or two
  focused searches should normally be enough.
- Do not search for private workspace facts, task history, or information that
  is already present in the prompt.

### Content Approach

- Determine from the context whether the form calls for factual data, creative/original content, or a mix
- For factual content (e.g. real places, people, products): only use information from your knowledge, the web, or provided sources — do not fabricate facts
- For creative content (e.g. original writing, fictional entries, curated descriptions): produce substantive, well-crafted content that fits the page naturally
- If you cannot determine a relevant value for a field and creativity is not appropriate, do not add that field to the submission
- Do not fill fields that are clearly intended for the user's personal input — fields like "want to read", "personal opinion", "my rating", "notes to self", "wishlist", "personal review", or similar subjective/user-action fields should always be left empty
- Once the supported fields are complete, stop researching and return the JSON submission.
"""

SCHEMA_TYPE_GUIDELINES = """
### Form Schema Element Type Reference

- The form schema is an array of element objects
- Each element object has a type property that specifies the type of element
- The type property is one of the following: `input`, `textarea`, `link`, `location`, `table`, `todo`, `checkbox`, `radio`, `select`, `signature`, `html`
- The `todo` type is available only in task forms

- The element object has an id property that is a unique identifier for the element
- The element object has a title property that is the display label for the element
- The element object optionally has a placeholder property that is the hint text for the element
- The element object optionally has a required property that is a boolean indicating if the element is required
- The element object may have additional properties depending on its type

#### `input` Submission Value Guidelines

- Input element values are strings
- Only fill with information that matches the input type (`text`, `email`, `date`, `number`, `tel`)
- Dates should be in format YYYY-MM-DD, times in HH:MM (e.g., 17:00 for 5 PM), tel numbers in 123-456-7890

#### `textarea` Submission Value Guidelines

- Text area element values are strings
- Fill with concise descriptive text from provided sources when the evidence
  supports the field
- In autofill, a grounded summary sentence or paragraph is a valid textarea
  value; do not omit textarea fields merely because they are narrative

#### `link` Submission Value Guidelines

- For link elements with `location` set to `in` (internal links):
  - The value may be an entity `id` supplied in context or returned by an available lookup tool
  - The value may also be a clear plaintext page/entity name from the provided evidence; AI validation will resolve it to an internal entity when possible
  - Autofill must not perform a workspace lookup merely to resolve an internal
    id; use the clear plaintext name when that is what the evidence provides
  - If an internal link cannot be filled, omit that field only; do not leave
    other grounded fields empty because the link is unresolved
  - Setting this value creates a reference to that internal page or entity
- For link elements with `location` set to `out` (external links):
  - Value is an object with both `title` and `url` properties
  - `title` will be displayed as the display title for the link (2-3 words max), the name of the website is fine if a short title is not possible
  - `url` is the URL of the link
  - External links should point to primary or original sources, not aggregator platforms (e.g. avoid Amazon, Goodreads, Rotten Tomatoes, Yelp, TripAdvisor, IMDb, Metacritic, etc.) — link to the official site, publisher, author, or original reviewer instead

#### `location` Submission Value Guidelines

- Location element values are objects with both `name` (name of the location or shortened address) and `address` (full formatted address) properties
- AI/autofill submissions may also provide a plain address string; location validation will store unresolved addresses as address text
- If no relevant location data is available, do not add that field to the submission

#### `table` Submission Value Guidelines

- Tables are mini-forms embedded within the larger form
- A table's submission value is an object with a `rows` property containing an array of table row submissions
- Each table row submission is a JSON object where the properties are the `id` fields from the elements in the table's `columns` array, and the values are formatted according to the guidelines for that element's `type`.
- Table row submissions follow the same rules and guidelines as the main form, using the `columns` property of the table element as the schema
- Example table submission value structure:
```
{{
  "rows": [
    {{"column-1-rating-id": "5", "column-2-publication-id": "Some Publication", "column-3-link-id": {{"title": "display title", "url": "https://example.com"}}, "column-4-internal-link-id": "entity-id-from-tool"}}
  ]
}}
```

#### `todo` Submission Value Guidelines

- Todo lists are available only on task forms
- A todo list value is an object with an `items` array
- Each item is an object with a non-empty `text` string and a `checked` boolean
- Preserve item order; use `checked`: false for newly generated items
- Example: `{{"items": [{{"text": "Confirm the venue", "checked": false}}]}}`

#### `radio`/`select` Submission Value Guidelines

- Only select options when you can confidently determine the correct choice from available information
- Always use the `value` property from the schema's `options` property, never the `label` text
  - For single-select fields (no `multiple` property or `multiple`: false):
    - Value should be a single string matching an option's `value`
    - Example: "select-field": "star-4" (not "4-Star")
  - For multi-select fields (`multiple`: true):
    - Value should be an array of strings, each matching an option's `value`
    - Example: "select-field": ["amenity-pool", "amenity-spa"] (not ["Swimming Pool", "Spa & Wellness Center"])
- If no relevant selection can be confidently determined, do not include that property in the submission

#### `checkbox` Submission Value Guidelines

- Value should be a boolean: `true` or `false` if you can confirm the checkbox should be checked or unchecked based on available information
- If you cannot confirm whether the checkbox should be checked or unchecked, do not include that field in the submission at all
"""
