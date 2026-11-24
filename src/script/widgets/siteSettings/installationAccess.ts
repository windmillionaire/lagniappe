import { SiteSetting } from "./base.ts";

interface InstallationAccess {
	summary: string;
	state: "application-complete" | "pending" | "owner-managed";
	project_id: string;
	owner_email: string;
	installer_email: string;
	deployer_email: string;
	bootstrap_admin_email: string;
	runtime_service_account: string;
	project_iam_url: string;
	authentication_email?: {
		service: string;
		sender_email: string;
		login: string;
		configured: boolean;
		uses_installer: boolean;
	};
}

const display = (value: string | null | undefined) => value || "None";

/**
 * Presents the Owner-safe installation identity and cleanup boundary.
 *
 */
export class SiteInstallationAccess extends SiteSetting {
	declare _access?: InstallationAccess;

	updated(response: { installation_access?: InstallationAccess }) {
		this._access = response.installation_access;
	}

	postreconcile() {
		if (this._access) this._render(this._access);
	}

	_render(access: InstallationAccess) {
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
		if (
			statusTitle &&
			statusDescription &&
			access.state === "application-complete"
		) {
			statusTitle.textContent = "Application handoff configured";
			statusDescription.textContent =
				"The saved deployer is the permanent Owner and automatic installer bootstrap is closed. Confirm Cloud IAM separately before considering cloud cleanup complete.";
		} else if (statusTitle && statusDescription && access.state === "pending") {
			statusTitle.textContent = "Delegated handoff pending";
			statusDescription.textContent =
				"Keep the installer’s Google Cloud access until setup handoff completes. Removing it early can prevent deployment and managed-resource transfer.";
		} else if (statusTitle && statusDescription) {
			statusTitle.textContent = "Owner-managed installation";
			statusDescription.textContent =
				"The permanent Owner also installed this site; there is no separate delegated installer to hand off.";
		}

		const iamLink = this.target.querySelector<HTMLAnchorElement>(
			"[data-role='project-iam-link']",
		);
		if (iamLink) iamLink.href = access.project_iam_url;

		const email = access.authentication_email;
		const emailDetails = this.target.querySelector<HTMLElement>(
			"[data-role='authentication-email-details']",
		);
		if (emailDetails)
			emailDetails.dataset.visible = email?.configured ? "true" : "false";
		const emailWarning = this.target.querySelector<HTMLElement>(
			"[data-role='installer-email-warning']",
		);
		if (emailWarning) {
			emailWarning.dataset.visible = email?.uses_installer ? "true" : "false";
		}
		const handoffInstructions = this.target.querySelector<HTMLElement>(
			"[data-role='handoff-instructions']",
		);
		if (handoffInstructions) {
			handoffInstructions.dataset.visible =
				access.state === "pending" ? "true" : "false";
		}
	}
}
