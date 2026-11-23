"""Digest-addressed OAuth records; all multi-record transitions are atomic."""

from collections.abc import Callable, Mapping

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore.transaction import Transaction

from .core import DATA
from .transactions import retry_aborted
from .utility import create_named_key


# @testable false
# @covered-by lagniappe/core/tools/database/remote_mcp.py::atomic
class Records:
    def __init__(self, transaction: Transaction | None = None) -> None:
        self.transaction = transaction

    # @testable false
    # @covered-by lagniappe/core/tools/database/remote_mcp.py::atomic
    def get(self, name: str) -> DatastoreEntity | None:
        return DATA.datastore.get(
            create_named_key("mcp_oauth", name), transaction=self.transaction
        )

    # @testable false
    # @covered-by lagniappe/core/tools/database/remote_mcp.py::atomic
    def put(self, name: str, value: Mapping[str, object]) -> None:
        # No OAuth record needs a query index. Expiry is enforced on every read.
        row = DatastoreEntity(
            key=create_named_key("mcp_oauth", name), exclude_from_indexes=tuple(value)
        )
        row.update(value)
        if self.transaction is None:
            raise RuntimeError("OAuth record writes require a transaction.")
        self.transaction.put(row)


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_store_uses_one_transaction_and_unindexed_records
# @matrix mcp-oauth : persistence transaction
@retry_aborted
def atomic[R](operation: Callable[[Records], R]) -> R:
    with DATA.datastore.transaction() as transaction:
        return operation(Records(transaction))


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::authenticate_access
def read(name: str) -> DatastoreEntity | None:
    return Records().get(name)
