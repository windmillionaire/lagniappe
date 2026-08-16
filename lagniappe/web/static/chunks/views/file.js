/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=ba53d151';
import '../core-foundation.js?v=ba53d151';
import '../connectivity.js?v=ba53d151';
import '../foundation.js?v=ba53d151';

/**
 * @testable true
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_text_tab_renders_uploaded_text_content
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_text_file_renders_original_content_in_text_tab
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_image_shows_desktop_preview
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_renders_pdf_preview_widget
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_toolbar_navigates_pages
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_mobile_preview_uses_preview_tab
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_mobile_pdf_preview_renders_canvas
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
 * @tests tests_js/test_039_file_processing_reconciliation.py::test_file_view_shows_extract_reload_only_for_matching_unmounted_text
 * @features file
 * @dimensions load tabs text-tab file-mobile preview pdf-preview pdf-toolbar file-upload page-upload extract polling reload authoritative-remount linked-entities reverse-links badges
 * @pairs file:extract file:reload file:text-tab file:authoritative-remount
 */
class File extends Entity {
	constructor(node) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "info";
		this._reloadAfterExtract = this._reloadAfterExtract.bind(this);
	}

	async init() {
		await super.init();
		this.elt.addEventListener("click", this._reloadAfterExtract);
	}

	afterReconcileChange(change) {
		if (change.type !== "extract-complete") return;
		if (change.key !== this.key) return;
		if (this.elt.querySelector("#text")) return;

		this.showExtractReloadNotice();
	}

	showExtractReloadNotice() {
		const notice = this.elt.querySelector("[data-role='extract-reload']");
		if (!notice) return;

		notice.dataset.visible = "true";
		this.addFlash(notice);
	}

	_reloadAfterExtract(event) {
		const button = event.target.closest("[data-role='extract-reload-button']");
		if (!button) return;

		window.location.reload();
	}

	destroy() {
		this.elt.removeEventListener("click", this._reloadAfterExtract);
		super.destroy();
	}
}

export { File as default };
