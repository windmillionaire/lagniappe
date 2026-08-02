/*! Third-party licenses: /third-party-licenses.txt */
import { C as Core } from '../core.js?v=be0d9638';
import '../connectivity.js?v=be0d9638';
import '../endpoints.js?v=be0d9638';
import '../errors.js?v=be0d9638';
import '../request.js?v=be0d9638';
import '../utilities.js?v=be0d9638';
import '../shell.js?v=be0d9638';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_home_mobile_dashboard_smoke
 * @features home
 * @dimensions load layout mobile
 */
class Home extends Core {
	constructor(elt) {
		super(elt);
		this.hash = "home";
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/home.mjs::Home._refreshStarred
	 * @covered-by src/script/views/home.mjs::Home._hideEmptyLists
	 * @reason polling reconciliation delegates collection work to focused home handlers
	 */
	async refreshSupplementalCollections(changes = []) {
		if (changes.some(({ type }) => ["star", "unstar"].includes(type))) {
			await this._refreshStarred();
		}
		if (changes.some(({ type }) => type === "delete")) this._hideEmptyLists();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
	 * @features starred
	 * @dimensions category project page
	 */
	async _refreshStarred() {
		const starredComponent = this.getComponent(
			document.getElementById("starred"),
		);
		if (!starredComponent) return;

		const existingWidget = starredComponent.widgets.StarredList;
		const widget =
			existingWidget || (await starredComponent.loadWidget("StarredList"));
		if (!widget) return;

		if (existingWidget) await starredComponent.load(widget);
		if (starredComponent.active === widget) await starredComponent.render(true);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_reload_uses_server_state_until_replay
	 * @features offline
	 * @dimensions server-first reload
	 */
	_hideEmptyLists() {
		for (const component of Object.values(this.components)) {
			for (const widget of Object.values(component.widgets)) {
				const target = widget.target;
				if (target?.tagName === "UL" && target.children.length === 0) {
					target.dataset.visible = "false";
				}
			}
		}
	}
}

export { Home as default };
