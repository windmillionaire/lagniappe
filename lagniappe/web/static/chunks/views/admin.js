/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b32ad33a';
import '../core.js?v=b32ad33a';
import '../connectivity.js?v=b32ad33a';
import '../endpoints.js?v=b32ad33a';
import '../errors.js?v=b32ad33a';
import '../request.js?v=b32ad33a';
import '../utilities.js?v=b32ad33a';
import '../shell.js?v=b32ad33a';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
 * @features admin
 * @dimensions page-load site-settings
 */
class Admin extends Entity {
	constructor(node) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "settings";
	}
}

export { Admin as default };
