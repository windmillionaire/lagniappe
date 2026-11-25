import type { OfflineMutationRecord } from "../shared/offlineQueue.ts";
import type { RequestResult } from "./api.d.ts";

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
	type?: FieldType;
	name?: string;
	label?: string;
	checked?: boolean;
	text?: string;
}

/** Canonical field definition rendered by FormRenderer. */
export interface FormFieldSchema {
	id: string;
	type: FieldType;
	title?: string;
	label?: string;
	name?: string;
	input?: InputType;
	location?: "out" | "in";
	multiple?: boolean;
	required?: boolean;
	checked?: boolean;
	layout?: "column" | "row";
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

/** Operation projection used by form controls and HTML bootstrap data. */
export interface FormReviewOperation {
	key: string;
	revision?: number | string | null;
	type?: string | null;
	status?: string | null;
	terminal?: boolean;
	phase?: string;
	phase_label?: string;
	recovering?: boolean;
	elapsed_seconds?: number;
	retry_reason?: string | null;
	error?: string;
	can_cancel?: boolean;
	operation_id?: string | null;
	scope?: string | null;
	blocks_edit?: boolean;
}

export interface FormAutofillReview {
	operation: string;
	private?: boolean;
	fields?: string[];
	schema?: FormSchema | null;
	submission: FormSubmission;
	baseline?: FormSubmission | null;
	saved_baseline?: FormSubmission | null;
}

export interface FormReviewState {
	revision?: string;
	operation?: FormReviewOperation | null;
	reviews?: FormAutofillReview[];
	stale_autofill?: boolean;
	refine_url?: string | null;
	cancel_url?: string;
	retry_operation?: string | null;
}

export interface FormMigrationNotice {
	label: string;
	before: string | null;
	after: string | null;
	reason: string;
}

export interface FormRevisionFields {
	schema: FormSchema | null;
	submission: FormSubmission | null;
	form_state: FormReviewState;
	migration_notice: FormMigrationNotice[] | null;
	generation: string | null;
}

export type FormRevisionResponse = RequestResult<FormRevisionFields>;

export interface FormRevisionConflict {
	record?: OfflineMutationRecord | null;
	response?: FormRevisionResponse | null;
}

export type FormRevisionSource = "local" | "server" | `ai:${string}`;

export type FormRevisionChoice =
	| "local"
	| "server"
	| {
			selections?: Record<string, FormRevisionSource>;
			selectedSubmission?: FormSubmission;
			localResponse?: FormRevisionResponse;
	  };

export interface FormRevisionReviewOptions {
	blockedAction?: "autofill" | null;
}
