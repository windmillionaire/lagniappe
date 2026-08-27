import { initializePublicSharing } from "./shared/publicShare";

/**
 * @testable true
 * @tests tests_js/test_047_public_sharing.py::test_public_share_entry_initializes_once
 * @matrix public-pages : entrypoint initialization
 */
export function startPublicPage() {
	initializePublicSharing();
}

startPublicPage();
