import type { PollingCoordinator } from "../shared/polling.ts";

interface DocumentIdentity {
	key: string;
	sync_id: string;
	fingerprint?: string | null;
}

export interface DocumentCursor {
	generation: string | null;
	revision: number;
	presence_digest: string | null;
}

export interface SyncMention {
	occurrence_id: string;
	recipient: string;
	display_name: string;
}

export interface DocumentUpdateContent {
	update?: string | null;
	ydoc?: string | null;
	html?: string | null;
	mentions?: SyncMention[] | null;
}

interface DocumentUpdate extends DocumentIdentity, DocumentUpdateContent {
	generation?: string | null;
	revision?: number | null;
	presence_digest?: string | null;
	touch_parent?: boolean;
}

export interface SyncUpdate extends DocumentUpdate {
	save: boolean;
}

export interface PersistedSyncRecord extends DocumentUpdate {
	save?: boolean;
	timestamp?: number;
}

interface SyncAcknowledgement {
	sync_id: string;
	generation: string | null;
	revision: number;
	fingerprint: string | null;
	checkpoint_accepted: boolean;
	checkpoint_persisted: boolean;
	entity_touched: boolean;
}

export interface SyncResponse {
	updates: SyncAcknowledgement[];
}

interface DocumentAuthor {
	hash: string;
	name: string;
}

interface DocumentReader {
	id: string;
	hash?: string;
	name?: string;
}

interface DocumentDelta {
	revision: number;
	update: string;
	user_hash: string | null;
}

export interface DocumentPollPayload {
	generation: string;
	revision: number;
	fingerprint: string | null;
	mode: "snapshot" | "delta";
	updates: DocumentDelta[];
	checkpoint_required: boolean;
	ydoc?: string | null;
	markup?: string | null;
	user_hash?: string;
	authors?: Record<string, DocumentAuthor>;
	users?: (DocumentReader & { client_id: string })[];
	user?: DocumentReader;
	presence_digest?: string;
}

interface CachedDocumentSnapshot {
	mode: "snapshot";
	ydoc?: string | null;
	markup?: string | null;
	fingerprint?: string | null;
	updates?: { update: string }[];
}

export type DocumentState = DocumentPollPayload | CachedDocumentSnapshot;

interface DocumentReadCache {
	read(): Promise<CachedDocumentSnapshot | null>;
	accept(payload: DocumentState): Promise<void>;
	clear(): Promise<void>;
}

type ComponentWidget = SyncWidget | { syncId?: null };

export interface SyncComponent {
	key?: string | null;
	visible?: boolean;
	elt?: HTMLElement | null;
	active?: object | null;
	widgets?: Record<string, ComponentWidget>;
}

export interface SyncWidget {
	syncId: string;
	key: string;
	component?: SyncComponent | null;
	target?: HTMLElement;
	container?: HTMLElement | null;
	initialized: boolean;
	visible?: boolean;
	readonly?: boolean;
	fingerprint?: string | null;
	snapshot?: string | null;
	remote: DocumentState | null;
	offlineRecord: PersistedSyncRecord | null;
	readCache?: DocumentReadCache;
	readonly saveData: DocumentUpdateContent | null;
	readonly syncData: DocumentUpdateContent | null;
	init(): void | Promise<void>;
	sync(): Promise<boolean | undefined>;
	waitForRender(): Promise<unknown>;
	commitSavedBaseline?(snapshot: string, mentions: SyncMention[]): void;
	destroy(): void;
}

export interface SyncView {
	online: boolean;
	hidden: boolean;
	components?: Record<string, SyncComponent>;
	connectivityGeneration?: number;
	PollingCoordinator?: Pick<
		PollingCoordinator,
		"get" | "update" | "subscribe" | "trigger" | "closeDocuments" | "clientId"
	> | null;
}

export interface SyncSendOptions {
	keepalive?: boolean;
	touchSyncIds?: Iterable<string>;
}
