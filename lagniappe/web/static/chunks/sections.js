/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition, r as request } from './foundation.js?v=bed962f9';
import './connectivity.js?v=bed962f9';
import { s as setIcon } from './icons.js?v=bed962f9';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=bed962f9';
import { b as buttons } from './buttons.js?v=bed962f9';
import { p as primitives } from './primitives.js?v=bed962f9';

const AUTOFILL_DROPZONE_TEXT = "Click or drop to add a related image or a pdf";

/**
 * @testable infrastructure
 */
class AutofillUpload extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.parent = attributes.parent;
		this.target = attributes.target;
		this.name = "autofill";
		this.icon = "generate";
		this.uploadType = "file";
		this.deferred = true;

		this.messages = {
			submit: "Autofill Form",
			submitting: "Starting...",
			submitted: "Autofill queued",
		};

		this.context = uploadElement.contextUpload({
			text: AUTOFILL_DROPZONE_TEXT,
		});
		this.inputName = "autofill-file";
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this._initialized = false;
		this._click = this._click.bind(this);
	}

	init() {
		this.parent.target.addEventListener("click", this._click);
	}

	get submitGroup() {
		return this.target.querySelector("[data-role='autofill-submit-group']");
	}

	get submitButton() {
		return this.submitGroup?.querySelector("button[type='submit']") ?? null;
	}

	_canFallbackToMultipart() {
		return false;
	}

	_click(e) {
		const role = e.target.closest("button")?.dataset?.role;
		if (!["cancel-autofill", "show-autofill"].includes(role)) return;

		e.preventDefault();
		e.stopPropagation();

		withTransition(async () => {
			if (!this._initialized) {
				await super.init();
				this.target.append(this.submitGroup);
				this._initialized = true;
			}

			if (role === "show-autofill") {
				this.target.dataset.visible = "true";
				this.parent.form.toggleSubForm(this);
				this.target.querySelector("textarea").focus();
			} else if (role === "cancel-autofill") {
				this.target.dataset.visible = "false";
				this.parent.form.toggleSubForm();
				this.reset();
				this.target.querySelector("textarea").value = "";
			}
		});
	}

	get html() {
		return [this.context.element];
	}
}

/**
 * @testable infrastructure
 */
const autofill = (form) => {
	const section = form.target.querySelector('[data-role="autofill"]');
	if (!section) return null;

	const autofill = new AutofillUpload({
		target: section,
		parent: form,
	});
	autofill.init();
	form.destroyables.push(autofill);
	return section;
};

/**
 * @testable infrastructure
 */
const generateEntityForm = (form) => {
	const section = form.target.querySelector('div[data-role="generate"]');
	if (!section) return null;

	const manualButton = section.querySelector('button[data-role="manual"]');
	const aiButton = section.querySelector('button[data-role="ai"]');
	const generate = section.querySelector('[name="generate"]');
	const explain = form.target.querySelector('[data-role="explain"]');
	const description = section.querySelector('[name="user_description"]');
	const aiFields = section.querySelectorAll('[data-role="ai"]:not(button)');

	/**
	 * @testable false
	 * @covered-by src/script/elements/sections.mjs::generateEntityForm
	 * @reason mode toggling is private generate-form UI plumbing
	 */
	const setMode = (mode) => {
		form.target.dataset.mode = mode;
		aiFields.forEach((element) => {
			element.dataset.visible = mode === "ai" ? "true" : "false";
		});
		form.target.querySelectorAll('[data-role="manual"]').forEach((element) => {
			if (!section.contains(element)) {
				element.dataset.visible = mode === "manual" ? "true" : "false";
			}
		});
	};

	setMode(form.target.dataset.mode || "manual");

	if (explain && description) {
		description.addEventListener("input", () => {
			explain.dataset.visible = "true";
		});
	}

	aiButton.addEventListener("click", () => {
		withTransition(() => {
			const changed = !generate.checked;
			setMode("ai");
			manualButton.dataset.active = "false";
			aiButton.dataset.active = "true";
			generate.checked = true;
			if (changed)
				generate.dispatchEvent(new Event("change", { bubbles: true }));
			description.focus();
			if (explain && description?.value) {
				explain.dataset.visible = "true";
			}
		});
	});

	manualButton.addEventListener("click", () => {
		withTransition(() => {
			const changed = generate.checked;
			setMode("manual");
			manualButton.dataset.active = "true";
			aiButton.dataset.active = "false";
			generate.checked = false;
			if (changed)
				generate.dispatchEvent(new Event("change", { bubbles: true }));
			if (explain) {
				explain.dataset.visible = "false";
			}
		});
	});

	return section;
};

/**
 * @testable infrastructure
 */
const attributes = (form) => {
	const section = form.target.querySelector('[data-role="attributes"]');
	if (!section) return null;
	if (form.readonly) return section;

	const controller = new AbortController();
	const signal = controller.signal;

	section.querySelectorAll("[data-role='attribute']").forEach((attribute) => {
		const checkbox = attribute.querySelector("input[type='checkbox']");
		const attributeName = attribute.dataset.attribute;

		/**
		 * @testable false
		 * @covered-by src/script/elements/sections.mjs::attributes
		 * @reason selected-state update is private attributes-section plumbing
		 */
		const updateSelected = (selected = checkbox.checked) => {
			const wasSelected = attribute.dataset.selected === "true";
			attribute.dataset.selected = selected.toString();
			checkbox.checked = selected;
			// If just selected (false → true), suppress hover effects until mouseout
			if (!wasSelected && selected) {
				attribute.dataset.justSelected = "true";
			}
		};

		/**
		 * @testable false
		 * @covered-by src/script/elements/sections.mjs::attributes
		 * @reason live page-attribute persistence is private attributes-section plumbing
		 */
		const persistSelected = async (selected) => {
			if (!form.endpoints?.attribute || !attributeName) return;

			attribute.classList.add("opacity-50", "pointer-events-none");
			try {
				const route = form.endpoints.attribute(attributeName);
				const response = await request.put(route, { active: selected });
				if (!form.view.successfulResponse(response, form.component)) {
					updateSelected(!selected);
					return;
				}

				await reconcilePageAttribute(form, attributeName, selected);
			} catch (error) {
				updateSelected(!selected);
				form.component?.showError?.(
					error.message || "Unable to update page feature.",
				);
			} finally {
				attribute.classList.remove("opacity-50", "pointer-events-none");
			}
		};

		attribute.addEventListener(
			"click",
			async (e) => {
				e.stopPropagation();
				e.preventDefault();
				const selected = attribute.dataset.selected !== "true";
				updateSelected(selected);
				if (!form.endpoints?.attribute) {
					checkbox.dispatchEvent(new Event("change", { bubbles: true }));
				}
				await persistSelected(selected);
			},
			{ signal },
		);

		attribute.addEventListener(
			"keydown",
			async (e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.stopPropagation();
					e.preventDefault();
					const selected = !checkbox.checked;
					updateSelected(selected);
					if (!form.endpoints?.attribute) {
						checkbox.dispatchEvent(new Event("change", { bubbles: true }));
					}
					await persistSelected(selected);
				}
			},
			{ signal },
		);

		attribute.addEventListener(
			"mouseleave",
			() => {
				attribute.blur();
				delete attribute.dataset.justSelected;
			},
			{ signal },
		);
	});

	form.destroyables.push({
		destroy: () => controller.abort(),
	});

	return section;
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt UI state helper
 */
const setPhotoPromptBusy = (section, busy) => {
	section.dataset.busy = busy ? "true" : "false";
	section.querySelectorAll("button").forEach((button) => {
		button.disabled = busy;
	});
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt UI state helper
 */
const setPhotoPromptButtonIcon = (button, icon) => {
	const iconElement = button?.querySelector("[data-icon]");
	if (iconElement) setIcon(iconElement, icon);
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt error helper
 */
const showPhotoPromptError = (section, message) => {
	const error = section.querySelector("[data-role='photo-prompt-error']");
	if (!error) return;

	error.textContent = message || "";
	error.dataset.visible = message ? "true" : "false";
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt template helper
 */
const photoMobileToggleTemplate = (section) => {
	const template = section.querySelector(
		"[data-role='photo-mobile-toggle-template']",
	);
	return template?.content?.firstElementChild?.cloneNode(true) ?? null;
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private compact photo prompt attribute-state helper
 */
const setAttributeSelected = (form, name, selected) => {
	const attribute = form.target.querySelector(
		`[data-role='attribute'][data-attribute='${name}']`,
	);
	if (!attribute) return;

	attribute.dataset.selected = selected ? "true" : "false";
	const checkbox = attribute.querySelector("input[type='checkbox']");
	if (checkbox) checkbox.checked = selected;
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private page attribute visibility helper
 */
const setEntityAttributeActive = (form, name, active) => {
	if (typeof form.view.setAttributeActive === "function") {
		form.view.setAttributeActive(name, active);
		return;
	}

	form.view.elt
		.querySelectorAll(`[data-has-attribute][data-attribute='${name}']`)
		.forEach((element) => {
			const photoToggle = element.matches("button[lp-show='photo:active']");
			if (name === "photo" && photoToggle) return;
			element.dataset.hasAttribute = active ? "true" : "false";
		});
	setAttributeSelected(form, name, active);
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private photo secondary-card toggle helper
 */
const setPhotoToggleActive = (form, active) => {
	if (typeof form.view.setSecondaryToggleActive === "function") {
		form.view.setSecondaryToggleActive("photo", active);
		return;
	}

	form.view.elt
		.querySelectorAll(
			"[data-has-attribute][data-attribute='photo'][lp-show='photo:active']",
		)
		.forEach((element) => {
			element.dataset.hasAttribute = active ? "true" : "false";
		});
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private page-photo image-state helper
 */
const photoContainsImage = (form) => {
	return !!form.view.elt.querySelector(
		"#photo [data-role='existing-image'] img",
	);
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private compact photo prompt visibility helper
 */
const syncPhotoPrompt = (form, active) => {
	const prompt = form.target.querySelector("[data-role='photo-prompt']");
	if (!prompt) return;
	prompt.dataset.visible =
		active && !photoContainsImage(form) ? "true" : "false";
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt mobile-nav helper
 */
const ensurePhotoMobileToggle = (form, section) => {
	const mobileToggles = form.view.elt.querySelector(
		"[lp-nav][data-nav='mobile'] nav[data-nav='mobile']",
	);
	if (
		mobileToggles &&
		!mobileToggles.querySelector("[lp-show='photo:active']")
	) {
		const toggle = photoMobileToggleTemplate(section);
		if (toggle) {
			mobileToggles.prepend(toggle);
			form.view._mobileNav = null;
		}
	}
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::attributes
 * @reason private page attribute tab visibility helper
 */
const reconcileTabAttribute = async (form, name, active) => {
	const component = form.view.elt.querySelector(
		`[lp-component][data-has-attribute][data-attribute='${name}']`,
	);
	const selected = localStorage.getItem(`${form.view.hash}-active`);
	const activeTabId =
		!active &&
		(selected === component?.id || component?.dataset.visible === "true")
			? "info"
			: null;
	const secondary =
		component?.dataset.secondaryAttribute === "true" ? component : null;

	if (typeof form.view.updateLayout === "function") {
		await form.view.updateLayout({
			attribute: name,
			active,
			secondary,
			activeTabId,
		});
		return;
	}

	setEntityAttributeActive(form, name, active);
	if (activeTabId) {
		localStorage.setItem(`${form.view.hash}-active`, activeTabId);
		if (typeof form.view._renderLayout === "function") {
			await form.view._renderLayout();
		}
	}
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::attributes
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private page attribute DOM reconciliation helper
 */
const reconcilePageAttribute = async (form, name, active) => {
	if (name === "photo") {
		if (!active) {
			await hidePhotoLayout(form, {
				attributeActive: false,
				promptActive: false,
			});
		} else if (photoContainsImage(form)) {
			await showPhotoLayout(form, form.target);
		} else {
			await hidePhotoLayout(form, {
				attributeActive: true,
				promptActive: true,
			});
		}
		return;
	}

	await reconcileTabAttribute(form, name, active);
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt layout handoff helper
 */
const showPhotoLayout = async (form, section, callback = null) => {
	const photo = form.view.elt.querySelector("#photo");
	if (!photo) return null;

	let widget = null;
	/**
	 * @testable false
	 * @covered-by src/script/elements/sections.mjs::photoPrompt
	 * @reason private photo prompt activation runs inside the entity layout transition
	 */
	const activatePhoto = async ({ transition = false } = {}) => {
		ensurePhotoMobileToggle(form, section);
		syncPhotoPrompt(form, false);

		const photoComponent = form.view.getComponent(photo);
		await photoComponent.activate("PagePhoto");
		widget = photoComponent.active;
		if (widget && callback) await callback(widget, { transition });
	};

	if (typeof form.view.updateLayout === "function") {
		await form.view.updateLayout({
			attribute: "photo",
			attributeActive: true,
			secondary: photo,
			secondaryActive: true,
			activeTabId: form.view.mobile ? "photo" : null,
			mutate: () => activatePhoto({ transition: false }),
		});
		return widget;
	}

	form.view.elt.dataset.secondary = "true";
	form.view.elt.classList.remove("max-w-5xl");
	form.view.elt.classList.add("max-w-7xl");
	photo.dataset.visible = "true";
	photo.dataset.persistent = "true";
	setEntityAttributeActive(form, "photo", true);
	setPhotoToggleActive(form, true);
	if (form.view.mobile) {
		localStorage.setItem(`${form.view.hash}-active`, "photo");
	}
	await activatePhoto({ transition: true });
	if (typeof form.view._renderLayout === "function") {
		await form.view._renderLayout();
	} else {
		await form.view.getComponent(photo).render(true);
	}
	return widget;
};

/**
 * @testable false
 * @covered-by src/script/elements/sections.mjs::photoPrompt
 * @reason private compact photo prompt layout handoff helper
 */
const hidePhotoLayout = async (
	form,
	{ attributeActive = null, promptActive = false } = {},
) => {
	const photo = form.view.elt.querySelector("#photo");
	const activeTabId =
		localStorage.getItem(`${form.view.hash}-active`) === "photo"
			? "info"
			: null;

	if (typeof form.view.updateLayout === "function") {
		await form.view.updateLayout({
			attribute: attributeActive === null ? null : "photo",
			attributeActive,
			secondary: photo,
			secondaryActive: false,
			activeTabId,
			mutate: () => syncPhotoPrompt(form, promptActive),
		});
		return;
	}

	form.view.elt.dataset.secondary = "false";
	form.view.elt.classList.remove("max-w-7xl");
	form.view.elt.classList.add("max-w-5xl");
	if (attributeActive !== null) {
		setEntityAttributeActive(form, "photo", attributeActive);
	}
	setPhotoToggleActive(form, false);
	syncPhotoPrompt(form, promptActive);

	if (photo) {
		photo.dataset.visible = "false";
		photo.dataset.persistent = "false";
	}

	if (activeTabId) {
		localStorage.setItem(`${form.view.hash}-active`, activeTabId);
	}

	if (typeof form.view._renderLayout === "function") {
		await form.view._renderLayout();
	}
};

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_photo_prompt_upload_keeps_mobile_photo_tab_hidden_on_desktop
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_empty_page_photo_prompt_can_disable_photo_without_reload
 * @features pages
 * @dimensions photo-prompt image-generate image-add photo-disable desktop-tabs
 */
const photoPrompt = (form) => {
	const section = form.target.querySelector("[data-role='photo-prompt']");
	if (!section) return null;

	const controller = new AbortController();
	const signal = controller.signal;
	const upload = section.querySelector("[data-role='photo-upload']");
	const generate = section.querySelector("[data-role='photo-generate']");
	const disable = section.querySelector("[data-role='photo-disable']");

	/**
	 * @testable false
	 * @covered-by src/script/elements/sections.mjs::photoPrompt
	 * @reason private shared reveal handler for compact photo prompt actions
	 */
	const reveal = async (button, callback) => {
		showPhotoPromptError(section, "");
		setPhotoPromptButtonIcon(button, "spinner");
		setPhotoPromptBusy(section, true);

		try {
			await showPhotoLayout(form, section, callback);
		} catch (error) {
			showPhotoPromptError(
				section,
				error.message || "Unable to show image tools.",
			);
		} finally {
			setPhotoPromptBusy(section, false);
			setPhotoPromptButtonIcon(upload, "upload");
			setPhotoPromptButtonIcon(generate, "generate");
			setPhotoPromptButtonIcon(disable, "x");
		}
	};

	upload?.addEventListener(
		"click",
		async () => {
			await reveal(upload, (widget, options) => {
				widget.hideGenerateForm(options);
			});
		},
		{ signal },
	);

	generate?.addEventListener(
		"click",
		async () => {
			await reveal(generate, (widget, options) =>
				widget.showGenerateForm(options),
			);
		},
		{ signal },
	);

	disable?.addEventListener(
		"click",
		async () => {
			showPhotoPromptError(section, "");
			setPhotoPromptButtonIcon(disable, "spinner");
			setPhotoPromptBusy(section, true);

			try {
				const route =
					section.dataset.endpointDisable || form.endpoints.disablePhoto;
				const response = await request.put(route, { active: false });
				if (!form.view.successfulResponse(response, form.component)) return;

				await reconcilePageAttribute(form, "photo", false);
			} catch (error) {
				showPhotoPromptError(
					section,
					error.message || "Unable to turn photo off.",
				);
			} finally {
				setPhotoPromptBusy(section, false);
				setPhotoPromptButtonIcon(disable, "x");
			}
		},
		{ signal },
	);

	form.destroyables.push({
		destroy: () => controller.abort(),
	});

	return section;
};

/**
 * @testable infrastructure
 */
const generateImageForm = () => {
	const container = document.createElement("div");
	container.dataset.role = "generate-image";
	container.className = "flex flex-col gap-4";
	container.dataset.visible = "false";

	const usePageInfo = primitives.checkbox({
		label: "Use page info",
		name: "info",
		checked: true,
		kind: "page",
	});

	const prompt = primitives.textarea({
		name: "prompt",
		placeholder: "or describe the image you wish to create",
		rows: 3,
		kind: "page",
	});

	const submitGroup = document.createElement("div");
	submitGroup.dataset.role = "submit-group";
	submitGroup.className = "flex flex-wrap gap-2 w-full";

	submitGroup.appendChild(
		buttons.default({
			role: "cancel",
			text: "Cancel",
			kind: "default",
			type: "button",
		}),
	);

	submitGroup.appendChild(
		buttons.default({
			role: "generate",
			text: "Generate",
			kind: "page",
			type: "submit",
			icon: "generate",
		}),
	);

	container.append(usePageInfo, prompt, submitGroup);

	return {
		element: container,
		submitGroup: submitGroup,
		reset: () => {
			usePageInfo.checked = false;
			prompt.value = "";
		},
		visible: () => {
			return container.dataset.visible === "true";
		},
		hide: () => {
			container.dataset.visible = "false";
		},
		show: () => {
			container.dataset.visible = "true";
			prompt.focus();
		},
	};
};

const sections = {
	generateEntityForm,
	attributes,
	photoPrompt,
	generateImageForm,
	autofill,
};

export { sections as s };
