"""Composable registry for deferred-job domain strategies."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import DeferredJobType

from .base import DeferredJobAdapter


# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
# @pair deferred-jobs:adapter-registry
# @pair deferred-jobs:domain-strategy
class DeferredJobAdapterRegistry:
    def __init__(self):
        self._adapters = {}
        self._defaults_loaded = False

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
    # @pair deferred-jobs:adapter-registration
    def register(self, adapter):
        if not isinstance(adapter, DeferredJobAdapter) or adapter.job_type is None:
            raise TypeError("Deferred job adapters require a job_type")
        self._adapters[adapter.job_type] = adapter
        return adapter

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
    # @pair deferred-jobs:adapter-lookup
    def adapter(self, job_type):
        self._load_default_adapters()
        if not isinstance(job_type, DeferredJobType):
            job_type = DeferredJobType(job_type)
        adapter = self._adapters.get(job_type)
        if adapter is None:
            raise exceptions.ValidationError(
                f"Unsupported deferred job type: {job_type.value}"
            )
        return adapter

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/deferred_jobs/adapters/registry.py::DeferredJobAdapterRegistry.adapter
    def _load_default_adapters(self):
        if self._defaults_loaded:
            return
        self._defaults_loaded = True
        from .registry_defaults import register_adapters

        register_adapters(self)
