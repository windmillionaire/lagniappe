---
title: Site Image
related:
- site_settings
- site_deployment
---
Site Image supplies the icons for browser tabs, home-screen shortcuts, app manifests, and supported platform icon sizes. Upload one source image and Lagniappe generates the required variants.

Use a square image with a clear central subject and enough padding to remain recognizable when cropped or reduced. Small text and detailed photographs can be difficult to distinguish at favicon size.

## Publish the icons

Uploading stores the generated images in site metadata. Run `./setup.sh update` and deploy to copy them into the application's served static assets.

Browsers and devices can keep the old icon after deployment. If it remains, refresh the site or remove and add its home-screen shortcut again.

These are public application icons. They are separate from page images and document illustrations, and should not contain private workspace information. Changing a page image does not change the installation's icon set.
