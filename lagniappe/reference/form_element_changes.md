---
title: Converting and Deleting Form Elements
related:
- form_builder
- form_settings
- task_history
---
Replace and Delete change the form's draft. Existing submissions are changed only after you save. Builder Undo reverses a draft change; it does not restore answers after a saved change has been applied.

## Convert values

Choose a supported component under **Replace With**, then choose **Convert**. Deterministic conversions use fixed rules: “42” can become a number, while “unknown” cannot. Values that do not fit the destination type are cleared.

Choices requiring AI need Create AI access and access to every affected page or task. Add conversion instructions before Save. For tables, configure destination columns first; for selects, configure options and Multiple. Conversion uses those final settings.

A component with no supported replacement offers Delete only.

## Delete and publish

Delete removes the field and, after Save, clears its answers from current submissions using that form. Original completed submissions and existing task history retain their recorded values and form generations.

While the update runs, affected submissions cannot be edited. The builder shows **Form update finished.** when it is done. If it shows **Form update needs attention**, read the error beside the message and use **Retry** to continue unfinished work.

Changed submissions can show a notice with before-and-after values. That notice clears when the submission is next updated or the task is completed or reopened.
