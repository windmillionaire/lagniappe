# Backend Definitions and Exceptions

The definitions module (`lagniappe/core/definitions/`) provides enums and configuration classes used throughout the entity system -- permissions, filter types, entity attributes, column ordering, asset types, search facets, and import stages. The exceptions module (`lagniappe/core/exceptions/`) provides custom exception types and error capture.

## Permissions (`definitions/permissions.py`)

The permission system is hierarchical: higher actions imply lower ones. Permissions are checked at two levels -- global (resource-type) and specific (entity-instance).

### Action

Enum of permission actions in ascending order of privilege:

| Action | Value | Description |
|---|---|---|
| `NONE` | 0 | No access |
| `RESTRICTED` | 1 | Can access children of a restricted parent |
| `VIEW` | 2 | Can view/read |
| `ASSIGN` | 3 | Can assign to users/groups |
| `EDIT` | 4 | Can modify |
| `DELETE` | 5 | Can delete |
| `PUBLISH` | 6 | Can publish/unpublish |
| `CREATE` | 7 | Can create new instances |
| `PERMISSIONS` | 8 | Can manage permissions |
| `ALL` | 9 | Full access |

`action.implies(other)` returns `True` if this action's value is >= the other's. Uses `DefaultEnum` metaclass -- unknown lookups return `NONE`.

### Resource

Enum of resource types. Three categories:

| Category | Resources | Access |
|---|---|---|
| **Owner** | `SITE`, `USER_GROUPS`, `INGRESS` | Owner only |
| **Global** | `USERS`, `MODELS`, `FORMS` | Admin/owner, or permission-based |
| **Instance** | `PAGE`, `CATEGORY`, `PROJECT`, `TASK`, `FILE`, `MODEL` | Aliases to their global resource |

`MODELS` is the shared global resource for categories, projects, pages, tasks, and files. `resource.allowed(action, user)` checks the user's global permission level for that resource.

Creating a page inside an existing category is category-scoped: a user with
`EDIT` on that category can add pages there. Global `MODELS.CREATE` is reserved
for creating model containers such as categories and projects, and for broad
owner/admin-style model creation flows.

### General

Global permission sections shown in the user permission form. Each has available levels and a default:

| Section | Levels | Default |
|---|---|---|
| `USERS` | None, View, Assign, Delete, Create | None |
| `MODELS` | None, View, Edit, Delete, Create | None |
| `FORMS` | None, View, Edit, Delete, Create | View |

### Specific

Entity-level permission sections for granular access control on individual categories, projects, pages, and groups:

| Section | Levels |
|---|---|
| `CATEGORIES` | View, Edit, Publish, Delete, Create |
| `PROJECTS` | View, Edit, Publish, Delete, Create |
| `PAGES` | View, Edit, Publish |
| `GROUPS` | View, Edit, Assign |

### Site

Boolean site-wide flags: `ADMIN` (admin privileges) and `PUBLIC` (public access enabled).

### Levels

Display-friendly enum mapping action names to strings for the permission form UI. Includes `FALSE`/`TRUE` for boolean permissions.

## Filters (`definitions/filters.py`)

Defines the filter condition system used by the saved filters feature.

### FieldType

Types of filterable fields: `STRING`, `NUMBER`, `BOOLEAN`, `TIMESTAMP`, `LIST`.

### Comparator

Comparison operators: `EQUALS`, `NOT_EQUALS`, `GREATER_THAN`, `LESS_THAN`, `CONTAINS`, `IN`, `NOT_IN`, `SUBSTRING`, `CONTAINS_ANY`, `BETWEEN`, `EXISTS`, `NOT_EXISTS`, `IS_TRUE`, `IS_FALSE`, and range variants.

### FilterOptions

Maps field types to their available comparator UI labels. Each option enum provides human-readable labels:

| Option Set | Examples |
|---|---|
| `DateOptions` | "is before", "is on or after", "is between" |
| `StringOptions` | "contains", "matches", "is in" |
| `NumberOptions` | "is less than", "equals", "is between" |
| `ListOptions` | "contains", "contains any", "is in" |
| `CompletedOptions` | "completed", "in progress" |
| `PublicOptions` | "public", "not public" |

Also includes domain-specific boolean options: `DocumentOptions`, `ImageOptions`, `NotesOptions`, `TasksOptions`, `SignatureOptions`, `CheckboxOptions`.

### FilterDefinition

A dataclass-like class that serializes filter conditions for storage and transport. Contains the field, comparator, value(s), and label for display.

## Attributes (`definitions/attributes.py`)

Entity feature flags that control what functionality is available.

### Attribute Base Class

Each attribute has a `name`, `icon`, `title`, and `kind`. It tracks whether it's `active` based on the entity's configured attribute names. `None` names means all are active (inherits from model).

### Entity Attribute Enums

| Enum | Available Attributes |
|---|---|
| `ProjectAttributes` | tasks (ModelTasks), document |
| `PageAttributes` | tasks, document, photo, notes, files |
| `CategoryAttributes` | tasks, document, photo, notes, files |

### EntityAttributes

Top-level enum mapping entity kinds (`project`, `page`, `category`) to their attribute enum. `EntityAttributes[kind].initialize(entity, names)` creates a list of `Attribute` instances with active/inactive state.

## Ordering (`definitions/ordering.py`)

Column sort behavior for table displays:

| Value | Description |
|---|---|
| `LEXICAL` | Alphabetical string sorting |
| `NUMERIC` | Numeric sorting (timestamps, numbers) |
| `CATEGORICAL` | Sort by category/group (entity references) |
| `EXISTS` | Sort by presence/absence |
| `BOOLEAN` | Sort by boolean value |

## Asset Types (`definitions/asset.py`)

### AssetType

Types of stored assets: `IMAGE`, `HTML`, `TEXT`, `YDOC` (Yjs collaborative document), `FILE` (generic binary), `JSON`.

### AssetVisibility

Access levels: `PRIVATE` (requires signed URL) or `PUBLIC` (direct URL access).

## Search Facets (`definitions/facets.py`)

`SearchFacets` enum defines the available entity types for search result filtering. Each facet has a `name`, `icon`, `kind`, and `title`. Available facets: Categories, Pages, Projects, Tasks, Files, Forms, Users.

## Entity Types (`entities/types.py`)

`EntityType` maps registry names to concrete entity classes used by the
`Entities` singleton. A few names are aliases rather than separate classes.

| EntityType | Class | Notes |
|---|---|---|
| `USER` | `User` | User accounts. |
| `PROJECT` | `Project` | Top-level project/model instance. |
| `MODEL_TASK`, `MODEL` | `ModelTask` | `MODEL` is an alias. |
| `FILE`, `INGRESS` | `File`, `Ingress` | Uploaded files and CSV import files. |
| `FORM` | `Form` | Form schema model. |
| `CATEGORY`, `USERS` | `Category`, `UserCategory` | `USERS` is the reserved users category class. |
| `PAGE`, `TASK` | `Page`, `Task` | Instance entities. |
| `USER_GROUP`, `GROUP`, `PUBLIC_GROUP` | `UserGroup`, `PublicGroup` | `GROUP` aliases `USER_GROUP`. |
| `HOME` | `Home` | Root/home pseudo-entity. |
| `FILTER`, `CONDITION` | `Filter`, `Condition` | Saved filters and filter conditions. |
| `TASK_HISTORY`, `FORM_HISTORY`, `DOCUMENT_HISTORY` | History classes | History records in the history kind/bucket. |
| `NOTIFICATION`, `NOTE` | `Notification`, `Note` | Activity/notification records. |

## Import Stages (`definitions/ingress.py`)

`IngressStage` defines the CSV import workflow stages in order:

1. `PROCESS_CSV` -- parse and validate the CSV file
2. `CHOOSE_TYPE` -- select entity type (page or task)
3. `CHOOSE_PARENT` -- select parent entity (category or project)
4. `CHOOSE_FORM` -- select or create the form schema
5. `ASSIGN_COLUMNS` -- map CSV columns to form fields
6. `VERIFY_IMPORT` -- review and confirm
7. `IMPORTING` -- execute the import
8. `COMPLETED` -- finished

Uses `DefaultEnum` metaclass so unknown stages default to `PROCESS_CSV`.

## DefaultEnum (`definitions/default.py`)

A custom `EnumMeta` metaclass that returns the `DEFAULT` member instead of
raising `KeyError` on unknown lookups. Used by enums such as `IngressStage`,
`Action`, and cache `Search` for safe fallback behavior.

## Exceptions (`exceptions/`)

### Custom Exception Types

| Exception | Used For |
|---|---|
| `ValidationError` | Form/data validation failures |
| `AIException` | Vertex AI generation failures |
| `DeploymentSettingsError` | Invalid deployment-setting updates |
| `TaskCompletionError` | Task state transition failures |
| `NetworkError` | External service failures |
| `SiteImageError` | Image generation/processing failures |

### Error Capture (`capture()`)

`capture(error, context, level)` is the central error reporting function:

- **Production with `CAPTURE_ERRORS`**: Sends to Sentry after recursively
  bounding context and redacting recognized credentials and payload-bearing
  keys. Context dicts are attached as Sentry contexts, other values as extras.
  Request metadata is attached once and is structural only: no form/JSON/query
  values, full URLs, route-argument values, filenames, or arbitrary headers.
- **Development/Testing**: Prints to console with `pformat`.

### Debug Context (`get_debug_context()`)

Extracts debug information from an exception:

- Error type, message, timestamp
- Entity data if an entity is found in frame locals (`extract_entity_from_frames()`)
- Privacy-reduced Flask request structure (`extract_request_info()`)
- Full traceback string

### Jinja Error Context (`extract_jinja_error_context()`)

Specialized extraction for template errors -- includes the template filename, line number, and surrounding source code lines. Used by the error handler to show exactly where in a template the error occurred.

### Error Formatting (`format_debug_context_for_template()`)

Converts the raw debug context dict into a template-friendly format for rendering in development error pages.
