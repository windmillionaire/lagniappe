# Frontend Editor

The editor system (`src/script/elements/editor/`) provides a rich text document editor built on TipTap (ProseMirror). It supports two modes: collaborative editing with Yjs CRDT synchronization, and independent editing for standalone document fields.

## Architecture

```
Widget (CollaborativeDocument or IndependentDocument)
  ├── Editor (TipTap)
  │     ├── StarterKit (bold, italic, lists, links, etc.)
  │     ├── Extensions (CustomImage, FlashRemoteChanges, SelectionHighlight)
  │     └── Collaboration (Yjs -- collaborative mode only)
  ├── Toolbar
  │     ├── Tool buttons (OPTION_REGISTRY)
  │     ├── Menu dropdowns (FORM_REGISTRY)
  │     └── UserManager (collaborative mode only)
  └── Container (<div data-role="editor">)
```

## Document Types

### CollaborativeDocument (`collaborative.mjs`)

Used for entity documents (project documents, page documents). Manages real-time collaboration via Yjs CRDT and server-side update polling.

**Initialization flow:**

1. Creates the editor container and loading placeholder.
2. Initializes the TipTap editor with collaboration extensions.
3. Creates the toolbar when not headless or readonly.
4. If the widget has a fingerprint and a view `SyncManager`, fetches remote
   state through `SyncManager.state(this)`.
5. Waits for the editor `create` event and the container `loaded` attribute,
   then calls `sync()` to apply remote/offline state for mounted editors.
6. Mounted editors wait for the next paint before they mark the container
   `initialized`; headless replay marks `initialized` immediately after editor
   creation because there is no visible surface and background tabs may pause
   animation frames.
7. The view-scoped `SyncManager` handles polling and incoming push updates.

**Collaboration:**

- **Yjs document**: A `Y.Doc` instance tracks all changes as CRDT operations.
- **Update queue**: Local Yjs updates are queued in `updateQueue`. `syncData`
  merges the queue into a base64 delta and includes the full base64 `ydoc`
  snapshot for the server cache.
- **Remote updates**: Incoming updates arrive as `sync-update` window events
  handled by `SyncManager.receiveUpdate()`. Remote updates are applied to the
  Yjs doc with `"remote"` origin so they do not re-queue.
- **Saving**: On blur, the editor dispatches `sync-save`. `saveData` includes
  the merged delta, full `ydoc`, and rendered `html`; document HTML persistence
  happens through the `/sync` route when `html` is present.
- **Offline/headless replay**: `loadHeadlessWidget(...)` can instantiate a
  headless collaborative document so an offline record can merge and replay
  even when the widget is not mounted on the current route.

**State encoding:** Yjs state vectors and updates are serialized as base64
strings for transport. Shared helpers `base64ToUint8Array` and
`uint8ArrayToBase64` handle conversion.

### IndependentDocument (`independent.mjs`)

Used for standalone rich text fields (e.g. HTML form elements). No collaboration, no Yjs -- just TipTap with history (undo/redo).

**Saving**: On blur or destroy, if the HTML content has changed, it's saved via PUT. A `this.saving` guard prevents concurrent saves. Empty documents (`<p></p>` or `<p><br></p>`) are not saved.

### Shared Behavior

Both document types:

- Create a container div with `data-role="editor"` and the editor styles
- Wait for content to load before allowing edits (via the `loaded` attribute)
- Save on blur (with a `requestAnimationFrame` check to skip if focus moved to the toolbar or a dropdown)
- Have `destroy()` methods that clean up the editor, toolbar, and (for collaborative) the Yjs document

Independent documents also save on editor destroy and expose `hide()`/`show()`
for tab visibility. Collaborative documents leave visibility and final save
behavior to the widget/component lifecycle plus `SyncManager`.

## Editor Configuration (`editor.mjs`)

Two factory functions create TipTap `Editor` instances with shared extension configuration:

**`collaborativeEditor(target, ydoc)`** -- includes `Collaboration` extension (Yjs), `FlashRemoteChanges`, disables built-in history (Yjs handles undo).

**`independentEditor(target)`** -- enables built-in history, no collaboration extensions.

The document editors include: `StarterKit` (with underline; built-in links disabled), `CustomLink`, `Typography`, `Color`, `TextStyle`, `TextAlign`, `Superscript`, `Subscript`, `Youtube`, `CustomImage`, `FontFamily`, `SelectionHighlight`.

## Custom Extensions (`extensions/`)

### CustomLink (`link.mjs`)

Extends TipTap's `Link` extension to normalize internal application links.
Same-origin links are saved without the origin, open in the current tab, and
receive a `text-*` class based on the first route prefix. For example, a link to
`https://example.test/pages/abc` on the same origin is saved as `/pages/abc`
with `class="text-page"` and no `target`. TipTap's built-in click opener is
disabled so `CustomLink` can keep internal links in the current tab while
external links still use a new tab.

### CustomImage (`image.mjs`)

Extends TipTap's `Image` extension with width, float, and alignment attributes. Renders images with computed inline styles for positioning.

**Attributes:**

| Attribute | Default | Description |
|---|---|---|
| `width` | `"100%"` | Image width as percentage |
| `float` | `"none"` | CSS float (`left`, `right`, `none`) |
| `alignment` | `"center"` | Horizontal alignment when not floating |

**Commands:**

| Command | Description |
|---|---|
| `setImageWidth(delta)` | Adjust width by delta percentage (clamped 10-100%) |
| `setImageFloat(float)` | Set float direction, resets alignment to center |
| `setImageAlignment(alignment)` | Set alignment, resets float to none |

Uses a custom `addNodeView()` that creates an `<img>` element and updates attributes in-place without recreating the DOM node.

### FlashRemoteChanges (`remote.mjs`)

A ProseMirror plugin that briefly highlights text inserted by remote collaborators. When a Yjs update arrives with `y-sync$` metadata, the plugin diffs the old and new document text, finds changed regions, and adds inline decorations with the remote user's color. Decorations are removed after 1 second.

**How the diff works:**

1. For each transaction step, extracts text before and after
2. Finds the changed region via prefix/suffix matching
3. Maps text positions to document positions using a position map
4. Maps through remaining steps to get final positions
5. Creates inline decorations on the changed text nodes

### SelectionHighlight (`highlight.mjs`)

Preserves the visual selection highlight when focus moves away from the editor (e.g. to a toolbar form). Provides commands:

| Command | Description |
|---|---|
| `setSelectionHighlight()` | Saves the current selection range and shows a blue highlight decoration |
| `clearSelectionHighlight()` | Removes the highlight |
| `getSelectionHighlightRange()` | Returns `{from, to}` if a highlight is active |

## Toolbar (`toolbar.mjs`)

The toolbar is shared between both document types. It creates tool buttons and dropdown menus, manages toolbar forms (color picker, image settings, link insertion), and tracks the active editor state.

### Initialization

1. Creates a container div with toolbar styles
2. Loads primary tool buttons from `TOOLBAR_TOOLS` config (via `OPTION_REGISTRY`)
3. Loads dropdown menus from `TOOLBAR_MENUS` config
4. Creates a `UserManager` (for collaborative mode)
5. Binds delegated submit handler, editor click/key listeners, and document capture-click dismissal for toolbar forms

`Ctrl-K` / `Cmd-K` opens the link form while focus is inside the editor. Editor
click-away closes forms like `addLink`; the toolbar checks `Core.isDragging`
before closing so drag-selection does not immediately dismiss the form.

### Option and Form Registries (`options/registry.mjs`)

**`OPTION_REGISTRY`** maps command names to lazy-loaded toolbar button/menu item modules. These handle simple toggle commands (bold, italic, lists, undo/redo) and one-shot commands (heading, alignment, horizontal rule).

**`FORM_REGISTRY`** maps command names to lazy-loaded toolbar form modules. These provide inline forms that appear below the toolbar for more complex operations:

| Form | Purpose |
|---|---|
| `setColor` | Color picker |
| `setFontFamily` | Font family selector |
| `setImage` | Image width/float/alignment controls (shown when an image is selected) |
| `addLink` | Link picker for typing/pasting URLs, selecting global search results, editing one existing link, or clearing a link |
| `addImage` | Image upload/URL for inserting images |
| `addYouTube` | YouTube URL input |
| `generateText` | AI text generation prompt |

### State Tracking

On `selectionUpdate`, the toolbar reads the current marks and node attributes from the editor state and enables/disables the corresponding toolbar options. Image selection triggers the `setImage` form.

### Toolbar Dropdowns (`dropdowns.mjs`)

`toolbarDropdown(menu, items)` creates a menu button with a `Dropdown` combobox. After creating the dropdown, it queries the rendered `[role="option"]` elements and assigns them back to the toolbar items as `.button` references, so toolbar options can update their own visual state (active/inactive).

`createMenuButton(settings)` is the shared factory for menu trigger buttons (icon + label + chevron). Used by both `toolbarDropdown` and `UserManager`.

## UserManager (`users.mjs`)

Manages the list of active collaborators in a collaborative document. Displays a "Users" dropdown in the toolbar showing each user with a colored dot.

**User colors** are assigned from a predefined palette (`USER_COLORS` from config). Colors are stable per session -- once assigned to a user, they keep the same color. When colors run out, the palette resets.

**`setUsers(users)`** is called by `CollaborativeDocument.sync()` after
`/state` or `/register` returns a co-viewer list. It rebuilds the dropdown with
the current user list.

**`remoteUpdate(userHash)`** is called by `CollaborativeDocument.sync()` when a
remote `sync-update` arrives. It marks the collaborator responsible for the
latest remote edit so `FlashRemoteChanges` can use that user's color.

**`getUserColor(hash)`** returns the color assigned to a user, used by `FlashRemoteChanges` to color remote edit highlights.
