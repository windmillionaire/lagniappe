/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b211475b';
import '../core.js?v=b211475b';
import '../connectivity.js?v=b211475b';
import '../endpoints.js?v=b211475b';
import '../errors.js?v=b211475b';
import '../request.js?v=b211475b';
import '../utilities.js?v=b211475b';
import '../shell.js?v=b211475b';

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
