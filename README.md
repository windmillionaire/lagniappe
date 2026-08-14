# Lagniappe

Lagniappe is a private, self-hosted workspace for structured records,
collaborative documents, tasks, files, search, and permissions. Read
[Why Lagniappe?](https://lagniappe.site/pages/public/74faecaf) for examples, or
explore the [user manual](https://lagniappe.site/manual/).

Lagniappe runs in your own Google Cloud project. By default, a quiet deployment
can sleep instead of charging for an idle server. The first visit after an idle
period may take a little longer while it wakes; once awake, normal use is fast
and interactive. Owners who prefer it can switch to always-on automatic
scaling in the manual's
[deployment settings](https://lagniappe.site/manual/personalization).

See the [release history](documentation/releases/) for version notes.

## Installation

The guided installer supports Windows, macOS, and Linux. It walks through the
required accounts and tools, cloud services, authentication, Redis, optional
features, and deployment.

Follow the [installation guide](https://lagniappe.site/manual/installation) for
current prerequisites and platform-specific instructions, including recovery
and repair. Updates and upgrades are covered in the manual's
[personalization guide](https://lagniappe.site/manual/personalization).

For installer architecture and implementation details, see
[INFRA_SETUP.md](documentation/INFRA_SETUP.md).

## Hosting and Support

The app deploys to Google App Engine in your cloud project. Its data and
supporting services remain under your provider accounts, so the operator is
responsible for monitoring, backups, provider retention settings, account
security, and usage costs.

Project support is best-effort through
[GitHub issues](https://github.com/windmillionaire/lagniappe/issues). General
questions may also be sent to
[support@lagniappe.site](mailto:support@lagniappe.site). Optional reports sent
to the maintainer are governed by the
[error-reporting privacy notice](ERROR_REPORTING_PRIVACY.md).

## Development

Lagniappe is currently a sole-maintainer project and is not accepting external
pull requests. Bug reports and focused feature suggestions are welcome through
GitHub issues.

To customize the code or work on Lagniappe itself, complete the ordinary
guided installation and then run:

```bash
./setup.sh development
```

Development workflows support Linux, macOS, and WSL2; use WSL2 when developing
on Windows. Start with the
[development setup](documentation/INFRA_SETUP.md#development-installation),
[testing guide](documentation/TESTING.md), and the
[documentation index](documentation/OVERVIEW.md).

The backend is Flask on Google Cloud Platform. The frontend is vanilla ES
modules bundled with Rollup and styled with Tailwind CSS.

## Security

Report suspected vulnerabilities privately as described in
[SECURITY.md](SECURITY.md). Do not include vulnerability details in a public
issue.

## License

Copyright (C) 2026 Caleb Wright. See [COPYRIGHT](COPYRIGHT).

Lagniappe is licensed under the
[GNU Affero General Public License, version 3 or later](LICENSE).
Third-party software, font, and icon notices are collected in
[THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).
