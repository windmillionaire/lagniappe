---
title: Category and Project Filters
category: pages_and_forms
keywords:
  - filters
  - filter bar
  - save filter
  - conditions
  - comparator
  - clear filter
  - structured query
related:
  - search
  - tables
  - create_category
  - create_project
  - form_settings
---
Slice pages in a Category or tasks in a Project using live structured conditions that update results automatically as you build them.

Use the filter bar inside a Category or Project when you want exact questions answered—such as open tasks assigned to someone, due dates in a range, or records matching specific form values.

## Building and saving filters

1. Open the Category or Project and click **+ Filter** (or open saved presets from the **Filters** dropdown).
2. Pick a record field or form field, choose a comparator, and enter or select a value—each rule appears as a removable chip, and matching rows update **automatically** alongside the current match count.
3. Remove individual chips, click **Clear** to reset, or click **Save filter** to keep useful filter combinations for quick reuse.

## How fields, columns, and permissions interact

- Category filters draw from the category's form context, while project filters include task fields and attached model-task forms. Multiple conditions narrow results together.
- Column choices (**Choose visible columns** / **Table controls**) are separate from filter rules: hiding a column does not drop a filter condition or alter who can read underlying data.
- Results only include items you are permitted to view. Newly saved record values can take a moment to show up in cached filters, and AI tools can run equivalent read-only structured queries within your permissions.
