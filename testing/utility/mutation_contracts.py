"""Inspect and validate the machine-readable entity mutation contracts."""

import argparse
import json


def _registry_errors():
    from lagniappe.core.definitions.mutation_contracts import (
        ENTITY_MUTATION_CONTRACTS,
        PERSISTED_ENTITY_KINDS,
        validate_mutation_contracts,
    )
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.types import EntityType
    from lagniappe.core.mixins import RelatedEntityListMixin, RelatedEntityMixin
    from lagniappe.core.properties.base_db import DBProperty

    errors = list(validate_mutation_contracts())
    persisted_types = {
        entity_type.value.entity_kind
        for entity_type in EntityType
        if isinstance(entity_type.value, type)
        and issubclass(entity_type.value, Entity)
    }
    missing_kinds = sorted(persisted_types - PERSISTED_ENTITY_KINDS)
    extra_kinds = sorted(PERSISTED_ENTITY_KINDS - persisted_types)
    if missing_kinds:
        errors.append("Missing entity contracts: " + ", ".join(missing_kinds))
    if extra_kinds:
        errors.append("Unknown entity contracts: " + ", ".join(extra_kinds))

    checked_classes = set()
    for entity_type in EntityType:
        entity_class = entity_type.value
        if (
            not isinstance(entity_class, type)
            or not issubclass(entity_class, Entity)
            or entity_class in checked_classes
        ):
            continue
        checked_classes.add(entity_class)
        kind = entity_class.entity_kind
        contract = ENTITY_MUTATION_CONTRACTS.get(kind)
        if contract is None:
            continue
        declared = {relation.name for relation in contract.relations}
        entity = entity_class(testing=True)
        db_relations = {
            name
            for name, property_class in entity.properties._registry.items()
            if issubclass(property_class, DBProperty)
            and issubclass(
                property_class,
                (RelatedEntityMixin, RelatedEntityListMixin),
            )
        }
        missing_relations = sorted(db_relations - declared)
        if missing_relations:
            errors.append(
                f"{kind} is missing persisted relations: "
                + ", ".join(missing_relations)
            )
    return errors


def _payload(kind=None):
    from lagniappe.core.definitions.mutation_contracts import (
        ENTITY_MUTATION_CONTRACTS,
    )

    if kind:
        contract = ENTITY_MUTATION_CONTRACTS.get(kind)
        return contract.to_dict() if contract else None
    return {
        name: contract.to_dict()
        for name, contract in sorted(ENTITY_MUTATION_CONTRACTS.items())
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run.py mutation-contracts",
        description="Inspect executable entity save/delete contracts.",
    )
    parser.add_argument("--kind", help="Show one persisted entity kind.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--check", action="store_true", help="Fail on drift.")
    args = parser.parse_args(argv)

    payload = _payload(args.kind)
    if args.kind and payload is None:
        parser.error(f"Unknown entity kind: {args.kind}")

    errors = _registry_errors()
    if args.json:
        print(json.dumps({"contracts": payload, "errors": errors}, indent=2))
    else:
        contracts = payload if args.kind else payload.values()
        contracts = [contracts] if args.kind else contracts
        for contract in contracts:
            print(f"{contract['kind']}:")
            if not contract["relations"]:
                print("  relations: none")
            for relation in contract["relations"]:
                targets = ", ".join(relation["targets"])
                storage = "stored" if relation["persisted"] else "derived"
                print(
                    f"  {relation['name']} -> {targets} "
                    f"({relation['cardinality']}, {storage}, "
                    f"{relation['authority']})"
                )
        for error in errors:
            print(f"ERROR: {error}")
        if not errors:
            print("Mutation contracts valid.")

    return 1 if args.check and errors else 0
