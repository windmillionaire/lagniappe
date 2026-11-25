import { request } from "../shared/request.ts";
import { withTransition } from "../shared/transitions.ts";
import ShellView from "./base/shell.ts";

export default class Results extends ShellView {
	declare selected: Set<string>;
	declare facetsContainer: HTMLElement | null;
	declare reset: HTMLElement | null;
	declare facets: NodeListOf<HTMLElement>;

	/**
	 * @template search/search.html::facet_button
	 */
	async init() {
		await super.init();

		const url = new URL(window.location.href);
		this.selected = new Set(url.searchParams.getAll("kind"));
		this.facetsContainer = document.querySelector<HTMLElement>(
			"[data-role='facets']",
		);
		this.reset = document.querySelector<HTMLElement>("[data-role='reset']");
		this.facets = document.querySelectorAll<HTMLElement>(
			"[data-role='attribute']",
		);

		this.updateSelectionState();
		this.facets.forEach((facet) => {
			const isSelected = Boolean(
				facet.dataset.kind && this.selected.has(facet.dataset.kind),
			);
			facet.dataset.selected = isSelected ? "true" : "false";
			facet.setAttribute("aria-pressed", isSelected ? "true" : "false");
		});

		this.reset?.addEventListener("click", (e) => this.handleResetClick(e));

		this.facets.forEach((facet) => {
			facet.addEventListener("click", (e) => this.handleFacetClick(e, facet));

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
		document
			.querySelectorAll("[data-role='pagination']")
			.forEach((pagination) => {
				pagination.addEventListener("click", (e) =>
					this.handlePaginationClick(e),
				);
			});
	}

	updateSelectionState() {
		if (!this.facetsContainer) return;
		this.facetsContainer.dataset.hasSelection = (
			this.selected.size > 0
		).toString();
	}

	updateResults(html: Document) {
		const replacement = html.querySelector("[data-role='results']");
		if (!replacement) return;
		document.querySelector("[data-role='results']")?.replaceWith(replacement);
		this.addPagination();
	}

	/**
	 * @template search/results.html::footer
	 */
	async handlePaginationClick(e: Event) {
		e.preventDefault();
		e.stopPropagation();

		const page = (e.currentTarget as HTMLElement | null)?.dataset.page;
		if (page === undefined) return;

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
			{ label: "search:paginate" },
		);
	}

	/**
	 * @template search/search.html::main
	 */
	async handleResetClick(e: Event) {
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
					facet.setAttribute("aria-pressed", "false");
					delete facet.dataset.justSelected;
				});
				this.updateSelectionState();
				this.updateResults(html);
				window.history.pushState({}, "", newUrl);
			},
			{ label: "search:reset-facets" },
		);
	}

	/**
	 * @template search/search.html::facet_button
	 */
	async handleFacetClick(e: Event, facet: HTMLElement) {
		e.preventDefault();
		e.stopPropagation();

		const url = new URL(window.location.href);
		url.searchParams.delete("page");
		const kind = facet.dataset.kind;
		if (kind === undefined) return;
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
				facet.setAttribute("aria-pressed", selected ? "true" : "false");
				if (selected && !wasSelected) facet.dataset.justSelected = "true";
				this.updateSelectionState();
				this.updateResults(html);
				window.history.pushState({}, "", newUrl);
			},
			{ label: "search:change-facet" },
		);
	}
}
