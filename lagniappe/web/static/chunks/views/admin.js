/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=be0d9638';
import '../core.js?v=be0d9638';
import '../connectivity.js?v=be0d9638';
import '../endpoints.js?v=be0d9638';
import '../errors.js?v=be0d9638';
import '../request.js?v=be0d9638';
import '../utilities.js?v=be0d9638';
import '../shell.js?v=be0d9638';

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
