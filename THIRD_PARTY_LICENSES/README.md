# Third-party licenses and notices

Lagniappe's own code is licensed under AGPL-3.0-or-later. The assets and
bundled code listed here retain their upstream licenses.

## Fonts and icons

| Asset | Upstream | License |
| --- | --- | --- |
| Material Symbols Rounded subset | Google Material Symbols v363 | [Apache License 2.0](material-symbols-LICENSE.txt) |
| Bitter webfonts | Google Fonts `ofl/bitter` | [SIL OFL 1.1](bitter-OFL.txt) |
| Source Sans 3 webfonts | Google Fonts `ofl/sourcesans3` | [SIL OFL 1.1](source-sans-3-OFL.txt) |
| Open Sans math and symbol subsets | Google Fonts `ofl/opensans` | [SIL OFL 1.1](open-sans-OFL.txt) |

The Material Symbols subset source request, included glyphs, axes, upstream
version, and SHA-256 digest are recorded in
`src/fonts/material-symbols-rounded.json`.

## Generated browser code

The production browser bundles include code from Floating UI,
Sentry, Tiptap and ProseMirror, Yjs, Sortable, PDF.js, and their small runtime
dependencies. Their notices are collected in
[browser-bundle-NOTICES.md](browser-bundle-NOTICES.md).

All Tiptap packages used by Lagniappe are public MIT-licensed packages. No
Tiptap Pro or other commercially licensed Tiptap extension is included.

PDF.js worker and decoder files are copied separately during the build. Their
additional notices are collected in
[pdfjs-dist-NOTICES.md](pdfjs-dist-NOTICES.md).

Exact JavaScript package versions are recorded in `package-lock.json`.
Server-side Python packages and JavaScript build tools are installed as
separate dependencies rather than incorporated into Lagniappe's source; their
license files remain in their respective distributions.
