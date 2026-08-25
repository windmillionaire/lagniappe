import Entity from "./base/entity";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
 * @matrix admin : page-load site-settings
 */
export default class Admin extends Entity {
	constructor(node) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "settings";
	}
}
