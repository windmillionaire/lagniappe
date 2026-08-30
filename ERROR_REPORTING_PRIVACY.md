# Lagniappe Maintainer Error-Reporting Privacy Notice

**Applies to:** Lagniappe 1.1.0

**Effective date:** July 27, 2026

**Contact:** Caleb Wright, [privacy@lagniappe.site](mailto:privacy@lagniappe.site)

## Scope

Lagniappe is self-hosted. Normal workspace activity and content stay with the
services selected by the operator of each Lagniappe instance.

This notice applies only when an instance operator chooses to send
privacy-reduced error reports to the default Sentry project operated by the
Lagniappe maintainer. It does not apply when an operator disables error
reporting or supplies a Sentry DSN that the operator owns. An operator using
their own DSN is responsible for that reporting destination and its privacy
terms.

## Choice and control

Maintainer error reporting is off by default. Setup explains the reporting
boundary and asks the operator to opt in. Using Lagniappe does not require
error reporting.

The operator can disable reporting at any time by setting `CAPTURE_ERRORS` to
`False` and redeploying the instance. Disabling reporting stops new reports; it
does not recall reports already delivered to Sentry.

The operator is responsible for deciding whether reporting is appropriate for
the instance and for informing its users when required.

## Who handles reports

Caleb Wright, the Lagniappe maintainer, determines how reports sent to the
default maintainer destination are used. Sentry, operated by Functional
Software, Inc., acts as the maintainer's service provider and data processor
for report contents.

Sentry may use subprocessors and process data in locations described in its
[Data Processing Addendum](https://sentry.io/legal/dpa/),
[subprocessor list](https://sentry.io/legal/subprocessors/), and
[Privacy Policy](https://sentry.io/privacy/).

## Why reports are used

Reports are used to:

- find, reproduce, diagnose, and fix errors;
- investigate reliability and performance problems;
- distinguish repeated failures from isolated failures; and
- verify that a fix works in later Lagniappe releases.

Reports are not used for advertising, user profiling, or selling personal
information.

## Diagnostic data that may be reported

Depending on where and how a failure occurs, a report may contain:

- error types, error messages, stack traces, source locations, timestamps,
  release information, and environment information;
- route templates, endpoint names, HTTP methods, route-parameter names, query
  field names and counts, request content type, and bounded request-size
  metadata;
- a short allowlist of diagnostic HTTP headers;
- browser, operating-system, runtime, device, application, trace, transaction,
  span, performance, and profiling information;
- page paths and bounded interface context such as element tags, identifiers,
  classes, or data attributes; and
- metadata added by enabled third-party integrations before Lagniappe's final
  filtering step.

Sentry necessarily receives network information, including the source IP
address used to deliver a report, even when Lagniappe does not deliberately
attach an IP address or user identity to the event.

## Data Lagniappe filters before sending

Lagniappe disables Sentry's default collection of personally identifiable
information and applies additional filtering intended to remove or reduce:

- form and JSON values, request and response bodies, and query values;
- uploaded filenames, file contents, full URLs, and referrers;
- authorization values, cookies, arbitrary headers, and Sentry user identity
  context;
- recognized passwords, access tokens, API keys, private keys, and similar
  credentials; and
- oversized strings, collections, and deeply nested diagnostic context.

Filtering reduces exposure but cannot guarantee anonymity. In particular,
unstructured error messages, stack traces, page paths, element identifiers,
classes, data attributes, integration metadata, or unexpected third-party
context can contain information that identifies an instance, user, record, or
other person. Operators should not enable maintainer reporting when even
privacy-reduced diagnostics must not leave the instance.

## Sharing and access

Reports are available to the Lagniappe maintainer and to Sentry and its
subprocessors as needed to provide and secure the Sentry service. Reports may
also be disclosed when required by law or necessary to protect rights,
security, or the integrity of the service.

Reports are not intentionally published. If a report leads to a public issue,
code change, test, or release note, the maintainer will use the minimum
diagnostic detail needed and will not intentionally copy personal information
or credentials into the public record.

## Retention and deletion

The maintainer relies on the automated retention period applied to the
maintainer's Sentry account and does not keep a separate archive of raw
reports. The applicable Sentry retention period may change with Sentry's
service terms, plan, or account configuration. Reports and issue data may be
deleted earlier when they are no longer useful or when a valid deletion
request can be matched to them. The current account retention setting is
available on request from the contact listed in this notice.

Sentry may retain limited service, security, backup, or legally required data
according to its own terms and deletion processes. Diagnostic facts that no
longer identify a person or instance may remain in source-code changes, tests,
release notes, or issue history.

To request access to or deletion of a report, email
[privacy@lagniappe.site](mailto:privacy@lagniappe.site) with the approximate
date and time of the event and any Sentry event identifier shown to you. You
may also include the instance hostname if you are comfortable doing so. Do not
send passwords, tokens, private keys, workspace content, or other sensitive
data with the request.

Because Lagniappe removes deliberate user identity fields and different
installations can produce similar errors, the maintainer may be unable to
identify a particular person's or instance's report without enough matching
information. Sentry may also require deletion of an entire grouped issue
rather than one immutable event.

## Security

Lagniappe sends reports to Sentry over HTTPS. Access to the maintainer project
is restricted through the maintainer's Sentry account. No filtering,
transmission, or storage system can guarantee complete security.

## Changes to this notice

Changes will be recorded in the repository history. The effective date and
applicable Lagniappe version at the top of this notice will be updated when the
notice materially changes.

Questions or privacy requests may be sent to Caleb Wright at
[privacy@lagniappe.site](mailto:privacy@lagniappe.site).
