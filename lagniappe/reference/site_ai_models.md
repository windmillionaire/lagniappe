---
title: AI Models
category: site_administration
keywords:
  - ai models
  - primary model
  - utility model
  - image model
  - model selection
  - gemini
related:
  - ai_tools
  - site_settings
  - user_settings
  - analytics
---
Choose which models handle primary reasoning, lightweight parsing and summaries, and image generation across Lagniappe from **Admin → Site Settings → AI Models**.

Authorized administrators can adjust model choices anytime without running a setup update or redeploying.

## Model roles

- **Primary**: Powers AI Plans, workspace answers, form and page generation, autofill, and heavier reasoning workflows.
- **Utility**: Handles focused, lighter tasks such as supported parsing and file summaries.
- **Image**: Generates cover images or visuals where image generation is enabled.

## Applying and testing changes

- **Takes effect immediately**: New requests pick up saved model selections right away; any generation already in progress finishes on the model it started with.
- **Custom and available models**: If a previously saved model drops out of the discovered catalog, it can remain shown as a custom value. A model appearing in a catalog list does not by itself guarantee project quota or workflow compatibility—compare documentation and pricing links, then verify directly (ask a question for Primary, summarize a file for Utility, or generate a cover image for Image).
- Model settings never change any user's **None / Ask / Create** tier or workspace permissions.
