"""Digest-addressed OAuth records; all multi-record transitions are atomic."""

from collections.abc import Callable, Mapping

from google.cloud.datastore import Entity as DatastoreEntity
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
