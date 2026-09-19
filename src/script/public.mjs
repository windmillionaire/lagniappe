import { initializePublicSharing } from "./shared/publicShare.mjs";

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.mjs::test_public_share_entry_initializes_once
 * @matrix public-pages : entrypoint initialization
 */
export function startPublicPage() {
	initializePublicSharing();
}

startPublicPage();
