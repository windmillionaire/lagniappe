/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, r as request, w as withTransition } from '../foundation.js?v=b74a2211';
import '../upstreamUnavailable.js?v=b74a2211';
import '../connectivity.js?v=b74a2211';

class Results extends ShellView {
  /**
   * @template search/search.html::facet_button
   */
  async init() {
    await super.init();
    const url = new URL(window.location.href);
    this.selected = new Set(url.searchParams.getAll("kind"));
    this.facetsContainer = document.querySelector(
      "[data-role='facets']"
    );
    this.reset = document.querySelector("[data-role='reset']");
    this.facets = document.querySelectorAll(
      "[data-role='attribute']"
    );
    this.updateSelectionState();
    this.facets.forEach((facet) => {
      if (facet.dataset.kind && this.selected.has(facet.dataset.kind)) {
        facet.dataset.selected = "true";
      }
    });
    this.reset?.addEventListener("click", (e) => this.handleResetClick(e));
    this.facets.forEach((facet) => {
      facet.addEventListener("click", (e) => this.handleFacetClick(e, facet));
      facet.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          this.handleFacetClick(e, facet);
        }
      });
      facet.addEventListener("mouseleave", () => {
        facet.blur();
        delete facet.dataset.justSelected;
      });
    });
    this.addPagination();
  }
  /**
   * @template search/results.html::footer
   */
  addPagination() {
    document.querySelectorAll("[data-role='pagination']").forEach((pagination) => {
      pagination.addEventListener(
        "click",
        (e) => this.handlePaginationClick(e)
      );
    });
  }
  updateSelectionState() {
    if (!this.facetsContainer) return;
    this.facetsContainer.dataset.hasSelection = (this.selected.size > 0).toString();
  }
  updateResults(html) {
    const replacement = html.querySelector("[data-role='results']");
    if (!replacement) return;
    document.querySelector("[data-role='results']")?.replaceWith(replacement);
    this.addPagination();
  }
  /**
   * @template search/results.html::footer
   */
  async handlePaginationClick(e) {
    e.preventDefault();
    e.stopPropagation();
    const page = e.currentTarget?.dataset.page;
    if (page === void 0) return;
    const url = new URL(window.location.href);
    url.searchParams.set("page", page);
    const response = await request.get(url.toString());
    const html = response?.html;
    if (!html) return;
    await withTransition(
      () => {
        this.updateResults(html);
        window.history.pushState({}, "", url.toString());
      },
      { label: "search:paginate" }
    );
  }
  /**
   * @template search/search.html::main
   */
  async handleResetClick(e) {
    e.preventDefault();
    e.stopPropagation();
    this.selected.clear();
    const url = new URL(window.location.href);
    url.searchParams.delete("kind");
    url.searchParams.delete("page");
    const newUrl = url.toString();
    const response = await request.get(newUrl);
    const html = response?.html;
    if (!html) return;
    await withTransition(
      () => {
        this.facets.forEach((facet) => {
          facet.dataset.selected = "false";
          delete facet.dataset.justSelected;
        });
        this.updateSelectionState();
        this.updateResults(html);
        window.history.pushState({}, "", newUrl);
      },
      { label: "search:reset-facets" }
    );
  }
  /**
   * @template search/search.html::facet_button
   */
  async handleFacetClick(e, facet) {
    e.preventDefault();
    e.stopPropagation();
    const url = new URL(window.location.href);
    url.searchParams.delete("page");
    const kind = facet.dataset.kind;
    if (kind === void 0) return;
    const wasSelected = facet.dataset.selected === "true";
    if (this.selected.has(kind)) {
      this.selected.delete(kind);
      url.searchParams.delete("kind", kind);
    } else {
      this.selected.add(kind);
      url.searchParams.append("kind", kind);
    }
    const newUrl = url.toString();
    const response = await request.get(newUrl);
    const html = response?.html;
    if (!html) return;
    await withTransition(
      () => {
        const selected = this.selected.has(kind);
        facet.dataset.selected = selected ? "true" : "false";
        if (selected && !wasSelected) facet.dataset.justSelected = "true";
        this.updateSelectionState();
        this.updateResults(html);
        window.history.pushState({}, "", newUrl);
      },
      { label: "search:change-facet" }
    );
  }
}

export { Results as default };
