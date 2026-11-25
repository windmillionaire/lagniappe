from __future__ import annotations
from typing import TYPE_CHECKING


from runner import presentation as ui
from runner.presentation import output as print
def get_deployment_settings() -> Entity | None:
    from installer.utils import ensure_datastore_dependency
    from installer.image import DATASTORE_TIMEOUT, get_datastore_client
    from installer import FORMATTER

    f = FORMATTER.initialize()

    deployment_entity = None
    try:
        ensure_datastore_dependency()
        ds = get_datastore_client()
        deployment_key = ds.key("site", "deployment")
        deployment_entity = ds.get(deployment_key, timeout=DATASTORE_TIMEOUT)
    except Exception as e:
        print(f.warning(f"Could not check Datastore for deployment settings: {e}"))
        print(ui.info("Continuing update with existing app.yaml settings."))

    return deployment_entity


from config.deployment import (
    apply_deployment_settings as apply_deployment_settings,
    normalize_deployment_settings as normalize_deployment_settings,
)


if TYPE_CHECKING:
    from google.cloud.datastore import Entity
