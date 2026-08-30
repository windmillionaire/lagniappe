/*! Third-party licenses: /third-party-licenses.txt */
import { S as SiteSetting } from './base.js?v=bdbb928b';

/**
 * @testable false
 * @covered-by src/script/widgets/siteSettings/installationAccess.mjs::SiteInstallationAccess
 * @reason display fallback is exercised through the installation-access renderer
 */
const display = (value) => value || "None";

/**
 * Presents the Owner-safe installation identity and cleanup boundary.
 *
 * @testable true
 * @tests tests_e2e/008_users/test_008f_site_administrators.py::test_owner_installation_access_distinguishes_handoff_from_provider_cleanup
 * @matrix owner : authentication-email delegated-handoff identity-metadata provider-cleanup
 */
class SiteInstallationAccess extends SiteSetting {
	updated(response) {
		this._access = response.installation_access;
	}

	postreconcile() {
		if (this._access) this._render(this._access);
	}

	_render(access) {
		this.updateSummary(access.summary);
		this.target.dataset.state = access.state;

		const fields = {
			project: access.project_id,
			owner: access.owner_email,
			installer: access.installer_email,
			deployer: access.deployer_email,
			bootstrap: access.bootstrap_admin_email,
			runtime: access.runtime_service_account,
			"email-service": access.authentication_email?.service,
			"email-sender": access.authentication_email?.sender_email,
			"email-login": access.authentication_email?.login,
		};
		for (const [name, value] of Object.entries(fields)) {
			const field = this.target.querySelector(`[data-field='${name}']`);
			if (field) field.textContent = display(value);
		}

		const status = this.target.querySelector("[data-role='handoff-status']");
		const statusTitle = status?.querySelector("[data-role='status-title']");
		const statusDescription = status?.querySelector(
			"[data-role='status-description']",
		);
		if (access.state === "application-complete") {
			statusTitle.textContent = "Application handoff configured";
			statusDescription.textContent =
				"The saved deployer is the permanent Owner and automatic installer bootstrap is closed. Confirm Cloud IAM separately before considering cloud cleanup complete.";
		} else if (access.state === "pending") {
			statusTitle.textContent = "Delegated handoff pending";
			statusDescription.textContent =
				"Keep the installer’s Google Cloud access until setup handoff completes. Removing it early can prevent deployment and managed-resource transfer.";
		} else {
			statusTitle.textContent = "Owner-managed installation";
			statusDescription.textContent =
				"The permanent Owner also installed this site; there is no separate delegated installer to hand off.";
		}

		const iamLink = this.target.querySelector("[data-role='project-iam-link']");
		if (iamLink) iamLink.href = access.project_iam_url;

		const email = access.authentication_email || {};
		const emailDetails = this.target.querySelector(
			"[data-role='authentication-email-details']",
		);
		if (emailDetails)
			emailDetails.dataset.visible = email.configured ? "true" : "false";
		const emailWarning = this.target.querySelector(
			"[data-role='installer-email-warning']",
		);
		if (emailWarning) {
			emailWarning.dataset.visible = email.uses_installer ? "true" : "false";
		}
		const handoffInstructions = this.target.querySelector(
			"[data-role='handoff-instructions']",
		);
		if (handoffInstructions) {
			handoffInstructions.dataset.visible =
				access.state === "pending" ? "true" : "false";
		}
	}
}

export { SiteInstallationAccess };
