/**
 * @testable true
 * @tests tests_js/test_036b_builder_draft.mjs::test_builder_draft_history_and_generation
 * @matrix forms : draft-history stable-identity schema-generation stale-acknowledgement
 */
export class BuilderDraft {
	constructor(state, baseline = null) {
		this.state = structuredClone(state);
		this.saved = structuredClone(state);
		this.baseline = baseline;
		this.revision = 0;
		this.past = [];
		this.future = [];
		this.group = null;
		// Recomputed on form edits/Save, so Document typing only compares HTML.
		this.formDirty = false;
	}

	content(state = this.state) {
		const { selected_id: _selection, ...content } = state;
		return content;
	}

	equal(a, b) {
		return this.serialize(this.content(a)) === this.serialize(this.content(b));
	}

	equalForm(a, b) {
		const { html_fields: _aHtml, ...aForm } = this.content(a);
		const { html_fields: _bHtml, ...bForm } = this.content(b);
		return this.serialize(aForm) === this.serialize(bForm);
	}

	serialize(value) {
		return JSON.stringify(value, (_key, item) =>
			item && typeof item === "object" && !Array.isArray(item)
				? Object.fromEntries(
						Object.keys(item)
							.sort()
							.map((key) => [key, item[key]]),
					)
				: item,
		);
	}

	get dirty() {
		return (
			this.formDirty ||
			this.serialize(this.state.html_fields) !==
				this.serialize(this.saved.html_fields)
		);
	}

	updateHtml(fieldId, html) {
		if (this.state.html_fields[fieldId] === html) return false;
		// The Document editor owns its history. Typing never snapshots the form.
		this.state.html_fields[fieldId] = html;
		this.revision += 1;
		return true;
	}

	record(state, group = null) {
		if (this.equal(this.state, state)) {
			this.state.selected_id = state.selected_id;
			return false;
		}
		if (!this.equalForm(this.state, state)) {
			if (!group || this.group !== group) {
				this.past.push(structuredClone(this.state));
				if (this.past.length > 100) this.past.shift();
			}
			this.future = [];
			this.group = group;
		}
		this.state = structuredClone(state);
		this.formDirty = !this.equalForm(this.state, this.saved);
		this.revision += 1;
		return true;
	}

	restoreForm(state) {
		const documents = new Set(
			this.state.schema
				.filter((field) => field.type === "html")
				.map((field) => field.id),
		);
		// Keep current content for surviving fields; restored fields bring their
		// snapshot content back with them, including any local image references.
		for (const field of state.schema) {
			if (field.type !== "html" || !documents.has(field.id)) continue;
			if (Object.hasOwn(this.state.html_fields, field.id))
				state.html_fields[field.id] = this.state.html_fields[field.id];
			else delete state.html_fields[field.id];
		}
		this.state = state;
		this.formDirty = !this.equalForm(this.state, this.saved);
		this.group = null;
		this.revision += 1;
	}

	undo() {
		if (!this.past.length) return false;
		this.future.push(structuredClone(this.state));
		this.restoreForm(this.past.pop());
		return true;
	}

	redo() {
		if (!this.future.length) return false;
		this.past.push(structuredClone(this.state));
		this.restoreForm(this.future.pop());
		return true;
	}

	acknowledge(submitted, response) {
		const replacement = response.image_urls || {};
		const map = (state) => {
			const result = structuredClone(state);
			for (const [id, html] of Object.entries(result.html_fields || {})) {
				result.html_fields[id] = Object.entries(replacement).reduce(
					(text, [token, url]) =>
						text.replaceAll(
							token.startsWith("draft-image:") ? token : `draft-image:${token}`,
							url,
						),
					html,
				);
			}
			return result;
		};
		const reconcile = (value, source, accepted) => {
			if (this.serialize(value) === this.serialize(source))
				return structuredClone(accepted);
			if (
				Array.isArray(value) &&
				Array.isArray(source) &&
				Array.isArray(accepted)
			) {
				return value.map((entry, index) => {
					const identity = entry?.id ?? entry?.value;
					const original =
						identity === undefined
							? source[index]
							: source.find((item) => (item?.id ?? item?.value) === identity);
					const saved =
						identity === undefined
							? accepted[index]
							: accepted.find((item) => (item?.id ?? item?.value) === identity);
					return original && saved
						? reconcile(entry, original, saved)
						: structuredClone(entry);
				});
			}
			if (
				value &&
				source &&
				accepted &&
				typeof value === "object" &&
				typeof source === "object" &&
				typeof accepted === "object" &&
				!Array.isArray(value)
			) {
				const result = structuredClone(value);
				for (const key of new Set([
					...Object.keys(source),
					...Object.keys(accepted),
				])) {
					const merged = reconcile(value[key], source[key], accepted[key]);
					if (merged === undefined) delete result[key];
					else result[key] = merged;
				}
				return result;
			}
			return structuredClone(value);
		};
		const unchanged = this.equal(this.state, submitted);
		const apply = (state) => ({
			...reconcile(map(state), map(submitted), response.draft),
			selected_id: state.selected_id,
		});
		this.past = this.past.map(apply);
		this.future = this.future.map(apply);
		this.state = apply(this.state);
		this.saved = { ...structuredClone(response.draft), selected_id: null };
		this.baseline = response.baseline;
		this.revision += 1;
		if (unchanged)
			this.state = {
				...structuredClone(this.saved),
				selected_id: this.state.selected_id,
			};
		this.formDirty = !this.equalForm(this.state, this.saved);
		this.group = null;
		return unchanged;
	}

	applyGeneration(response) {
		const next = structuredClone(this.state);
		const fields = new Map(next.schema.map((field) => [field.id, field]));
		if (!Array.isArray(response.operations))
			throw new Error("Invalid generated changes.");
		for (const operation of response.operations) {
			if (operation.op === "add_field") {
				const field = operation.field;
				if (!field?.id || fields.has(field.id))
					throw new Error("Generated field identity is invalid.");
				if (
					![
						"input",
						"textarea",
						"checkbox",
						"select",
						"radio",
						"table",
						"html",
						"status",
						"signature",
						"link",
						"bookmark",
						"location",
						"todo",
					].includes(field.type)
				)
					throw new Error("Unsupported generated field type.");
				const added = structuredClone(field);
				if (added.type === "html") next.html_fields[added.id] = "";
				next.schema.push(added);
				fields.set(added.id, added);
				continue;
			}
			const field = fields.get(operation.field_id);
			if (!field)
				throw new Error("A generated change targets an unknown field.");
			if (operation.op === "update_field") {
				if (
					!operation.changes ||
					Object.entries(operation.changes).some(
						([key, value]) =>
							!["title", "placeholder"].includes(key) ||
							typeof value !== "string",
					)
				) {
					throw new Error(
						"This generated change needs a later migration step.",
					);
				}
				Object.assign(field, operation.changes);
			} else if (operation.op === "update_option") {
				const option = field.options?.find(
					(item) => item.value === operation.value,
				);
				if (!option || typeof operation.label !== "string")
					throw new Error("Invalid generated option label.");
				option.label = operation.label;
			} else if (operation.op === "update_column") {
				const column = field.columns?.find(
					(item) => item.id === operation.column_id,
				);
				if (!column || typeof operation.title !== "string")
					throw new Error("Invalid generated column label.");
				column.title = operation.title;
			} else
				throw new Error("This generated change needs a later migration step.");
		}
		for (const [id, html] of Object.entries(response.html_fields || {})) {
			if (fields.get(id)?.type !== "html" || typeof html !== "string")
				throw new Error("Invalid generated text content.");
			next.html_fields[id] = html;
		}
		return this.record(next);
	}
}
