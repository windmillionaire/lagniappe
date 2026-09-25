/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=b276e1c2';
import './controller.js?v=b276e1c2';
import './primitives.js?v=b276e1c2';
import './styles.js?v=b276e1c2';
import './icons.js?v=b276e1c2';
import './foundation.js?v=b276e1c2';
import './upstreamUnavailable.js?v=b276e1c2';
import './connectivity.js?v=b276e1c2';
import './loader.js?v=b276e1c2';
import './modal.js?v=b276e1c2';
import './reviewBar.js?v=b276e1c2';
import './representation.js?v=b276e1c2';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_owner_can_open_page_permissions_panel
 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_page_restrictions_save_drafts_and_show_each_source
 * @matrix pages : permission-gates permissions-panel access-restrictions explicit-submit group-restricted owner-restricted source-summary
 */
class PagePermissions extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Save Restrictions",
			submitting: "Saving Restrictions",
			submitted: "Restrictions Saved",
		};
	}
}

export { PagePermissions };
