"""Digest-addressed OAuth records; all multi-record transitions are atomic."""

from collections.abc import Callable, Mapping

from google.cloud.datastore import Entity as DatastoreEntity, Key
from google.cloud.datastore.transaction import Transaction

from .core import DATA
from .transactions import retry_aborted
from .utility import create_named_key


class Records:
    def __init__(self, transaction: Transaction | None = None) -> None:
        self.transaction = transaction

    def get(self, name: str) -> DatastoreEntity | None:
        return DATA.datastore.get(
            create_named_key("mcp_oauth", name), transaction=self.transaction
        )

    def put(self, name: str, value: Mapping[str, object]) -> None:
        # No OAuth record needs a query index. Expiry is enforced on every read.
        row = DatastoreEntity(
            key=create_named_key("mcp_oauth", name), exclude_from_indexes=tuple(value)
        )
        row.update(value)
        if self.transaction is None:
            raise RuntimeError("OAuth record writes require a transaction.")
        self.transaction.put(row)


@retry_aborted
def atomic[R](operation: Callable[[Records], R]) -> R:
    with DATA.datastore.transaction() as transaction:
        return operation(Records(transaction))


def read(name: str) -> DatastoreEntity | None:
    return Records().get(name)


def read_grant_and_user(
    grant_name: str, user_key: object,
) -> tuple[DatastoreEntity | None, DatastoreEntity | None]:
    """Read the two current records referenced by a live access token."""
    if not isinstance(user_key, Key):
        return None, None
    grant_key = create_named_key("mcp_oauth", grant_name)
    rows = {row.key: row for row in DATA.datastore.get_multi([grant_key, user_key])}
    return rows.get(grant_key), rows.get(user_key)
