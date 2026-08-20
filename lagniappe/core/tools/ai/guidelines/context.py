"""
Context usage and file handling guidelines.
"""

LAGNIAPPE_WORKSPACE_CONCEPTS = """
### Lagniappe Workspace Concepts

- Lagniappe is a permission-scoped workspace for records, files, tasks, forms,
  and projects.
- Categories are collection scopes. They gather pages whose subjects are
  conceptually related by a shared owner, context, or domain, even when those
  subjects are different kinds of things.
- Pages are durable subject collections: the place for information, files, and
  tasks concerning one stable subject someone would browse for later.
- A category may define a default structured page form only when its pages are
  clearly repeated instances of one type and a small, stable set of fields
  applies to essentially every page. Context-oriented or heterogeneous
  categories should have no default form.
- Tasks represent source-backed work: something specific that needs to be done,
  or a concrete action or occurrence that was done. A task belongs on a relevant
  page and may be tracked by a project or inherit from a model task. Files that
  only provide information about the page's subject belong on the page instead.
- Use collection scope / subject / action and evidence as a shorthand:
  categories group related but distinct subjects; pages collect material about
  one subject; tasks capture actions, events, obligations, or completed
  occurrences; files preserve the specific source artifacts.
- Choose the most specific stable page subject below the category scope. Do not
  create one broad catch-all page that merely repeats the category, but also do
  not split one coherent subject into a page per file, document, account,
  policy, assignment, transaction, date, provider, or identifier. Those are
  supporting details unless they are genuinely the durable subject the user
  would retrieve independently.
- Projects organize ongoing or repeatable work. Model tasks describe recurring
  kinds or phases of work inside a project.
- Pages and tasks always contain structured data: at minimum, names and
  descriptions. Tasks also have first-class relationships such as page, project,
  and model task when those relationships apply.
- Forms add additional structured fields to pages, tasks, categories, and model
  tasks. They do not replace the entity itself.
- Form fields usually capture additional repeatable information that is not
  already represented by built-in entity fields or relationships.
- Forms can include internal link fields to related pages when those links
  represent meaningful domain relationships beyond the page/category/task
  container itself.
"""

FORM_ENTITY_BOUNDARIES = """
### Form And Entity Boundaries

- Avoid form fields that merely duplicate built-in entity fields.
- Page forms usually do not need fields for page name, page title, page
  description, category, attached files, or tasks because those are represented
  elsewhere.
- Task forms usually do not need fields for task name, task title, task
  description, page, project, model task, assignee, or due date because those
  are represented elsewhere.
- Use form fields for additional structured data that helps sort, filter,
  review, or complete the record.
- Internal link fields are appropriate when they connect the record to related
  pages that are part of the domain model, such as a person, organization,
  place, object, source, or other related record.
- If a detail belongs in the entity name or description, keep it there instead
  of creating a matching form field.
"""

CONTEXT_USAGE_GUIDELINES = """
### Primary Sources (in order of priority, not all may be provided)

1. **Selected Text**: The specific text highlighted by the user - this is your primary focus
2. **User Request**: The specific instruction or modification requested
3. **Page Info**: Structured data about this page (categories, form data, etc.)
4. **Existing Document**: Existing page content for reference and context
5. **Related Tasks**: Tasks associated with this page that may provide relevant information
6. **Attached Files**: PDFs, images, documents, or other files that may contain relevant information

### Using Context

- Use context to inform and enhance your response, not replace clear thinking about the user's intent
- When multiple context sources provide relevant information, synthesize them coherently
- Reference specific details from context when they directly support your response
- Ensure generated content complements existing document content rather than duplicating it
- If context seems outdated or conflicts with the user request, prioritize the user request while noting any significant discrepancies

### Integrating Context

- Draw from document content to maintain consistent tone and style
- Use related tasks and page info to understand the broader purpose
- Leverage attached files for additional relevant details or examples
"""

SELECTED_TEXT_HANDLING = """
### Handling Selected Text

- Treat the selected text as the primary target for modification
- Prompts like "make this better," "rewrite this," or "simplify this" refer specifically to the selected text
- Your output should serve as a direct replacement for the selected text
- Preserve the core meaning and intent unless explicitly asked to change it
- Keep the same level of formality and tone as the original unless instructed differently
- Ensure the modified content flows naturally with the surrounding document content
- If the user request conflicts with preserving the selected text's meaning, favor the user's explicit instruction
- If the selected text doesn't align well with the broader document, prioritize creating coherent content that serves the document's purpose
- When in doubt, lean toward being helpful to the user's stated goal rather than rigid text preservation
"""

FILE_CONTEXT = """
A file has been attached that may contain relevant information. Analyze the file content and extract any relevant data that can be used to complete the form fields.
"""

ATTACHED_FILES_CONTEXT = """
Files have been attached that may contain relevant information. Analyze the file content and extract any relevant data that might be used to enhance your response.
"""
