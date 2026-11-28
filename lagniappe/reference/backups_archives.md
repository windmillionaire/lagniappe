---
title: Backups and Archives
category: site_administration
keywords:
  - backup
  - backups
  - archive
  - archives
  - restore
  - dry run
  - pitr
  - automatic backups
  - manual backups
  - portable archive
  - setup.sh
  - validate
related:
  - site_settings
  - import_data
  - site_deployment
  - site_maintenance
---
Check Google Cloud data protection status, prepare and create manual backups, validate portable archives, and restore data from the CLI.

Open **Navigation → Admin → Backups & Archives** to view backup status and copy exact CLI commands for your installation. **Backups & Archives** is a status view and command reference—creates, restores, and archive creation run via `./setup.sh` from your installation checkout, not in-browser buttons.

## Data protection and automatic backups

- **Data protection**: Reports Google Cloud Point-in-Time Recovery (PITR) status and native backup schedules configured on your project.
- **Automatic backups**: Managed and expired by Google Cloud on schedule. They protect the database, and an automatic backup must be **prepared as a manual backup** (using the prepare command shown in the panel) before Lagniappe can restore it together with its exact referenced files.

## Manual backups and restores

- **Manual backups**: Run `./setup.sh backup create` to capture one exact database snapshot plus copies of every referenced file version. Manual backups stay available until deleted (`./setup.sh backup delete BACKUP_ID`).
- **Restores**: Preflight checks (`./setup.sh restore BACKUP_ID --dry-run`) and restores (`./setup.sh restore BACKUP_ID`) run strictly via the CLI from your installation checkout.

## Portable archives

- Run `./setup.sh archive BACKUP_ID` to generate an independent, downloadable copy containing portable data, documents, and saved files.
- Validate any archive offline—without Google Cloud access—using `./setup.sh archive validate "ARCHIVE_PATH"`.
- A portable archive is an offline inspection and portability bundle; it is **not** itself the source used by `./setup.sh restore`. For importing or exporting workspace content tables, see [Importing and Exporting Data](/help/import_data) and [Installation](/manual/installation).
