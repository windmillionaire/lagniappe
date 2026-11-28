---
title: Analytics
category: site_administration
keywords:
  - analytics
  - site activity
  - observability
  - ai observability
  - metrics
  - page views
  - logins
  - tokens
  - in-flight ai
  - retention
  - activity records
related:
  - site_settings
  - ai_tools
  - site_maintenance
---
Monitor workspace usage and AI generation telemetry from the administrator Analytics dashboard.

Open **Navigation → Analytics** and use the **Analytics period** switcher to inspect activity over a chosen timeframe. Access is limited to authorized administrators and owners.

## Site Activity

When site activity analytics are enabled, you can inspect:

- **Summary metrics**: **Total Events**, **Page Views**, **Public Views**, **Logins**, and **Known Users**.
- **Top Pages**: Most-visited pages along with view counts for the selected period.
- **Activity**: Expandable route-prefix groups showing individual logged events.
- **Delete Activity Records**: A retention control letting authorized operators prune older records by age or clear stored activity records.

## AI Observability

When AI observability is enabled, Analytics also tracks how site AI features run:

- **Totals**: **Generations**, **Success** rate, **Requests**, **Tokens**, **Provider Result Chars**, **Validated Result Chars**, and **Original Files**.
- **Breakdowns**: **Known Tool Usage**, recent runs, and **Breakdowns by workflow, model, and contract**.
- **In-flight AI Generations**: Currently running or **Stale** provider calls with **Job ID**, **Provider Stage**, **Model**, **Requests**, and age (`Delete AI Records` lets you clear older telemetry).

See [Site Settings](/help/site_settings) and [AI Tools and Plans](/help/ai_tools) for configuration and AI workflow details.
