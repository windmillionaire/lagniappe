/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=bdc1ce7d';
import './controller.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './foundation.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';
import './modal.js?v=bdc1ce7d';
import './representation.js?v=bdc1ce7d';

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
