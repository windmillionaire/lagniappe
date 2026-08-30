/*! Third-party licenses: /third-party-licenses.txt */
/**
 * Best-effort access to browser storage that never makes application behavior
 * depend on storage availability.
 *
 * @testable true
 * @tests tests_js/test_020_shared_utilities.py::test_safe_storage_adapters_handle_browser_failures_and_json
 * @matrix browser-storage : availability json
 */
class StorageAdapter {
	constructor(name) {
		this.name = name;
	}

	_storage() {
		try {
			return globalThis[this.name] || null;
		} catch {
			return null;
		}
	}

	get(key, fallback = null) {
		try {
			const value = this._storage()?.getItem(key);
			return value === null || value === undefined ? fallback : value;
		} catch {
			return fallback;
		}
	}

	set(key, value) {
		try {
			const storage = this._storage();
			if (!storage) return false;
			storage.setItem(key, value);
			return true;
		} catch {
			return false;
		}
	}

	remove(key) {
		try {
			const storage = this._storage();
			if (!storage) return false;
			storage.removeItem(key);
			return true;
		} catch {
			return false;
		}
	}

	getJSON(key, fallback = null) {
		const value = this.get(key);
		if (value === null) return fallback;

		try {
			return JSON.parse(value);
		} catch {
			this.remove(key);
			return fallback;
		}
	}

	setJSON(key, value) {
		try {
			const serialized = JSON.stringify(value);
			if (serialized === undefined) return false;
			return this.set(key, serialized);
		} catch {
			return false;
		}
	}
}

const localStore = new StorageAdapter("localStorage");
const sessionStore = new StorageAdapter("sessionStorage");

export { localStore as l, sessionStore as s };
