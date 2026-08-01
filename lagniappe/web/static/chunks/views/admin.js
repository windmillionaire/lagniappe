/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b7488009';
import '../core.js?v=b7488009';
import '../connectivity.js?v=b7488009';
import '../endpoints.js?v=b7488009';
import '../errors.js?v=b7488009';
import '../request.js?v=b7488009';
import '../utilities.js?v=b7488009';
import '../shell.js?v=b7488009';

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
