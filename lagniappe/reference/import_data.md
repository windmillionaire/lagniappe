---
title: Importing CSV Data
manual_section: quickstart
related:
- create_form
- create_page
- tasks
- upload_file
---
Import Data turns a CSV spreadsheet into structured pages or tasks. Use it when each row represents a record or work item, rather than uploading the spreadsheet only as a reference file.

## Prepare and import

1. Use a header row with clear column names. Remove unrelated notes and blank rows, and keep one kind of record in the file.
2. Upload the CSV through **Import Data**. Lagniappe validates it and prepares row, column, and detected-type information.
3. Open the import wizard to choose the record type, select or build the relevant form, and map spreadsheet columns to fields.
4. The **Verify Page Import** or **Verify Task Import** step shows how rows will become records. If the fields and destination are correct, choose **Import**.

The wizard shows **Importing** while it creates records, then **Import Complete** when it finishes. The list below links to the created records and shows warnings or errors for individual rows. You can leave the page and reopen the import file later to see the results.

Choose field types that match the actual data. Dates, numbers, links, and repeated values need deliberate mapping. Workspace permissions still apply to destinations and created records. Use ordinary file upload instead when you only need to retain the original spreadsheet.
