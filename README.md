# Lagniappe

Lagniappe is a private, self-hosted, searchable and permissioned workspace for structured records, collaborative documents, tasks and files. The goal of the project is to build a flexible website where an individual or a small business can store all their stuff cheaply, make parts of it accessible to certain groups (customers, employees, family members) in a controlled way without paying for every single person who uses it, and use AI for the boring things that it is great at, like turning photos and documents into structured data.

It's built with old and reliable web technology: web forms, server-rendered HTML, and a hard client/server split, so it is very secure and once installed should just run indefinitely without much maintenance, although if you'd like to read more about these casually asserted claims please visit [Security](https://lagniappe.site/manual/security) and [Under the Hood](https://lagniappe.site/manual/under-the-hood). Read [Why Lagniappe?](https://lagniappe.site/pages/public/74faecaf) for examples of uses it can be put to, or explore the [user manual](https://lagniappe.site/manual/) for some juicy ai-generated (yet human-reviewed!) documentation.

Lagniappe runs on Google Cloud, in your personal or business account, as a project that you own. It doesn't talk to any services other than Google Cloud or Redis unless you configure it to do so. The frontend itself only ever talks to Google services or the server itself, unless you enable error tracking (which I very much hope you do, it really does make the app better since I simply cannot anticipate everything that can be potentially done) in which case it also talks to Sentry.

By default it scales to zero, so the server can sleep when unused instead of racking up charges, and since App Engine is billed by uptime rather than by request, it isn't possible to be surprised by a big bill for unexpected traffic (unless, again, you configure it that way, which you can do in the app's [deployment settings](https://lagniappe.site/manual/personalization)). This doesn't eliminate ALL of the potential big-bill-surprises, if you use AI very heavily or store a ton of data you may well accumulate surprises, but normal usage is pretty well protected from large monetary oscillations.

You may wonder why this repo seems massively overbuilt for the use case that I've laid out above. The reasons are two: it's just plain easier to overbuild now, and that I really do believe that do-it-right-the-first-time is a better value than show-people-what-you're-working-with-and-fix-it-later. So the repo reflects those values.

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

Development workflows support Linux, macOS, and WSL2; use WSL2 when developing on Windows. Start with the [development setup](documentation/INFRA_SETUP.md#development-installation), [testing guide](documentation/TESTING.md), and the [documentation index](documentation/OVERVIEW.md).

The backend is Flask on Google Cloud Platform. The frontend is vanilla ES modules bundled with Rollup and styled with Tailwind CSS.

## Security

Report suspected vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not include vulnerability details in a public issue.

## License

Copyright (C) 2026 Caleb Wright. See [COPYRIGHT](COPYRIGHT).

Lagniappe is licensed under the [GNU Affero General Public License, version 3 or later](LICENSE). Third-party software, font, and icon notices are collected in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).
