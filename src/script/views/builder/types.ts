import type {
	FieldType,
	FormFieldSchema,
	FormSchema,
	InputType,
} from "../../types/forms.d.ts";

export interface DraftContent {
	name: string;
	schema: FormSchema;
	form_type?: string | null;
	html_fields: Record<string, string>;
	conversion_instructions?: Record<string, string>;
}

export interface DraftState extends DraftContent {
	selected_id?: string | null;
}

export interface DraftPublication {
	draft: DraftContent;
	baseline: string;
	image_urls?: Record<string, string>;
}

export interface PendingChange {
	status: string | null;
	operation?: string | null;
	error?: string | null;
	failed_entity?: { kind: string; url: string; name: string } | null;
}

export interface DraftBootstrap extends DraftState {
	baseline: string;
	pending_change?: PendingChange;
}

export interface DraftChangeResponse extends DraftPublication {
	pending_change?: PendingChange | null;
	rejected_change?: { error: string } | null;
	saved_url?: string;
}

export interface DraftAttempt {
	state: DraftState;
	id: string;
}

export interface DraftCopyResponse {
	url: string;
	saved_url?: string;
}

type GeneratedOperation =
	| { op: "add_field"; field: FormFieldSchema }
	| {
			op: "update_field";
			field_id: string;
			changes: Partial<Pick<FormFieldSchema, "title" | "placeholder">>;
	  }
	| { op: "update_option"; field_id: string; value: string; label: string }
	| { op: "update_column"; field_id: string; column_id: string; title: string };

export interface DraftGenerationResponse {
	operations: GeneratedOperation[];
	html_fields?: Record<string, string>;
	request_id: string;
	draft_revision: number;
	saved_url?: string;
}

export type FieldKind = FieldType | InputType | "in" | "out" | "multiple";

type ConversionRule = "scalar" | "delete" | "table" | "text" | "ai";

export interface ConversionChoice {
	value: FieldKind;
	label: string;
	schema: Omit<FormFieldSchema, "id">;
}

export interface ConversionCatalog {
	version: number;
	types: ConversionChoice[];
	rules: Partial<
		Record<FieldKind, Partial<Record<string, ConversionRule | null>>>
	>;
}
