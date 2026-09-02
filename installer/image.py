"""Best-effort restoration of site images with transactional local updates."""

import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import uuid

from installer import FORMATTER
from installer.utils import ensure_storage_dependency

DATASTORE_TIMEOUT = 30
IMAGE_DOWNLOAD_TIMEOUT = 60
SITE_IMAGE_SUFFIXES = (".png", ".ico", ".jpg", ".jpeg", ".webp")
SITE_IMAGE_METADATA_KEYS = frozenset({"version", "asset_generations"})


# @testable false
# @covered-by installer/image.py::get_images
# @reason thin Datastore client adapter owned by image metadata discovery
def get_datastore_client():
    from google.cloud import datastore
    from config import SETTINGS

    return datastore.Client(project=SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT"))


# @testable false
# @covered-by installer/image.py::save_images
# @reason thin managed-public-bucket adapter owned by transactional image restore
def get_storage_bucket():
    ensure_storage_dependency()

    from google.cloud import storage
    from config import SETTINGS
    from config.storage import storage_bucket_names

    bucket_name = storage_bucket_names(SETTINGS.APP)["public"]
    return storage.Client().bucket(bucket_name)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_image_restore_uses_loaded_metadata_and_timeouts
# @pair setup:image-restore
def get_images():
    f = FORMATTER.initialize()

    try:
        ds = get_datastore_client()
        image_key = ds.key("site", "image")
        return ds.get(image_key, timeout=DATASTORE_TIMEOUT)
    except Exception as error:
        print(f.warning(f"Could not check Datastore for site images: {error}"))
        print(f.warning("Continuing update with existing site images."))
        return None


# @testable false
# @covered-by installer/image.py::save_images
# @reason path validation branch exercised through transactional image restore
def _validated_image_key(key):
    value = str(key)
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or path.drive
    ):
        raise ValueError(f"Unsafe site-image key: {value!r}")
    return path


# @testable false
# @covered-by installer/image.py::save_images
# @reason metadata filtering and legacy path fallback are exercised through image restore
def _site_image_entries(images_dict, sp, formatter):
    """Return safe local names and their corresponding remote blob paths."""
    entries = []
    for raw_name, stored_path in images_dict.items():
        name = str(raw_name)
        if name.casefold() in SITE_IMAGE_METADATA_KEYS:
            continue
        if not name.casefold().endswith(SITE_IMAGE_SUFFIXES):
            sp.write(
                formatter.warning(
                    f"Ignoring unrecognized site-image metadata: {name}"
                )
            )
            continue
        try:
            relative_path = _validated_image_key(name)
        except ValueError as error:
            sp.write(formatter.warning(f"Ignoring site image: {error}"))
            continue

        if isinstance(stored_path, str) and stored_path.strip():
            provider_key = stored_path.strip()
        elif stored_path is True:
            # Early installations used the image name itself as the remote key.
            provider_key = name
        else:
            sp.write(
                formatter.warning(
                    f"Ignoring site image with no stored object path: {name}"
                )
            )
            continue
        entries.append((provider_key, relative_path))
    return entries


# @testable false
# @covered-by installer/image.py::save_images
# @reason directory swap and rollback are owned by transactional image restore
def _swap_image_tree(staging, images_dir):
    backup = images_dir.parent / (
        f".{images_dir.name}.backup-{uuid.uuid4().hex}"
    )
    had_existing = images_dir.exists()
    try:
        if had_existing:
            os.replace(images_dir, backup)
        os.replace(staging, images_dir)
    except Exception:
        if had_existing and backup.exists() and not images_dir.exists():
            os.replace(backup, images_dir)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_image_restore_uses_loaded_metadata_and_timeouts
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_image_restore_skips_invalid_entries_and_keeps_successful_downloads
# @matrix setup : image-restore path-validation transactional-state partial-failure
def save_images(sp, images_dict=None):
    """Restore each available remote image without replacing good live files."""
    from installer import FORMATTER
    from config import Directory

    f = FORMATTER.initialize()
    if images_dict is None:
        images_dict = get_images()
    if not images_dict:
        sp.write(f.warning("Site images not found; keeping existing images."))
        return False

    keys = _site_image_entries(images_dict, sp, f)
    if not keys:
        sp.write(
            f.warning(
                "Site image metadata contains no restorable image files; "
                "keeping existing images."
            )
        )
        return False

    images_dir = Path(Directory.SITE_IMAGES.value)
    images_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{images_dir.name}.staging-",
            dir=images_dir.parent,
        )
    )
    try:
        if images_dir.exists():
            shutil.copytree(images_dir, staging, dirs_exist_ok=True)
        try:
            bucket = get_storage_bucket()
        except Exception as error:
            sp.write(
                f.warning(
                    f"Could not access stored site images; keeping existing "
                    f"images. Reason: {error}"
                )
            )
            return False
        staged_targets = []
        for provider_key, relative_path in keys:
            target = staging.joinpath(*relative_path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            download = target.with_name(
                f".{target.name}.download-{uuid.uuid4().hex}"
            )
            try:
                blob = bucket.blob(provider_key)
                blob.download_to_filename(
                    str(download),
                    timeout=IMAGE_DOWNLOAD_TIMEOUT,
                )
                if not download.is_file() or download.stat().st_size == 0:
                    raise RuntimeError(
                        f"Downloaded site image is missing or empty: {provider_key}"
                    )
                os.replace(download, target)
            except Exception as error:
                if download.exists():
                    download.unlink()
                sp.write(
                    f.warning(
                        f"Could not restore site image {relative_path}; "
                        f"continuing without it. Reason: {error}"
                    )
                )
                continue
            staged_targets.append(target)
            sp.write(f.info(f"Staged {provider_key}"))

        if not staged_targets:
            sp.write(
                f.warning(
                    "No remote site images could be restored; keeping existing images."
                )
            )
            return False
        _swap_image_tree(staging, images_dir)
        staging = None
        if len(staged_targets) != len(keys):
            sp.write(
                f.warning(
                    f"Restored {len(staged_targets)} of {len(keys)} site images; "
                    "existing files were retained for unavailable images."
                )
            )
        return True
    except Exception as error:
        sp.write(
            f.warning(
                f"Could not update local site images; keeping existing images. "
                f"Reason: {error}"
            )
        )
        return False
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
