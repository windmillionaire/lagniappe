/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b01d709d';
import '../core.js?v=b01d709d';
import '../connectivity.js?v=b01d709d';
import '../endpoints.js?v=b01d709d';
import '../errors.js?v=b01d709d';
import '../request.js?v=b01d709d';
import '../utilities.js?v=b01d709d';
import '../shell.js?v=b01d709d';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_tasks_attribute
 * @features projects
 * @dimensions attribute-model-tasks
 */
class Project extends Entity {
	get secondaryCard() {
		const modelTasks = this.elt.querySelector("#model-tasks");
		if (modelTasks?.dataset.hasAttribute === "false") return null;
		return modelTasks;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._renderLayout
	 * @reason project-specific inactive attribute guard feeds the shared layout renderer
	 */
	_prerender(tabId) {
		const tab = this._tabElement(tabId);
		if (tab?.dataset.hasAttribute === "false") {
			tabId = this._defaultTabId;
		}
		return super._prerender(tabId);
	}
}

export { Project as default };
