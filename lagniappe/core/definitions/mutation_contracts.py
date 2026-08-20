"""Canonical entity and relationship mutation contract registry."""

from .mutations import (
    DeletePolicy,
    EntityMutationContract,
    MutationEffectType,
    RelationAuthority,
    RelationMutationContract,
)


# @testable false
# @covered-by lagniappe/core/definitions/mutation_contracts.py::validate_mutation_contracts
# @reason contract construction is covered by registry completeness validation
def relation(
    name,
    *targets,
    cardinality="one",
    authority=RelationAuthority.SOURCE,
    gateway=None,
    persisted=True,
    on_source_delete=DeletePolicy.PRESERVE,
    on_target_delete=DeletePolicy.PRESERVE,
    mirrored=False,
):
    effects = (
        (MutationEffectType.UPSERT, MutationEffectType.UNLINK)
        if mirrored
        else (MutationEffectType.UPSERT,)
    )
    return RelationMutationContract(
        name=name,
        targets=tuple(targets),
        cardinality=cardinality,
        authority=authority,
        gateway=gateway or f"properties.{name}",
        persisted=persisted,
        on_source_delete=on_source_delete,
        on_target_delete=on_target_delete,
        add_effects=effects,
        replace_effects=effects,
        remove_effects=effects,
    )


ALL_ACTIVITY_TARGETS = (
    "category",
    "file",
    "form",
    "model",
    "page",
    "project",
    "report",
    "task",
    "task_history",
    "user",
)

ALL_FILTER_TARGETS = ("category", "form", "model", "project", "user")


ENTITY_MUTATION_CONTRACTS = {
    contract.kind: contract
    for contract in (
        EntityMutationContract(
            "user",
            (
                relation(
                    "page",
                    "page",
                    authority=RelationAuthority.MIRRORED,
                    gateway="UserPage.value",
                    on_source_delete=DeletePolicy.CASCADE,
                    on_target_delete=DeletePolicy.CASCADE,
                    mirrored=True,
                ),
                relation("groups", "group", "public_group", cardinality="many"),
                relation(
                    "starred",
                    "category",
                    "page",
                    "project",
                    cardinality="many",
                    on_target_delete=DeletePolicy.PRESERVE,
                ),
            ),
        ),
        EntityMutationContract(
            "project",
            (
                relation(
                    "model_tasks",
                    "model",
                    cardinality="many",
                    authority=RelationAuthority.ANCESTOR,
                    gateway="ModelTask.create",
                    persisted=False,
                    on_source_delete=DeletePolicy.CASCADE,
                ),
                relation(
                    "filters",
                    "filter",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                    on_source_delete=DeletePolicy.CASCADE,
                ),
            ),
        ),
        EntityMutationContract(
            "model",
            (
                relation(
                    "project",
                    "project",
                    authority=RelationAuthority.ANCESTOR,
                    on_target_delete=DeletePolicy.CASCADE,
                ),
                relation("form", "form", on_source_delete=DeletePolicy.DELETE_IF_ORPHANED),
            ),
        ),
        EntityMutationContract(
            "file",
            (
                relation(
                    "pages",
                    "page",
                    cardinality="many",
                    authority=RelationAuthority.SOURCE,
                    gateway="AttachedToPages",
                    on_target_delete=DeletePolicy.UNLINK,
                ),
                relation(
                    "tasks",
                    "task",
                    "task_history",
                    cardinality="many",
                    authority=RelationAuthority.MIRRORED,
                    gateway="TaskFiles",
                    on_target_delete=DeletePolicy.UNLINK,
                    mirrored=True,
                ),
                relation("report_user", "user"),
            ),
        ),
        EntityMutationContract(
            "ingress",
            tuple(relation(name, target) for name, target in (
                ("category", "category"),
                ("project", "project"),
                ("model", "model"),
                ("form", "form"),
            )),
        ),
        EntityMutationContract(
            "form",
            (
                relation("groups", "group", "public_group", cardinality="many"),
                relation(
                    "categories",
                    "category",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                ),
                relation(
                    "projects",
                    "project",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                ),
            ),
        ),
        EntityMutationContract(
            "category",
            (
                relation("form", "form"),
                relation("forms", "form", cardinality="many"),
                relation(
                    "pages",
                    "page",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                    on_source_delete=DeletePolicy.UNLINK,
                ),
                relation(
                    "filters",
                    "filter",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                    on_source_delete=DeletePolicy.CASCADE,
                ),
            ),
        ),
        EntityMutationContract(
            "users",
            (
                relation("form", "form"),
                relation("forms", "form", cardinality="many"),
            ),
        ),
        EntityMutationContract(
            "page",
            (
                relation("form", "form"),
                relation("model", "category", "users"),
                relation("categories", "category", cardinality="many"),
                relation("groups", "group", "public_group", cardinality="many"),
                relation(
                    "user",
                    "user",
                    authority=RelationAuthority.MIRRORED,
                    gateway="UserPage.value",
                    on_source_delete=DeletePolicy.CASCADE,
                    on_target_delete=DeletePolicy.CASCADE,
                    mirrored=True,
                ),
                relation(
                    "files",
                    "file",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                    on_source_delete=DeletePolicy.UNLINK,
                ),
                relation(
                    "tasks",
                    "task",
                    "task_history",
                    cardinality="many",
                    authority=RelationAuthority.QUERY,
                    persisted=False,
                    on_source_delete=DeletePolicy.CASCADE,
                ),
            ),
        ),
        EntityMutationContract(
            "task",
            (
                relation("page", "page", on_target_delete=DeletePolicy.CASCADE),
                relation("form", "form"),
                relation("groups", "group", "public_group", cardinality="many"),
                relation("model", "model"),
                relation("project", "project"),
                relation("assigned_to", "page"),
                relation("assigned_by", "page"),
                relation("completed_by", "page"),
                relation("linked_pages", "page", cardinality="many"),
                relation(
                    "files",
                    "file",
                    cardinality="many",
                    authority=RelationAuthority.MIRRORED,
                    gateway="TaskFiles",
                    on_source_delete=DeletePolicy.UNLINK,
                    mirrored=True,
                ),
            ),
        ),
        EntityMutationContract("group"),
        EntityMutationContract("public_group"),
        EntityMutationContract(
            "filter",
            (
                relation("related", *ALL_FILTER_TARGETS, cardinality="many"),
                relation("parent", "category", "project", on_target_delete=DeletePolicy.CASCADE),
                relation("creator", "user"),
            ),
        ),
        EntityMutationContract(
            "task_history",
            (
                relation(
                    "task",
                    "task",
                    authority=RelationAuthority.ANCESTOR,
                    persisted=False,
                ),
                relation("page", "page", on_target_delete=DeletePolicy.CASCADE),
                relation("form", "form"),
                relation("completed_by", "page"),
                relation("linked_pages", "page", cardinality="many"),
                relation(
                    "files",
                    "file",
                    cardinality="many",
                    authority=RelationAuthority.MIRRORED,
                    gateway="TaskFiles",
                    on_source_delete=DeletePolicy.UNLINK,
                    mirrored=True,
                ),
            ),
        ),
        EntityMutationContract(
            "notification",
            (
                relation("parent", "user"),
                relation("target", *ALL_ACTIVITY_TARGETS),
            ),
        ),
        EntityMutationContract(
            "note",
            (
                relation("parent", *ALL_ACTIVITY_TARGETS),
                relation("user", "user"),
            ),
        ),
        EntityMutationContract(
            "form_history",
            (relation("form", "form", authority=RelationAuthority.ANCESTOR),),
        ),
        EntityMutationContract("document_history"),
        EntityMutationContract(
            "job",
            (
                relation("actor", "user"),
                relation("notification", "notification"),
            ),
        ),
        EntityMutationContract("job_lock"),
        EntityMutationContract(
            "report",
            (
                relation("parent", *ALL_ACTIVITY_TARGETS),
                relation("user", "user"),
                relation("input_files", "file", cardinality="many"),
            ),
        ),
        EntityMutationContract("message_conversation"),
        EntityMutationContract("message"),
        EntityMutationContract("mention_marker"),
    )
}


PERSISTED_ENTITY_KINDS = frozenset(ENTITY_MUTATION_CONTRACTS)


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @features mutations
# @dimensions contract lookup
def mutation_contract(kind):
    return ENTITY_MUTATION_CONTRACTS.get(kind)


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @features mutations
# @dimensions contract completeness validation
def validate_mutation_contracts():
    """Return stable validation messages for registry drift."""
    errors = []
    known = set(ENTITY_MUTATION_CONTRACTS)
    for kind, contract in sorted(ENTITY_MUTATION_CONTRACTS.items()):
        if contract.kind != kind:
            errors.append(f"Contract key {kind} declares kind {contract.kind}.")
        relation_names = set()
        for relation_contract in contract.relations:
            if relation_contract.name in relation_names:
                errors.append(f"{kind} declares relation {relation_contract.name} twice.")
            relation_names.add(relation_contract.name)
            unknown = sorted(set(relation_contract.targets) - known)
            if unknown:
                errors.append(
                    f"{kind}.{relation_contract.name} has unknown targets: "
                    + ", ".join(unknown)
                )
            if relation_contract.cardinality not in {"one", "many"}:
                errors.append(
                    f"{kind}.{relation_contract.name} has invalid cardinality."
                )
            if not relation_contract.gateway:
                errors.append(f"{kind}.{relation_contract.name} has no gateway.")
    return errors
