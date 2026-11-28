---
title: Working Offline and Reconnecting
category: getting_started
keywords:
  - offline
  - reconnect
  - queued sync
  - pending sync
  - server offline
  - conflict
  - browser cache
  - service worker
  - install app
related:
  - documents
  - navigation
  - quick_tasks
  - notes
---
Keep editing open documents and queuing supported form submissions when your connection drops, then let Lagniappe sync cleanly when you reconnect.

The offline status indicator in the header reflects whether your browser can reach the server. See [Under the Hood](/manual/under-the-hood) for how browser storage and ETag invalidation work.

## Documents and forms offline

- **Documents**: Keep typing in an open collaborative document as usual. Edits remain safely in your browser and send automatically when connectivity returns.
- **Offline-capable forms**: Info updates, page tasks, creating pages, Home tasks, and Home notes queue changes when offline. Submit as usual—the button switches to **Queued Sync** (or shows **Pending sync** for new tasks and notes). Typing into fields alone without submitting does not save changes.
- **Server-required forms**: Actions that must reach the server show a disabled **Server Offline** button until the connection is back (which can also appear briefly while a server wakes from inactivity).

## Reconnecting and resolving conflicts

- When you return online, queued documents and form submissions replay in order.
- If a queued submission hits a newer server edit, Lagniappe pauses and asks you to choose which values to keep; later queued submissions wait until that choice is made.
- **Do not clear browser storage** before queued items finish sending, or waiting offline changes will be lost.

## Cached pages and installing

Cached views visited recently remain readable offline and refresh once you reconnect. Where supported by your browser, you can install Lagniappe to your home screen or desktop as an app for quick access.
