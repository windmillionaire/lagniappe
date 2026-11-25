/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=b74a2211';
import './upstreamUnavailable.js?v=b74a2211';
import './connectivity.js?v=b74a2211';

const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") || "";
const token = () => document.querySelector("#token")?.value || "";
const analyticsEnabled = () => meta("analytics") === "true";
const navigationType = () => {
  const navigation = performance.getEntriesByType?.("navigation")?.[0];
  return navigation && "type" in navigation && typeof navigation.type === "string" ? navigation.type : "";
};
const pageTitle = () => meta("analytics-title") || document.querySelector("[lp-view] [data-nav='view'] [data-role='title']")?.textContent?.trim() || document.title.trim();
const viewData = (action) => {
  const view = document.querySelector("[lp-view]");
  return {
    action,
    path: window.location.pathname,
    query: window.location.search || "",
    page_title: pageTitle(),
    view_kind: view?.dataset.kind || "",
    entity_key: view?.dataset.key || "",
    entity_hash: view?.dataset.hash || "",
    index: view?.dataset.index || "",
    public_id: meta("analytics-public-id"),
    referrer: document.referrer || "",
    navigation_type: navigationType()
  };
};
class AnalyticsManager {
  get enabled() {
    return analyticsEnabled();
  }
  get mode() {
    return meta("mode");
  }
  async tag(action, payload = {}) {
    if (!this.enabled) return;
    const path = payload.path || window.location.pathname;
    if (/^\/(?:analytics|api|mcp|l)(?:\/|$)/.test(path)) {
      return;
    }
    try {
      const body = JSON.stringify({ ...payload, action, path });
      const send = () => fetch("/analytics/track", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": token(),
          "X-Lagniappe-Request": "true"
        },
        credentials: "include",
        keepalive: true,
        body
      });
      const response = await send();
      if (request.csrfFailed(response) && await request.token()) {
        await send();
      }
    } catch {
    }
  }
  view() {
    const action = meta("analytics-action") || "view";
    this.tag(action, viewData(action));
  }
}
const analytics = new AnalyticsManager();

export { analytics };
