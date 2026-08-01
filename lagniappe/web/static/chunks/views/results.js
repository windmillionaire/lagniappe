/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from '../request.js?v=b3f50eb1';
import { S as ShellView } from '../shell.js?v=b3f50eb1';
import '../errors.js?v=b3f50eb1';
import '../connectivity.js?v=b3f50eb1';

/**
 * @testable infrastructure
 */
class Results extends ShellView {
	/**
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_facets_displayed
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_facet_selection_visual_state
	 * @features search
	 * @dimensions facets facet-state
	 * @template search/search.html::facet_button
	 */
	async init() {
		await super.init();

		const url = new URL(window.location.href);
		this.selected = new Set(url.searchParams.getAll("kind"));
		this.facetsContainer = document.querySelector("[data-role='facets']");
		this.reset = document.querySelector("[data-role='reset']");
		this.facets = document.querySelectorAll("[data-role='attribute']");

		this.updateSelectionState();
		this.facets.forEach((facet) => {
			if (this.selected.has(facet.dataset.kind)) {
				facet.dataset.selected = "true";
			}
		});

		this.reset.addEventListener("click", (e) => this.handleResetClick(e));

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
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_pagination_controls_visible
	 * @features search
	 * @dimensions pagination
	 * @template search/results.html::footer
	 */
	addPagination() {
		document
			.querySelectorAll("[data-role='pagination']")
			.forEach((pagination) => {
				pagination.addEventListener("click", (e) =>
					this.handlePaginationClick(e),
				);
			});
	}

	updateSelectionState() {
		this.facetsContainer.dataset.hasSelection = (
			this.selected.size > 0
		).toString();
	}

	updateResults(html) {
		document
			.querySelector("[data-role='results']")
			.replaceWith(html.querySelector("[data-role='results']"));
		this.addPagination();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_next_page
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_previous_page
	 * @features search
	 * @dimensions pagination-next pagination-previous
	 * @template search/results.html::footer
	 */
	async handlePaginationClick(e) {
		e.preventDefault();
		e.stopPropagation();

		const page = e.currentTarget?.dataset.page;
		if (page === undefined) return;

		const url = new URL(window.location.href);
		url.searchParams.set("page", page);
		const response = await request.get(url.toString());
		this.updateResults(response.html);
		window.history.pushState({}, "", url.toString());
	}

	/**
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_clear_facet_filter
	 * @features search
	 * @dimensions clear-facet
	 * @template search/search.html::main
	 */
	async handleResetClick(e) {
		e.preventDefault();
		e.stopPropagation();

		this.facets.forEach((facet) => {
			facet.dataset.selected = "false";
			delete facet.dataset.justSelected;
		});
		this.selected.clear();
		this.updateSelectionState();

		const url = new URL(window.location.href);
		url.searchParams.delete("kind");
		url.searchParams.delete("page");
		const newUrl = url.toString();
		const response = await request.get(newUrl);
		this.updateResults(response.html);
		window.history.pushState({}, "", newUrl);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_click_facet_filters_results
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_facet_selection_visual_state
	 * @features search
	 * @dimensions facet-filter url-state results facet-state
	 * @template search/search.html::facet_button
	 */
	async handleFacetClick(e, facet) {
		e.preventDefault();
		e.stopPropagation();

		const url = new URL(window.location.href);
		url.searchParams.delete("page");
		const kind = facet.dataset.kind;
		const wasSelected = facet.dataset.selected === "true";

		if (this.selected.has(kind)) {
			this.selected.delete(kind);
			url.searchParams.delete("kind", kind);
			facet.dataset.selected = "false";
		} else {
			this.selected.add(kind);
			url.searchParams.append("kind", kind);
			facet.dataset.selected = "true";

			if (!wasSelected) {
				facet.dataset.justSelected = "true";
			}
		}

		this.updateSelectionState();
		const newUrl = url.toString();
		const response = await request.get(newUrl);
		this.updateResults(response.html);
		window.history.pushState({}, "", newUrl);
	}
}

export { Results as default };
