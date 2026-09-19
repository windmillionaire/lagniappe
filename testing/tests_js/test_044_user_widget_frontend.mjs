import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

// @matrix users : create-form create-form-reset focus-preservation visibility-isolation
test("test_create_user_focuses_on_open_and_reset_without_stealing_live_field_focus", async (t) => {
	let activeElement = null;
	const body = { id: "body" };
	replaceGlobal(t, "document", {
		body,
		get activeElement() {
			return activeElement;
		},
	});
	class FormWidget {
		constructor(attributes = {}) {
			Object.assign(this, attributes);
			this._created = false;
			this._updated = false;
		}
		async prereconcile() {}
		postreconcile() {
			this._created = false;
			this._updated = false;
		}
	}
	const { CreateUser } = await esmock.strict(
		"../../src/script/widgets/user.mjs",
		{
			"../../src/script/elements/facetedSearch.mjs": {
				FacetedSearchElement: class {},
			},
			"../../src/script/elements/input.mjs": { InputElement: class {} },
			"../../src/script/elements/radio.mjs": { RadioElement: class {} },
			"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
		},
	);

	function createWidget(visible) {
		const name = { id: "name" };
		const email = { id: "email" };
		const submit = { id: "submit" };
		const target = {
			dataset: { visible: visible ? "true" : "false" },
			contains(element) {
				return [name, email, submit].includes(element);
			},
		};
		let focusCount = 0;
		const widget = new CreateUser({ target });
		widget.nameElement = {
			focus() {
				focusCount += 1;
				activeElement = name;
			},
		};
		widget.form = {
			resetSubmitButton() {
				widget.submitReset = true;
			},
		};
		widget.prepareReset = async () => {
			widget.resetPrepared = true;
		};
		widget.commitReset = () => {
			const resetName = { id: "reset-name" };
			widget.target = {
				dataset: { visible: "true" },
				contains(element) {
					return element === resetName;
				},
			};
			widget.nameElement = {
				focus() {
					focusCount += 1;
					activeElement = resetName;
				},
			};
			activeElement = body;
			return true;
		};
		return {
			email,
			get focusCount() {
				return focusCount;
			},
			submit,
			target,
			widget,
		};
	}

	const opening = createWidget(false);
	activeElement = body;
	await opening.widget.prereconcile();
	opening.target.dataset.visible = "true";
	opening.widget.postreconcile();
	assert.equal(opening.focusCount, 1);
	assert.equal(activeElement.id, "name");

	const movedDuringOpen = createWidget(false);
	activeElement = body;
	await movedDuringOpen.widget.prereconcile();
	activeElement = movedDuringOpen.email;
	movedDuringOpen.target.dataset.visible = "true";
	movedDuringOpen.widget.postreconcile();
	assert.equal(movedDuringOpen.focusCount, 0);
	assert.equal(activeElement, movedDuringOpen.email);

	const ordinary = createWidget(true);
	activeElement = ordinary.email;
	await ordinary.widget.prereconcile();
	ordinary.widget.postreconcile();
	assert.equal(ordinary.focusCount, 0);
	assert.equal(activeElement, ordinary.email);

	const inactive = createWidget(false);
	inactive.widget.visible = false;
	inactive.widget.postreconcile();
	assert.equal(inactive.target.dataset.visible, "false");

	const created = createWidget(true);
	created.widget._created = true;
	activeElement = created.submit;
	await created.widget.prereconcile();
	created.widget.postreconcile();
	assert.equal(created.widget.resetPrepared, true);
	assert.equal(created.widget.submitReset, true);
	assert.equal(created.focusCount, 1);
	assert.equal(activeElement.id, "reset-name");
});

// @matrix user-groups : rename reset-rebinding
test("test_group_permissions_tracks_rename_draft_after_target_rebuild", async () => {
	const node = (name) => ({
		dataset: { name },
		input: { value: name },
		querySelector() {
			return this.input;
		},
	});
	class FormWidget {
		constructor(attributes) {
			Object.assign(this, attributes);
		}
		get formData() {
			return new Map([["name", this.target.input.value]]);
		}
		async prepareSubmit() {
			return true;
		}
		markUnsavedState() {
			this.unsavedState = true;
		}
		async reset() {}
		async prepareRevision() {}
		postreconcile() {
			if (!this._updated) return;
			this.target = this.initialTarget;
			this._updated = false;
			this.unsavedState = false;
		}
	}
	const { GroupPermissions } = await esmock.strict(
		"../../src/script/widgets/userPermissions.mjs",
		{
			"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
		},
	);
	const label = { textContent: "Original" };
	const button = {
		dataset: { key: "group" },
		querySelector: () => label,
	};
	const widget = new GroupPermissions({
		target: node("Original"),
		key: "group",
		component: { elt: { querySelectorAll: () => [button] } },
	});

	widget.target.input.value = "First rename";
	assert.equal(await widget.prepareSubmit(), true);
	widget.initialTarget = node("First rename");
	widget._updated = true;
	widget.postreconcile();
	assert.equal(label.textContent, "First rename");

	widget.target.input.value = "Second rename";
	assert.equal(widget.formData.get("name"), "Second rename");
	assert.equal(await widget.prepareSubmit(), true);
	widget.target.input.value = "Newer draft";
	widget.initialTarget = node("Second rename");
	widget._updated = true;
	widget.postreconcile();
	assert.equal(widget.formData.get("name"), "Newer draft");
	assert.equal(label.textContent, "Second rename");
	assert.equal(widget.unsavedState, true);

	widget.revisionPreview = true;
	widget.initialTarget = node("Preview only");
	widget._updated = true;
	widget.postreconcile();
	assert.equal(label.textContent, "Second rename");
});
