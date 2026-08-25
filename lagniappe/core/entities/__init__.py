from ..definitions import Fetch, FetchDepth, MutationOperation
from ..exceptions import capture, record_entity_load_trace
from ..mutations import (
    execute_mutation,
    plan_document_checkpoint,
    plan_document_parent_touch,
    plan_mutation,
    plan_root,
)
from ..mutations.delete import plan_delete
from ..tools import database


# @testable infrastructure
class EntityRegistry:
    """Global type registry and public entity persistence facade."""

    def initialize(self):
        from .types import EntityType

        for name, entity_type in EntityType.__members__.items():
            setattr(self, name, entity_type.value)
        self._types = EntityType
        return self

    def _typed_entity(self, entity):
        """Convert a raw database entity dict to a typed Entity instance."""
        if not entity:
            return None
        if hasattr(entity, "db"):
            return entity

        entity_type = entity.get("type", None)
        if not entity_type:
            capture(
                ValueError(f"Entity type not found for entity: {entity}"),
                context={"entity": entity},
            )
            return None
        return self._types[entity_type.upper()].value(entity)

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_reuses_cached_attached_relations
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_preserves_explicit_root_over_shallow_attached_copy
    # @matrix entities relations : attached-cache load no-extra-read
    def _load(self, *identifiers, related=True, _fetch=None, _fetch_stage=None):
        """Batch-load typed entities and attach resolved relationships."""
        if not identifiers:
            return []

        entities = {
            entity.key: entity
            for entity in [
                self._typed_entity(identifier)
                for identifier in identifiers
                if hasattr(identifier, "key")
            ]
            if entity
        }
        entities.update(
            {
                key: None
                for key in [
                    database.get.datastore_key(identifier)
                    for identifier in identifiers
                    if not hasattr(identifier, "key")
                ]
                if key
            }
        )
        primary_keys = list(entities)

        for entity in [value for value in entities.values() if value]:
            for key, related_entity in entity.related_entities.items():
                entities.setdefault(key, related_entity)
            for key in entity.related_keys:
                entities.setdefault(key, None)

        secondary_keys = [key for key, value in entities.items() if value is None]
        secondary_entities = {
            entity.key: self._typed_entity(entity)
            for entity in database.get.entities(secondary_keys)
            if entity
        }
        entities.update(secondary_entities)
        entities = {key: value for key, value in entities.items() if value}

        related_keys, related_entities = [], {}
        if related:
            related_sources = list(entities.values())
            for entity in related_sources:
                for key, related_entity in entity.related_entities.items():
                    entities.setdefault(key, related_entity)

            related_keys = [
                key
                for entity in related_sources
                for key in entity.related_keys
                if key not in entities
            ]
            related_entities = {
                entity.key: self._typed_entity(entity)
                for entity in database.get.entities(related_keys)
                if entity
            }
            entities.update(related_entities)
            entities = {key: value for key, value in entities.items() if value}

        resolved_keys = {*secondary_keys, *related_keys}
        for entity in entities.values():
            entity.attach(entities, resolved_keys=resolved_keys)

        primary_entities = {
            key: entities[key] for key in primary_keys if key in entities
        }
        record_entity_load_trace(
            primary=primary_entities,
            secondary=secondary_entities,
            related=related_entities,
            first_batch_key_count=len(secondary_keys),
            related_key_count=len(related_keys),
            fetch_depth=_fetch.depth.name if _fetch else None,
            fetch_reason=(
                _fetch.reason.value
                if _fetch and _fetch.reason is not None
                else None
            ),
            fetch_stage=_fetch_stage,
        )
        return list(primary_entities.values())

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_applies_total_depth_to_key_and_typed_entity
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_batches_unresolved_roots_once
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_deduplicates_mixed_roots_and_skips_missing
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_reuses_attached_direct_relations
    # @matrix entities : batch explicit-fetch-depth
    # @matrix relations : direct nested root
    def fetch(self, *identifiers, request):
        """Load roots and expand only to the requested total relationship depth."""
        if not isinstance(request, Fetch):
            raise TypeError("Entities.fetch requires a Fetch request")

        entities = self._load(
            *[identifier for identifier in identifiers if not hasattr(identifier, "key")],
            related=False,
            _fetch=request,
            _fetch_stage="roots",
        ) + [
            self._typed_entity(identifier)
            for identifier in identifiers
            if hasattr(identifier, "key")
        ]
        if request.depth is FetchDepth.ROOT:
            return entities
        return self._load(
            *entities,
            related=request.depth is FetchDepth.NESTED,
            _fetch=request,
            _fetch_stage="relations",
        )

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_fetch_one_returns_entity_or_none
    # @pairs entities:explicit-fetch-depth relations:root
    def fetch_one(self, identifier, *, request):
        fetched = self.fetch(identifier, request=request)
        return fetched[0] if fetched else None

    # @testable true
    # @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_cascades_dependents_assets_and_cache
    # @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_project_cascades_models_forms_filters_and_cache
    # @matrix entities : assets cache cascade database delete forms
    def delete(self, *entities, preserve_user_pages=False):
        return execute_mutation(
            plan_delete(
                *entities,
                registry=self,
                preserve_user_pages=preserve_user_pages,
            )
        )

    # @testable true
    # @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_save_persists_relations_process_payloads_and_cache
    # @matrix entities : cache database dependent-owner process-state save
    def save(self, *entities):
        return execute_mutation(
            plan_mutation(MutationOperation.SAVE, *entities, registry=self)
        )

    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_save_root_persists_full_exclusions_without_lifecycle_intents_or_cache
    # @matrix mutations : cache-isolation direct-save exclusions intent-isolation lifecycle-isolation root-save
    def save_root(self, entity, *, property_mask=None):
        """Persist one root, optionally updating only selected properties."""
        return execute_mutation(plan_root(entity, property_mask=property_mask))

    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_touch_uses_masked_root_save_and_only_updates_modified
    # @matrix mutations : exclusions modified property-mask root-save touch
    def touch(self, *entities):
        entities = tuple(entity for entity in entities if hasattr(entity, "db"))
        return execute_mutation(
            plan_root(
                *entities,
                property_mask=("modified",),
                property_updates=("modified",),
            )
        )

    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_document_checkpoint_masks_parent_state_and_optionally_advances_lists
    # @matrix mutations sync : checkpoint document history parent-fingerprint property-mask
    def save_document_checkpoint(self, entity, *, advance_parent=False):
        """Persist a document checkpoint without rewriting sibling state."""
        return execute_mutation(
            plan_document_checkpoint(
                entity,
                advance_parent=advance_parent,
                registry=self,
            )
        )

    # @testable true
    # @tests tests_unit/test_022_mutation_contracts.py::test_document_parent_touch_only_advances_parent_and_list_fingerprints
    # @matrix mutations sync : document list-owner parent-fingerprint property-mask
    def advance_document_parent(self, entity):
        """Advance document ownership metadata through masked writes."""
        return execute_mutation(
            plan_document_parent_touch(entity, registry=self)
        )

Entities = EntityRegistry()


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_entities_initialized
# @pair entities:initialization
def initialize():
    Entities.initialize()
