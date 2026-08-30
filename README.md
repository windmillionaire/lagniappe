# Lagniappe

Lagniappe is a private web app for individuals and small organizations that supports collaborative documents, files, structured records, contextual tasks, permissions, and search. It runs in a Google Cloud project and connects to a Redis Cloud database, both controlled by the owner. Optional, user-invoked AI is limited to the invoking user's existing permissions.

[Tour](https://lagniappe.site/pages/public/74faecaf) · [Manual](https://lagniappe.site/manual/) · [Install](https://lagniappe.site/manual/installation) · [Latest release](https://github.com/windmillionaire/lagniappe/releases/latest)

The tour and manual are public, although the demo examples linked to in the tour require you to log in.

## Contextual organization

The main unit of organization in Lagniappe is a page: a car, a job you're trying to get, an apartment you manage — anything, really. A page can have as much structure as you choose to give it, and its related tasks, files, images, and notes are attached directly to that page. Structure is defined by reusable forms that you build yourself or generate with AI and attach to pages or tasks. Because those forms provide structure without determining where something belongs, a page can cohesively organize many different kinds of information.

Rather than a folder containing a collection of files, a page represents a thing or a concept itself. Pieces of it can appear elsewhere — in search, filters, or project-tracked task lists — but they remain attached to that page. This fits the way I organize things in my own head, and it also happens to be convenient for always-optional AI features, because the relevant context is already bundled together.

| Structured information | Collaborative document |
|:---:|:---:|
| <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/01-milo-info.png" alt="Milo's structured adoption record"> | <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/02-milo-document.png" alt="A collaborative document"> |

| Contextual task | Attached files |
|:---:|:---:|
| <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/03-milo-task-detail.png" alt="A customizable task attached to Milo's page"> | <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/04-milo-files.png" alt="Two supporting PDF records attached to Milo's page"> |

All four views belong to Milo's one page: structured information, a collaborative document, work to be done, and supporting records.

## Who Lagniappe is for

Lagniappe is a great fit for an individual or organization that needs to be organized but has some trouble actually keeping things organized. If you're mildly technical and have a collection of side projects, clubs, or papers you don't want to lose — and you want to give a wide variety of people controlled access to selected material — you might like it.

It can also fit a small business or nonprofit that has to keep track of a lot, provide different views of that information to customers, vendors, employees, or others, and structure its data without having to type everything into a spreadsheet.

If you don't like the idea of hosting your data in GCP, don't want to be technically involved, or would simply rather have someone else manage your software, Lagniappe probably isn't a great fit. Installation and maintenance aren't especially complicated, but you are still the operator of your own deployment and Redis database, plus a domain registrar if you want a custom URL.

## More of the system

| Task history | Reviewable AI report |
|:---:|:---:|
| <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/05-task-history.png" alt="Structured completion history for a recurring relationship task"> | <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/08-ai-report.png" alt="A completed and reversible AI file-organization report"> |

| Form builder | Project filtering |
|:---:|:---:|
| <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/07-form-builder-permissions.png" alt="The form builder with reusable components and access restrictions"> | <img src="https://storage.googleapis.com/public-6d87544dcf8564696514a9ca9/06-project-task-filter.png" alt="A project filter with nested structured task results"> |

See the [release history](documentation/releases/) for version notes.

## Installation

The guided installer supports Windows, macOS, and Linux. It walks through the required accounts and tools, cloud services, authentication, Redis, optional features, and deployment.

Follow the [installation guide](https://lagniappe.site/manual/installation) for current prerequisites and platform-specific instructions, including recovery and repair. Updates and upgrades are covered in the manual's [personalization guide](https://lagniappe.site/manual/personalization).

For installer architecture and implementation details, see [INFRA_SETUP.md](documentation/INFRA_SETUP.md).

## Hosting and Support

The app deploys to Google App Engine in your cloud project. Its data and supporting services remain under your provider accounts, so the operator is responsible for monitoring, backups, provider retention settings, account security, and usage costs.

Project support is best-effort through [GitHub issues](https://github.com/windmillionaire/lagniappe/issues). General questions may also be sent to [support@lagniappe.site](mailto:support@lagniappe.site). Optional reports sent to the maintainer are governed by the [error-reporting privacy notice](ERROR_REPORTING_PRIVACY.md).

## Development

Lagniappe is currently a sole-maintainer project and is not accepting external pull requests. Bug reports and focused feature suggestions are welcome through GitHub issues. This is not necessarily because I don't want collaborators, but because I don't want to read pull requests. If you are interested in contributing to the project, and you've looked at enough of the code to know how much work it might require to get familiar with it, I'd be happy to hear from you, just [email me](mailto:caleb@lagniappe.site).

To customize the code or work on Lagniappe itself, complete the ordinary guided installation and then run:

```bash
./setup.sh development
```

Development workflows support Linux, macOS, and WSL2; use WSL2 when developing on Windows. Start with the [development setup](documentation/INFRA_SETUP_DEVELOPMENT.md), [testing guide](documentation/TESTING.md), and the [documentation index](documentation/OVERVIEW.md).

The backend is Flask on Google Cloud Platform. The frontend is vanilla ES modules bundled with Rollup and styled with Tailwind CSS.

## Security

Report suspected vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not include vulnerability details in a public issue.

## License

Copyright (C) 2026 Caleb Wright. See [COPYRIGHT](COPYRIGHT).

Lagniappe is licensed under the [GNU Affero General Public License, version 3 or later](LICENSE). Third-party software, font, and icon notices are collected in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).
