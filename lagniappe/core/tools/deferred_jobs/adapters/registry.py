"""Composable registry for deferred-job domain strategies."""

from threading import RLock

from lagniappe.core import exceptions
from lagniappe.core.definitions import DeferredJobType

from .base import DeferredJobAdapter


# @testable true
# @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
# @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_rejects_duplicate_job_types
# @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_rolls_back_failed_default_loading
# @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_loads_defaults_once_across_threads
# @pair deferred-jobs:adapter-registry
# @pair deferred-jobs:domain-strategy
class DeferredJobAdapterRegistry:
    def __init__(self):
        self._adapters = {}
        self._defaults_loaded = False
        self._lock = RLock()

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_registered_adapters_declare_required_ai_tiers
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_rejects_duplicate_job_types
    # @pair deferred-jobs:adapter-registration
    def register(self, adapter):
        if not isinstance(adapter, DeferredJobAdapter) or adapter.job_type is None:
            raise TypeError("Deferred job adapters require a job_type")
        with self._lock:
            if adapter.job_type in self._adapters:
                raise ValueError(
                    f"Deferred job adapter already registered: {adapter.job_type.value}"
                )
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

    # @testable true
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_rolls_back_failed_default_loading
    # @tests tests_unit/test_023c_deferred_job_runner.py::test_adapter_registry_loads_defaults_once_across_threads
    # @pair deferred-jobs:failure-isolation
    # @pair deferred-jobs:concurrency
    def _load_default_adapters(self):
        with self._lock:
            if self._defaults_loaded:
                return
            adapters = self._adapters.copy()
            try:
                from .registry_defaults import register_adapters

                register_adapters(self)
            except Exception:
                self._adapters = adapters
                raise
            self._defaults_loaded = True
