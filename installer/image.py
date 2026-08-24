"""Transactional restoration of site images from the managed public bucket."""

import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import uuid

from installer import FORMATTER
from installer.utils import ensure_storage_dependency

DATASTORE_TIMEOUT = 30
IMAGE_DOWNLOAD_TIMEOUT = 60


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
# @features setup
# @dimensions image-restore
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
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_image_restore_rejects_unsafe_keys_and_never_swaps_partial_downloads
# @features setup
# @dimensions image-restore transactional-state path-validation
def save_images(sp, images_dict=None):
    """Stage and verify every remote image before replacing the live tree."""
    from installer import FORMATTER
    from config import Directory

    f = FORMATTER.initialize()
    if images_dict is None:
        images_dict = get_images()
    if not images_dict:
        sp.write(f.error("Site images not found"))
        sp.fail(f.fail_glyph)
        return False

    try:
        keys = [
            (str(key), _validated_image_key(key))
            for key in images_dict
            if key != "version"
        ]
    except ValueError as error:
        sp.write(f.error(str(error)))
        sp.fail(f.fail_glyph)
        return False
    if not keys:
        sp.write(f.error("Site image metadata contains no image files"))
        sp.fail(f.fail_glyph)
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
        bucket = get_storage_bucket()
        staged_targets = []
        for provider_key, relative_path in keys:
            target = staging.joinpath(*relative_path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            blob = bucket.blob(provider_key)
            blob.download_to_filename(
                str(target),
                timeout=IMAGE_DOWNLOAD_TIMEOUT,
            )
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError(
                    f"Downloaded site image is missing or empty: {provider_key}"
                )
            staged_targets.append(target)
            sp.write(f.info(f"Staged {provider_key}"))

        if len(staged_targets) != len(keys):
            raise RuntimeError("The complete site-image set was not staged.")
        _swap_image_tree(staging, images_dir)
        staging = None
        return True
    except Exception as error:
        sp.write(f.error(f"Failed to restore site images: {error}"))
        sp.fail(f.fail_glyph)
        return False
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
