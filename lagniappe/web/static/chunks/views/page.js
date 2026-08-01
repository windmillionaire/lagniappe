/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b3f50eb1';
import '../core.js?v=b3f50eb1';
import '../connectivity.js?v=b3f50eb1';
import '../endpoints.js?v=b3f50eb1';
import '../errors.js?v=b3f50eb1';
import '../request.js?v=b3f50eb1';
import '../utilities.js?v=b3f50eb1';
import '../shell.js?v=b3f50eb1';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
 * @features pages
 * @dimensions image-add photo-prompt
 */
class Page extends Entity {
	async init() {
		const taskId =
			new URLSearchParams(window.location.search).get("task") ||
			this.elt.dataset.focusTask;
		if (taskId) {
			localStorage.setItem(`${this.hash}-active`, "tasks");
			this.postRender = this._focusTask.bind(this, taskId);
		}

		await super.init();

		const photo = this.elt.querySelector("#photo");
		if (photo) {
			const component = this.getComponent(photo);
			const initiallyVisible =
				component?.active || this.isSecondaryCardVisible(photo);
			if (initiallyVisible && !component.active) {
				await component.activate("PagePhoto");
			}
		}
	}

	get secondaryCard() {
		if (this.elt.dataset.secondary !== "true") return null;
		return this.elt.querySelector("#photo");
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setAttributeActive
	 * @reason the photo card has attribute state distinct from image/secondary visibility
	 */
	secondaryCardForAttribute(attribute) {
		if (attribute === "photo") return this.elt.querySelector("#photo");
		return super.secondaryCardForAttribute(attribute);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._renderLayout
	 * @reason page-specific inactive attribute guard feeds the shared layout renderer
	 */
	_prerender(tabId) {
		const tab = this._tabElement(tabId);
		if (tab?.dataset.hasAttribute === "false") {
			tabId = this._defaultTabId;
		}
		return super._prerender(tabId);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_create_task_opens_from_tasks_section
	 * @features entity-layout
	 * @dimensions page-mobile task-create
	 */
	async _focusTask(taskId) {
		const taskTab = this.getComponent(this.elt.querySelector("#tasks"));
		await taskTab.activate("PageTaskList");
		await taskTab.render(true);
		await taskTab.active.focusTask(taskId);
		this._replaceFocusedTaskUrl();
		this.postRender = null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_route_rewrites_to_page_url_after_focus
	 * @features tasks
	 * @dimensions navigation canonical-url reload
	 */
	_replaceFocusedTaskUrl() {
		const pagePath = this.key ? `/pages/${this.key}` : window.location.pathname;
		history.replaceState(null, "", pagePath);
	}
}

export { Page as default };
