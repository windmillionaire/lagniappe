---
title: Site Image
category: site_administration
keywords:
  - site image
  - favicon
  - app icon
  - pwa icon
  - branding
  - home screen icon
related:
  - site_settings
  - site_deployment
---
Site Image generates the icons used across browser tabs, home-screen shortcuts, PWA manifests, and supported platform icon sizes from one uploaded graphic.

Open **Admin → Site Settings → Site Image**, pick a square image with a clear central symbol and clean margins so tiny sizes stay legible, and upload it. Tiny text or busy photographs are tough to read at favicon scale.

## Publishing updated icons

- Uploading saves the generated icon set inside site metadata; run `./setup.sh update` and deploy to copy the icons into served static assets.
- Browsers and installed web apps frequently cache older favicons and home-screen icons—refresh the browser cache or re-add your home-screen shortcut after deploying if an old icon lingers.
- Because application icons are publicly served static assets, never use private workspace imagery here. Changing a page's cover photo does not alter site branding icons.
