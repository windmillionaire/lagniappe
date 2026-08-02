/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b549327e';
import '../core.js?v=b549327e';
import '../connectivity.js?v=b549327e';
import '../endpoints.js?v=b549327e';
import '../errors.js?v=b549327e';
import '../request.js?v=b549327e';
import '../utilities.js?v=b549327e';
import '../shell.js?v=b549327e';

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
