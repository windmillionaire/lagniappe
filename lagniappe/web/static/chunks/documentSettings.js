/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd163a0f';
import './foundation.js?v=bd163a0f';
import './connectivity.js?v=bd163a0f';
import { p as primitives } from './primitives.js?v=bd163a0f';
import { S as SelectBox } from './select2.js?v=bd163a0f';
import { F as FormElement } from './form2.js?v=bd163a0f';
import './icons.js?v=bd163a0f';
import './combobox.js?v=bd163a0f';
import './results.js?v=bd163a0f';
import './storage.js?v=bd163a0f';
import './formatting.js?v=bd163a0f';
import './submitter.js?v=bd163a0f';
import './baseForm.js?v=bd163a0f';
import './loader.js?v=bd163a0f';

const PUBLIC_DIRECTORY_ROOT = "__public_pages__";

const VISIBILITY = {
	public: "This page is public. It can be viewed at this URL: ",
	private: "This page is private.",
};

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_document_visibility_can_toggle_public_private
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_public_document_images_are_anonymous_and_revocable
 * @matrix pages : document-visibility private public
 * @matrix public-pages : metadata preview
 * @pair public-directory:category
 */
class DocumentSettings extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Public Page",
			submitting: "Updating",
			submitted: "Updated",
		};
	}

	get publicSettings() {
		try {
			return JSON.parse(this.target?.dataset.publicSettings || "{}");
		} catch {
			return {};
		}
	}

	get previewImages() {
		try {
			return JSON.parse(this.target?.dataset.previewImages || "[]");
		} catch {
			return [];
		}
	}

	get directoryCategories() {
		try {
			return JSON.parse(this.target?.dataset.directoryCategories || "[]");
		} catch {
			return [];
		}
	}

	get url() {
		return this.target?.dataset.url || null;
	}

	get formData() {
		const data = super.formData;
		if (data.get("directory-category") === PUBLIC_DIRECTORY_ROOT) {
			data.set("directory-category", "");
		}
		return data;
	}

	set url(value) {
		if (!this.target) return;
		if (value) {
			this.target.dataset.url = value;
		} else {
			delete this.target.dataset.url;
		}
	}

	get statusElement() {
		const status = document.createElement("p");
		status.className = "font-base font-semibold text-base-dark";
		if (this.url) {
			const a = document.createElement("a");
			a.dataset.kind = this.kind;
			a.className = STYLES.link.default;
			a.href = this.url;
			a.textContent = this.url;
			status.append(`${VISIBILITY.public}`, a, ".");
		} else {
			status.textContent = VISIBILITY.private;
		}
		return status;
	}

	get visibilityGroupElement() {
		const visibilityGroup = document.createElement("fieldset");
		visibilityGroup.className = "flex flex-row gap-4";

		const options = [
			{ label: "Public", value: "public", checked: !!this.url },
			{ label: "Private", value: "private", checked: !this.url },
		];

		options.forEach((option) => {
			visibilityGroup.appendChild(
				primitives.radio({
					label: option.label,
					name: "visibility",
					value: option.value,
					checked: option.checked,
					required: true,
					kind: this.kind,
				}),
			);
		});
		return visibilityGroup;
	}

	get discoveryElement() {
		const settings = this.publicSettings;
		const wrapper = document.createElement("div");
		wrapper.className =
			"flex flex-col gap-3 border-t border-base-light/60 pt-4";

		const heading = document.createElement("h3");
		heading.className = "font-semibold text-base-dark";
		heading.textContent = "Public discovery and sharing preview";

		const siteState = document.createElement("p");
		siteState.className = "text-sm text-base-medium";
		siteState.textContent =
			this.target?.dataset.siteIndexing === "true"
				? "Site discovery is on. This page can opt out or choose how it is grouped in the public directory."
				: "Site discovery is off. These settings will be ready if it is enabled later.";

		const marker = document.createElement("input");
		marker.type = "hidden";
		marker.name = "public-settings-present";
		marker.value = "true";

		const indexing = primitives.checkbox({
			label: "Allow this page to appear in search results",
			name: "allow-indexing",
			value: "true",
			checked: settings.allow_indexing !== false,
			kind: this.kind,
		});

		const title = primitives.input({
			label: "Public title (optional)",
			name: "public-title",
			value: settings.title || "",
			placeholder: "Uses the page name when blank",
			kind: this.kind,
		});
		title.querySelector("input").maxLength = 120;

		const description = primitives.textarea({
			label: "Public description (optional)",
			name: "public-description",
			value: settings.description || "",
			placeholder: "Uses an excerpt from the document when blank",
			rows: 3,
			kind: this.kind,
		});
		description.querySelector("textarea").maxLength = 300;

		const directoryCategory = primitives.select({
			label: "Public directory category",
			name: "directory-category",
			kind: this.kind,
			data: {
				preload: JSON.stringify([
					{
						id: settings.directory_category || PUBLIC_DIRECTORY_ROOT,
					},
				]),
			},
			options: [
				{
					label: "Public Pages",
					value: PUBLIC_DIRECTORY_ROOT,
					selected: !settings.directory_category,
				},
				...this.directoryCategories.map((category) => ({
					label: category.name,
					value: category.id,
					selected: category.id === settings.directory_category,
				})),
			],
		});
		directoryCategory.dataset.role = "directory-category";
		const directoryCategorySelect = new SelectBox(directoryCategory);
		directoryCategorySelect.init();
		this.destroyables.push(directoryCategorySelect);
		const categoryGuidance = document.createElement("p");
		categoryGuidance.className = "text-sm text-base-medium";
		categoryGuidance.textContent =
			"Choosing a category publishes that category name in the directory. Only categories already attached to this page are available.";

		wrapper.append(
			heading,
			siteState,
			marker,
			indexing,
			title,
			description,
			directoryCategory,
			categoryGuidance,
		);
		const previews = this.previewPickerElement;
		if (previews) wrapper.append(previews);
		return wrapper;
	}

	get previewPickerElement() {
		const images = this.previewImages;
		if (!images.length) return null;
		const selected = this.publicSettings.preview_image_asset || "";
		const fieldset = document.createElement("fieldset");
		fieldset.className = "flex flex-col gap-2";
		const legend = document.createElement("legend");
		legend.className = "mb-2 font-semibold text-base-dark";
		legend.textContent = "Sharing preview image";
		fieldset.append(legend);

		const options = [
			{
				name: "",
				url: this.target.dataset.siteImage,
				alt: "Site image",
			},
			...images,
		];
		const grid = document.createElement("div");
		grid.className = "grid grid-cols-2 gap-3 sm:grid-cols-3";
		for (const option of options) {
			const choice = primitives.radio({
				label: option.name ? option.alt || "Document image" : "Site image",
				name: "preview-image-asset",
				value: option.name,
				checked: option.name === selected,
				kind: this.kind,
			});
			choice.classList.add(
				"flex-col",
				"items-start",
				"rounded-md",
				"border",
				"border-base-light/70",
				"p-2",
			);
			const image = document.createElement("img");
			image.src = option.url;
			image.alt = option.alt || "";
			image.className = "aspect-video w-full rounded object-cover";
			choice.prepend(image);
			grid.append(choice);
		}
		fieldset.append(grid);
		return fieldset;
	}

	get html() {
		return [
			this.statusElement,
			this.visibilityGroupElement,
			this.discoveryElement,
		];
	}

	updated(response) {
		super.updated(response);
		const updatedTarget = response.html?.querySelector(
			`[data-widget='${this.name}']`,
		);
		if (updatedTarget) {
			this.url = updatedTarget.dataset.url || null;
			for (const name of [
				"publicSettings",
				"previewImages",
				"directoryCategories",
				"siteIndexing",
				"siteImage",
			]) {
				if (updatedTarget.dataset[name] !== undefined) {
					this.target.dataset[name] = updatedTarget.dataset[name];
				}
			}
		}
	}
}

export { DocumentSettings };
