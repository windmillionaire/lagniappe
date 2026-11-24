export type InputType = "text" | "date" | "time" | "number" | "email" | "tel";

export type FieldType =
	| "bookmark"
	| "checkbox"
	| "html"
	| "input"
	| "link"
	| "location"
	| "radio"
	| "select"
	| "signature"
	| "status"
	| "table"
	| "textarea"
	| "todo";

export interface FieldOption {
	label: string;
	value: string;
}

export interface FieldCondition {
	id?: string;
	value?: unknown;
}

/** Canonical field definition rendered by FormRenderer. */
export interface FormFieldSchema {
	id: string;
	type: FieldType;
	title?: string;
	input?: InputType;
	location?: "out" | "in";
	multiple?: boolean;
	required?: boolean;
	placeholder?: string | null;
	options?: FieldOption[];
	columns?: FormFieldSchema[];
	visibility?: FieldCondition[] | null;
	status?: FieldCondition[] | null;
}

export type FormSchema = FormFieldSchema[];

/** Each value is interpreted by the field definition for its key. */
export type FormSubmission = Record<string, unknown>;

export interface FormControlSelection {
	name: string;
	options: object[];
}

export interface CapturedFormState {
	fields: [name: string, value: string][];
	files: { name: string; file: Blob; filename: string; type: string }[];
	form_controls: FormControlSelection[];
	renderer_schema: FormSchema | null;
	renderer_submission: FormSubmission | null;
}
