/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, r as request, w as withTransition } from '../foundation.js?v=bf7d4d98';
import '../upstreamUnavailable.js?v=bf7d4d98';
import '../connectivity.js?v=bf7d4d98';

class Analytics extends ShellView {
  async init() {
    await super.init();
    if (!this._analyticsToggle) {
      this._analyticsToggle = (event) => {
        const group = event.target;
        if (group?.matches?.("details[data-role='analytics-prefix']") && group.open) {
          void this._loadGroup(group);
        }
      };
      this.elt.addEventListener("toggle", this._analyticsToggle, true);
    }
    return this;
  }
  destroy() {
    if (this._analyticsToggle)
      this.elt.removeEventListener("toggle", this._analyticsToggle, true);
    super.destroy();
  }
  _click(event) {
    const target = event.target;
    const copyButton = target?.closest?.(
      "[data-role='ai-run-copy']"
    );
    if (copyButton && this.elt.contains(copyButton)) {
      event.preventDefault();
      event.stopPropagation();
      void this._copyRun(copyButton);
      return;
    }
    const clearButton = target?.closest?.(
      "[data-role='analytics-clear']"
    );
    if (clearButton && this.elt.contains(clearButton)) {
      event.preventDefault();
      event.stopPropagation();
      this._clearRecords(clearButton);
      return;
    }
    super._click(event);
  }
  async _loadGroup(group) {
    if (group.dataset.loaded === "true") return;
    const target = group.querySelector("[data-role='analytics-events']");
    const route = group.dataset.route;
    if (!target || !route) return;
    group.dataset.loaded = "true";
    const response = await request.get(route);
    if (!response?.ok) group.dataset.loaded = "false";
    const html = response?.ok && response.html ? response.html.body.innerHTML : '<div class="p-2 text-sm text-base-medium sm:px-6">Unable to load events.</div>';
    await withTransition(
      () => {
        target.innerHTML = html;
      },
      { label: "analytics:load-group" }
    );
  }
  async _copyRun(button) {
    const route = button.dataset.route;
    if (button.disabled || !route) return;
    const run = button.closest("[data-role='ai-run']");
    const status = run?.querySelector("[data-role='ai-run-copy-status']");
    const fallback = run?.querySelector(
      "[data-role='ai-run-json-fallback']"
    );
    if (!status || !fallback) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    status.textContent = "Loading run JSON\u2026";
    fallback.dataset.visible = "false";
    try {
      const response = await request.get(route);
      if (!response?.ok || !response.job_id) {
        status.textContent = "Unable to load run JSON. Try again.";
        return;
      }
      const {
        schema_version,
        job_id,
        telemetry_id,
        operation,
        ai_generations,
        ai_record_query_limit,
        ai_records_may_be_truncated
      } = response;
      const payload = {
        schema_version,
        job_id,
        telemetry_id,
        operation,
        ai_generations,
        ai_record_query_limit,
        ai_records_may_be_truncated
      };
      const text = JSON.stringify(payload, null, 2);
      try {
        await navigator.clipboard.writeText(text);
        status.textContent = "Run JSON copied.";
      } catch {
        fallback.value = text;
        fallback.dataset.visible = "true";
        fallback.focus();
        fallback.select();
        status.textContent = "Select and copy the JSON below.";
      }
    } catch {
      status.textContent = "Unable to load run JSON. Try again.";
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
  async _clearRecords(button) {
    const route = button.dataset.route;
    if (button.disabled || !route) return;
    const panel = button.closest(
      "[data-role='analytics-retention-panel']"
    );
    const dataset = panel?.dataset.dataset || "activity";
    const originalContent = button.innerHTML;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    this._setRetentionStatus(panel, "Clearing records...");
    const response = await request.delete(route);
    if (!response?.ok) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.innerHTML = originalContent;
      this._setRetentionStatus(
        panel,
        response?.error || "Unable to clear analytics records.",
        "delete"
      );
      return;
    }
    const refreshedPanel = await this._refreshDashboard(dataset);
    const datasetLabel = dataset === "ai" ? "AI generation" : "analytics";
    this._setRetentionStatus(
      refreshedPanel,
      `Deleted ${response.deleted} ${datasetLabel} ${response.deleted === 1 ? "record" : "records"}.`,
      "success"
    );
  }
  _setRetentionStatus(panel, message, kind = "page") {
    const status = panel?.querySelector(
      "[data-role='analytics-clear-status']"
    );
    if (!status) return;
    status.dataset.kind = kind;
    status.dataset.visible = "true";
    status.textContent = message;
  }
  async _refreshDashboard(dataset) {
    const response = await request.get(
      `${window.location.pathname}${window.location.search}`
    );
    const html = response?.html;
    if (!response?.ok || !html) return null;
    const view = html.querySelector("[lp-view][data-kind='analytics']");
    if (!view) return null;
    let panel;
    await withTransition(
      () => {
        this.elt.innerHTML = view.innerHTML;
        const retention = this.elt.querySelector(
          `[data-role='analytics-retention'][data-dataset='${dataset}']`
        );
        panel = retention?.querySelector(
          "[data-role='analytics-retention-panel']"
        );
        if (retention) retention.open = true;
      },
      { label: "analytics:refresh-dashboard" }
    );
    return panel || null;
  }
}

export { Analytics as default };
