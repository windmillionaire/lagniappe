/** Messaging projections returned by the conversation, history, and send routes. */
export interface MessageConversation {
	id: string | null;
	peer: {
		id: string | null;
		name: string;
		available: boolean;
		replyable: boolean;
		deleted: boolean;
	};
	unread: number;
	revision: number;
}

export interface MessageEntry {
	id: string | null;
	body: string;
	mine: boolean;
	created: string | null;
}

export interface MessageSendResponse {
	conversation: MessageConversation;
}
