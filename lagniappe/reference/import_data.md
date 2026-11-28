---
title: Importing CSV Data
category: pages_and_forms
keywords:
  - import
  - import data
  - csv
  - spreadsheet
  - bulk import
  - verify page import
  - verify task import
  - export data
related:
  - create_form
  - create_page
  - tasks
  - upload_file
  - backups_archives
---
Turn a clean CSV spreadsheet into structured Pages or Tasks through Admin's Import Data workflow, with row-by-row validation before creating records.

Use **Import Data** when every row represents a workspace item rather than a file you just want to store on a page. If you are looking to create a downloadable snapshot or export of your workspace data, use **Backups & Archives** portable archives instead—see [Backups and Archives](/help/backups_archives).

## Preparing and running an import

1. Format your CSV with a clear header row, remove blank rows or stray summary notes, and keep one type of record per file.
2. Upload the CSV through **Navigation → Admin → Import Data** so Lagniappe can inspect headers, row counts, and inferred field types.
3. Open the import wizard to choose **Page** or **Task**, select or create a matching form, map CSV columns to form fields, and pick the target category/page context.
4. Review **Verify Page Import** or **Verify Task Import** carefully, then start **Import**.

While running, status displays **Importing** and finishes with **Import Complete**, listing created records alongside row-level warnings or errors (you can close the page and revisit the import file later). Choose accurate field types for dates, numbers, links, and multi-value columns, and keep in mind ordinary permissions govern every destination and record created.
