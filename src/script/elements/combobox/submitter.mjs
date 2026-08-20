/**
 * @testable true
 * @tests tests_js/test_016_combobox_frontend.py::test_submitter_clear_can_suppress_change_notification
 * @features combobox
 * @dimensions clear-notification
 */
export const Submitter = (Combobox) =>
	/**
	 * @testable infrastructure
	 */
	class extends Combobox {
		init() {
			this.multiple ??= JSON.parse(this.parent.dataset.multiple || "false");
			this.create = !!this.create;
			if (this.element?.name) {
				this.name = this.element.name;
				this.element.removeAttribute("name");
			}

			let preload = JSON.parse(this.preload || "[]");
			preload = Array.isArray(preload) ? preload : [preload];

			preload.forEach((option) => {
				this.addOption(option, true);
			});
			this.updatePanel(this.results.create(this.items || []));
			this.updateSelect(true);

			super.init();
		}

		setupSelect() {
			if (this.select) {
				this.select.innerHTML = "";
				return;
			} else {
				this.select = document.createElement("select");
				this.element.after(this.select);
				this.select.multiple = this.multiple;
				this.select.name = this.name;
				this.select.style.display = "none";
			}
		}

		updateSelect(preloading = false) {
			this.setupSelect();

			this.values.forEach((value) => {
				const option = document.createElement("option");
				option.value = value;
				option.selected = true;
				this.select.appendChild(option);
			});

			if (this.options.length > 0) {
				this.updatePlaceholder();
			}

			if (!preloading) {
				this.dispatchChangeEvents();
			}
		}

		dispatchChangeEvents() {
			const event = new CustomEvent("updated", {
				bubbles: true,
				detail: {
					name: this.name,
					options: Object.fromEntries(
						this.options
							.filter((o) => this.values.has(o.id))
							.map((o) => [o.id, o]),
					),
				},
			});
			this.element.dispatchEvent(event);
			this.select.dispatchEvent(new Event("change", { bubbles: true }));
		}

		updatePlaceholder() {
			let displaySet;
			const focusedOption = this.focusedOption();
			if (focusedOption && !this.multiple) {
				displaySet = new Set([focusedOption.dataset.id]);
			} else if (focusedOption && this.multiple) {
				displaySet = new Set([...this.values, focusedOption.dataset.id]);
			} else {
				displaySet = new Set(this.values);
			}
			const totalCount = displaySet.size;

			if (totalCount === 0) {
				this.element.placeholder = this.placeholder;
				this.element.dataset.values = "false";
				return;
			}

			this.element.dataset.values = "true";

			const options = Array.from(displaySet)
				.map((id) => this.options.find((o) => o.id === id))
				.filter(Boolean);

			const names = options.map((o) => o.name).join(", ");
			const kinds = new Set(
				options.map((o) => o.kind).filter((k) => k && k !== "default"),
			);
			if (kinds.size === 1) {
				this.element.dataset.kind = Array.from(kinds)[0];
			} else {
				this.element.dataset.kind = this.kind || "default";
			}
			this.element.value = "";
			this.element.placeholder = names || this.placeholder;
		}

		focusOption(option) {
			super.focusOption(option);
			this.updatePlaceholder();
		}

		unfocusOption(option) {
			super.unfocusOption(option);
			this.updatePlaceholder();
		}

		selectOption(option) {
			const key = option.dataset.id;

			if (!this.multiple) {
				this.values.clear();
				this.values.add(key);
				this.hidePanel();
			} else if (this.values.has(key)) {
				this.values.delete(key);
				this.unfocusOption(option);
				option._checkbox.checked = false;
			} else {
				this.values.add(key);
				option._checkbox.checked = true;
			}

			this.updateSelect();
		}

		elementKeydown(event) {
			super.elementKeydown(event);
			if (event.defaultPrevented) return;

			if (event.key === "Enter") {
				event.stopPropagation();
				event.preventDefault();
				if (this.panelOpen) {
					this.hidePanel();
				} else if (this.options.length > 0) {
					this.showPanel();
				}
			} else if (
				this.values.size > 0 &&
				(event.key === "Backspace" || event.key === "Delete")
			) {
				event.stopPropagation();
				this.clear();
			}
		}

		deactivate() {
			this.hidePanel();
			this.unfocusOption();
			this.element.dispatchEvent(
				new CustomEvent("deactivate", { bubbles: true }),
			);
			this.element.value = "";
			this.updatePlaceholder();
		}

		addValue(value, preloading = false) {
			this.values.add(value);
			this.updateSelect(preloading);
		}

		addOption(option = {}, preloading = false) {
			if (Object.keys(option).length === 0) return;

			if (option.id && !this.options.some((o) => o.id === option.id)) {
				this.options.unshift(option);
			}
			this.results.add(option);
			this.addValue(option.id, preloading);
		}

		clear({ notify = true } = {}) {
			if (this.values.size === 0) return;

			this.values.clear();
			this.focusedIndex = -1;
			this.element.value = "";
			this.hidePanel();
			this.updateSelect(!notify);
		}
	};
