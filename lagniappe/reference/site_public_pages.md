---
title: Public Pages and Search Discovery
category: site_administration
keywords:
  - site public pages
  - public directory
  - search discovery
  - sitemap
  - robots.txt
  - update public page
  - allow this page to appear in search results
related:
  - document_settings
  - site_settings
  - search
---
Control whether published pages on this site can appear in the site-wide public directory, sitemap, and search engine discovery.

Published pages always have shareable direct links when toggled public—site-wide discovery adds the public catalog and search engine crawling layer on top.

## Site discovery vs. per-page settings

- Enable discovery under **Admin → Site Settings → Public Pages** when your site should expose the public directory and `sitemap.xml`. Only explicitly published metadata and selected display category labels appear in the catalog; private records and unrelated category memberships stay hidden.
- Turning site discovery off updates `robots.txt` and removes public discovery listings without revoking any already-published direct page URLs—use a page's own visibility toggle under [Document Settings](/help/document_settings) to make a page private.
- On an individual page, **Publishing** displays its public link and the **Allow this page to appear in search results** checkbox (**Update Public Page** saves changes). Note that search engines and link previews may keep cached snapshots until refreshed.
- Private workspace search remains completely separate: signed-in teammates search permitted workspace records and general Help from the header Search box ([Searching Lagniappe](/help/search)).
