import { MessagingModal } from "../shared";
import Core from "./base/core";

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001c_messaging.py::test_allow_messages
 * @features messaging
 * @dimensions permission-modal
 */
export default class Testing extends Core {
	async init() {
		await super.init();
		// Explicitly show the messaging modal for testing
		// (initializeMessaging skips the modal in testing mode)
		const messagingModal = new MessagingModal();
		await messagingModal.init();
	}
}
