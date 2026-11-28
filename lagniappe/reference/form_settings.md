---
title: Form Component Settings
category: pages_and_forms
keywords:
  - form settings
  - component settings
  - visibility rules
  - conditional logic
  - required field
  - input type
  - options
  - multiple select
  - placeholder
related:
  - form_builder
  - form_components
  - form_element_changes
---
Select any component on the Form Builder canvas to open its Settings panel and tailor its label, validation, choices, and conditional visibility.

Controls shown depend on the component type you clicked.

## Field configuration and rules

- **Title**: The visible label shown to users—keep it specific and self-explanatory.
- **Placeholder**: Example text shown inside an empty box (disappears as soon as someone starts typing).
- **Required**: Prevents completing a task (where supported) until a required value is provided.
- **Input Type**: Sets validation and input formatting for plain text, numbers, dates, times, emails, or phone numbers.
- **Options** and **Multiple**: Configure answer choices for **Radio** and **Select** fields, and enable **Multiple** when a dropdown allows more than one answer.
- **Visibility**: Show or hide a component dynamically based on answers in earlier controlling fields.

Multiple conditions referencing the *same* controlling field act as alternatives (`OR`); conditions referencing *different* controlling fields must all match (`AND`). Test conditional fields and **Status** alerts inside **Preview** before saving. For **Table** elements, finalize columns and choices before triggering conversions ([Converting and Deleting Form Elements](/help/form_element_changes)).
