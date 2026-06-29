# Backwards Compatibility Policy

## Version Promise

The current repository is pre-public-beta. The public baseline should be called `v0.1 beta`.

From `v0.1 beta` through the `v1.x` series:

- old saved workflows should load
- old hardware maps should load
- old function manifests should load or migrate
- old module manifests should load or show a clear broken-module placeholder
- old controller/firmware protocol references should either work or migrate

A future `v2` may intentionally fix architecture mistakes, but it should still provide migrations or clear compatibility tooling.

## Compatibility Target

Compatibility means:

- persisted files parse successfully
- missing references remain visible
- users get suggested fixes
- old expected behavior is covered by tests or migration fixtures
- migrations are deterministic and do not silently discard user work

Compatibility does not mean every old bug must stay. It means old projects should keep loading and have a documented path to the new behavior.

## Required Persistent Schema Fields

Before `v0.1 beta`, ensure these files have explicit versions:

- `hardware-map.json`: already has `version`
- workflow JSON: backend-normalized with `schema_version` and legacy `version`
- function manifests: backend model supports `schema_version`
- module manifests: must have `schema_version`
- firmware protocol descriptors: must have `schema_version`

Hardware map controller, device, and group `enabled` fields are additive. Older hardware maps without those fields load as enabled.

## Migration Rules

When a schema changes:

1. Keep the old parser path.
2. Add a migration from old shape to new shape.
3. Preserve unknown fields unless there is a documented reason not to.
4. Keep old IDs as aliases when possible.
5. Add or update fixture tests.
6. Update `docs/ARCHITECTURE_CONTRACTS.md` if the contract changes.

## Broken Reference Behavior

When a saved file points to something missing:

- render a broken block/device/module placeholder
- keep original IDs and metadata
- show what could not be resolved
- suggest repair actions
- avoid deleting the unresolved item on save unless the user explicitly removes it

Examples:

- workflow block references a missing advanced function
- function references a missing hardware device
- hardware device references a missing controller
- module references firmware that cannot be built
- API block references a missing secret name

Hardware maps without `function_assignments` load as having no function-to-hardware overrides. Missing function hardware is preserved by creating disabled, unconnected placeholders until the operator assigns the function requirement to a physical Hardware Map device.

Hardware maps without `node_positions` load with generated canvas positions. When present, `node_positions` is an additive UI-layout field and does not change physical wiring behavior.

## Test Strategy

Minimum long-term test set:

- golden hardware map load/save tests
- golden workflow load/save tests
- function manifest validation tests
- hardware dependency sync tests
- workflow output contract tests
- firmware requirement collection tests
- broken reference rendering tests
- migration tests for every persisted schema version
- simulated workflow behavior tests once simulation exists

The goal is not only passing tests. The goal is to let future agents detect when a change breaks old expected behavior and then repair it intentionally.

Current implemented compatibility tests live in `backend/tests/test_schema_compatibility.py`.
