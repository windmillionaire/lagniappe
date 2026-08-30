import { withTransition } from "../shared";
import { setIcon } from "../shared/icons";
import { AutofillUpload } from "./autofill";
import { buttons } from "./buttons";
import { primitives } from "./primitives";

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
 * @reason private compact photo prompt visibility helper
 */
const syncPhotoPrompt = (form, visible) => {
	const prompt = form.target.querySelector("[data-role='photo-prompt']");
	if (!prompt) return;
	prompt.dataset.visible = visible ? "true" : "false";
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
	} else {
		mobileToggles
			?.querySelector("[lp-show='photo:active']")
			?.setAttribute("data-visible", "true");
	}
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
	const activatePhoto = async ({
		transition = false,
		deferCommit = false,
	} = {}) => {
		const photoComponent = form.view.getComponent(photo);
		await photoComponent.activate("PagePhoto");
		widget = photoComponent.active;
		await photoComponent.prepareRender?.(true);
		/**
		 * @testable false
		 * @covered-by src/script/elements/sections.mjs::photoPrompt
		 * @reason private synchronous commit is exercised through photo prompt activation
		 */
		const commit = () => {
			ensurePhotoMobileToggle(form, section);
			syncPhotoPrompt(form, false);
			if (widget && callback) callback(widget, { transition });
		};
		if (deferCommit) return commit;
		commit();
	};

	if (typeof form.view.updateLayout === "function") {
		await form.view.updateLayout({
			secondary: photo,
			secondaryActive: true,
			activeTabId: form.view.mobile ? "photo" : null,
			mutate: () => activatePhoto({ transition: false, deferCommit: true }),
		});
		return widget;
	}

	form.view.elt.dataset.secondary = "true";
	form.view.elt.classList.remove("max-w-5xl");
	form.view.elt.classList.add("max-w-7xl");
	photo.dataset.visible = "true";
	photo.dataset.persistent = "true";
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
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_photo_prompt_upload_keeps_mobile_photo_tab_hidden_on_desktop
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_mobile_photo_prompt_rejoins_section_switching
 * @matrix pages : desktop-tabs image-add image-generate mobile-photo-tab photo-prompt
 */
const photoPrompt = (form) => {
	const section = form.target.querySelector("[data-role='photo-prompt']");
	if (!section) return null;

	const controller = new AbortController();
	const signal = controller.signal;
	const upload = section.querySelector("[data-role='photo-upload']");
	const generate = section.querySelector("[data-role='photo-generate']");

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

export const sections = {
	generateEntityForm,
	photoPrompt,
	generateImageForm,
	autofill,
};
