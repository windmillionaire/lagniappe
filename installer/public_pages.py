"""Read public-page settings saved by the deployed application."""

from __future__ import annotations
from typing import TYPE_CHECKING


from runner import presentation as ui
from runner.presentation import output as print


def get_public_page_settings() -> Entity | None:
    from installer.utils import ensure_datastore_dependency
    from installer.image import DATASTORE_TIMEOUT, get_datastore_client
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    entity = None
    try:
        ensure_datastore_dependency()
        datastore = get_datastore_client()
        entity = datastore.get(
            datastore.key("site", "public_pages"),
            timeout=DATASTORE_TIMEOUT,
        )
    except Exception as error:
        print(
            formatter.warning(
                f"Could not check Datastore for public-page settings: {error}"
            )
        )
        print(
            ui.info(
                "Continuing update with existing public-page settings."
            )
        )
    return entity


from config.public_pages import (  # noqa: E402
    apply_public_page_settings as apply_public_page_settings,
    normalize_public_page_settings as normalize_public_page_settings,
)


if TYPE_CHECKING:
    from google.cloud.datastore import Entity
