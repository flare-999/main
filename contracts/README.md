# Harpocrates Soroban Contracts

This workspace contains the Stellar Soroban contracts for Harpocrates.

## Contracts

```text
contracts/harpocrates-registry
```

[`HarpocratesRegistry`] stores evidence records for all identity tiers:

- Tier 1 Silent Witness: anonymous Noir proof with nullifier protection.
- Tier 2 Consistent Source: Stellar account signed source.
- Tier 3 Public Seal: approved institutional issuer.

## Build

```powershell
cargo test
stellar contract build
```

## Contract Version

The registry exposes the crate release version on-chain via:

```text
version -> String
```

It returns the value of `env!("CARGO_PKG_VERSION")` from
`contracts/contracts/harpocrates-registry/Cargo.toml`, so clients can
confirm which contract release is deployed. This is distinct from
the data-layout versions reported by `get_schema_version` and
`get_storage_schema_version`.

The function performs no storage access and requires no authorization,
so it is safe to call from any client or monitoring probe.

## Contract Wasm Size Budget

Issue #346 adds a fail-closed size budget for the deployed registry artifact
`harpocrates_registry.wasm` so supply-chain accidents (an unintended
dependency, a disabled optimization, a truncated artifact) fail CI before
they can be deployed.

- Constants live in `contracts/harpocrates-registry/src/wasm_budget.rs`:
  `MAX_WASM_SIZE_BYTES = 128_000` (just under Soroban's 128 KiB upload cap),
  `MIN_WASM_SIZE_BYTES = 10_000`,
  `WASM_SIZE_REGRESSION_BAND_PCT = 15`, plus a typed `WasmBudgetError`
  contract (`ArtifactTooLarge`, `ArtifactTooSmall`, `MissingArtifact`).
- The budget manifest is `devx/wasm_size_budget.json`; the fail-closed gate
  is `devx/wasm_size_budget.py` and runs in the Contracts CI workflow after
  `stellar contract build`.
- The gate fails closed: a missing artifact, malformed manifest, size
  outside the `[min, max]` band, or drift beyond `regression_band_pct` from
  the recorded baseline all fail. Diagnostics carry sizes and digests only —
  never artifact bytes, proofs, witnesses, media, or keys.

```bash
# check the built artifact against the budget
python3 devx/wasm_size_budget.py --check

# deliberately migrate the baseline after a reviewed size change
python3 devx/wasm_size_budget.py --record

cd contracts/contracts/harpocrates-registry
make wasm-budget
```

The module is host-side only (`#[config(not(target_arch = "wasm32"))]`), so the
deployed artifact stays byte-identical to the pre-budget build, and no
exported contract function, storage key, or event schema changes. The
recorded baseline also pins the artifact's SHA-256 digest as an audit trail
for the deployed build. Rollback is reverting the gate step, the manifest,
and the budget module; no on-chain repair is required.

## Identity-Tier Property Tests

Issue #345 adds focused property tests for identity-tier invariants in
`contracts/harpocrates-registry/src/test_identity_tier_properties.r`.

The harness uses a deterministic LCG over reproducible seeds to generate
registration sequences across Silent Witness (tier 1), Consistent Source
(tier 2), and Public Seal (tier 3). After every step it checks:

- tier-shaped privacy fields (no source/issuer on tier 1; nullifier only on tier 1)
- global uniqueness of `proof_id` and `video_hash` across tiers
- nullifier uniqueness for Silent Witness registrations
- pause-domain isolation (pausing one tier never blocks the others)
- lookup consistency (`get_proof` / `get_by_video`)
- rejected duplicates leave prior storage unchanged

Failure messages report only seeds, tier tags, slot indices, and error codes —
never proof bytes, public inputs, witnesses, or media.

Run focused:

```
cargo test -p harpocrates-registry identity_tier -- --nocapture
```

This change is test-only. It does not alter exported contract entry points,
storage keys, or on-chain migration behavior.

## Registry State-Machine Fuzzing

Issue #93 adds deterministic state-machine fuzzing for the registry contract in
`contracts/harpocrates-registry/src/test_state_machine.r`. The harness drives
the real Soroban contract boundary with bounded authorized and adversarial
command streams, including duplicate proof/video/nullifier attempts, wrong
admins, revoked and unknown issuers, invalid and oversized public inputs,
missing verifier/revocation-root cases, replayed non-revocation nullifiers,
admin-transfer replacement/cancellation, TTL expiry, and client-side cancelled,
timed-out, or partial operations that must not reach contract storage.

The oracle is an explicit model of registry storage and status semantics. After
every generated command it checks:

-` Proof`, `Video`, `Nullifier`, `Issuer`, `CredentialRoot`, `Verifier`,
  `ProofTtl`, and `RevocationRoot` query results match the model.
- `get_proof_status` returns `Valid`, `Expired`, `Revoked`, or `NotFound
  according to the modeled timestamp, TTL, and revocation state.
- rejected transitions return the expected `RegistryError`, emit no contract
  event, and leave storage unchanged.
- successful transitions emit only the existing typed lifecycle events, except
  `set_proof_ttl`, which intentionally has no event.
- each command remains inside a fixed fuzz budget ceiling so hostile inputs stay
  bounded in CI.

The CI corpus is the combination of curated adversarial sequences and fixed
generated seeds in `REGRESSION_SEEDS`; it runs as part of normal
cargo test --workspace`, so no workflow or dependency upgrade is required.
Local expansion is opt-in:

```bash
cd contracts
HARPOCRATES_REGISTRY_FUZZ_RUNS=128 \
HARPOCRATES_REGISTRY_FUZZ_SEED=0x9300000000000001 \
cargo test -p harpocrates-registry registry_state_machine -- --nocapture
```

When a case fails, the runner shrinks the command stream by deletion and command
simplification, then prints the original seed, the failing step, the shrunk
command list, and the expected/actual error code. It never prints proof bytes,
public input bytes, witnesses, media, credentials, signatures, or raw metadata.
The model uses deterministic slot numbers and synthetic hashes only.

## Upgrade Compatibility Harness

Issue #347 adds a focused upgrade compatibility harness in
`contracts/harpocrates-registry/src/test_upgrade_compat.r`. It drives the
real `upgrade_storage` / `get_storage_schema_version` boundary with:

- positive V1 init + idempotent upgrade calls
- negative unauthorized upgrade attempts
- legacy registries missing `DataKey::SchemaVersion` (stamp without event)
- regression that Tier-2 source proofs and the verifier pointer survive upgrade

```bash
cd contracts
cargo test -p harpocrates-registry upgrade_compat -- --nocapture
```

### Compatibility, Migration, And Rollback

`upgrade_storage` is the only admin path that advances `DataKey::SchemaVersion`.
At V1 the call is a no-op when the key is already present. Pre-#85 deployments
that lack the key are stamped to V1 without emitting `SchemaUpgraded` because
the on-disk layout is already V1-compatible. Future V2+ migrations must land
in the sequential branch inside `upgrade_storage`, preserve existing proof /
video / nullifier records, and must never log media, secrets, witnesses, or
private keys.

A V1 wasm presented with a stored version greater than V1 leaves that version
and the rest of storage untouched; it does not attempt a downgrade. Operators
must use a wasm that supports the stored schema version.

Rollback is redeploying a prior wasm: additive `SchemaVersion` keys are
ignored by older readers, and no proof rewrite is required for the V1 stamp.
Operators should call `get_storage_schema_version` after upgrade to confirm
the stamped version before rotating verifiers.

### Threat Assumptions

The harness assumes Soroban auth + persistent storage semantics. It does not
exercise live mainnet wasm replace, cryptographic verifier soundness, or real
evidence payloads. Failure modes under test are deterministic `RegistryError`
codes (`Unauthorized`) and privacy-safe absence of `SchemaUpgraded` on no-ops.

### Compatibility And Rollout

This fuzzing change is test-only. It does not alter exported contract
functions, storage keys, event schemas, proof/public-input formats, verifier
domains, script arguments, or deployed artifact compatibility. There is no
migration. Rollout is enabling the new tests in CI through the existing
contracts workflow. Rollback is removal or revert of the test module and this
documentation; no on-chain repair is needed.

### Signals And Privacy

Production observers continue to rely on existing typed events:

```text
["proof", "reg", proof_id]        => video_hash, tier, status
["proof", "revoke", proof_id]     => status
["issuer", "add", issuer]         => metadata_hash
["issuer", "revoke", issuer]      => {}
["verif", "set", verifier]        => {}
["credroot", "add", root]       => metadata_hash, issued_at
["credroot", "revoke", root]    => {}
["admin", "propose", pending]     => current_admin
["admin", "cancel", pending]      => current_admin
["admin", "accept", new_admin]     => previous_admin
["revroot", "set", root]          => {}
["nonrev", "check", root]        => nullifier, revocation_root
```

Failures are observable as deterministic transaction reverts with typed
`RegistryError` codes, not as extra events. The fuzz runner treats failed,
cancelled, timed-out, and partial operations as privacy-sensitive and asserts
that they do not emit success signals or write registry records.

### Threat Assumptions And Limits

The harness assumes Soroban ledger execution is atomic and serializes
concurrent submissions. Concurrent behavior is modeled as interleaved retries
and collisions against the same global `Proof`, `Video`, and `Nullifier` keys.
Client-side timeouts/cancellations are modeled as commands that never submit a
transaction; submitted partial failures are modeled through contract calls that
fail after parsing or authorization gates. Real user evidence, production
secrets, live mainnet behavior, and cryptographic verifier soundness are out of
scope for this test module. Cryptographic vectors remain owned by the Noir and
verifier conformance fixtures.

### Troubleshooting

Use the printed seed and shrunk commands to reproduce a failure with
`HARPOCRATES_REGISTRY_FUZZ_SEED`. If the failure is a budget ceiling only,
compare against `src/test_budget.rs` before raising the fuzz ceiling. If a
contract error changes intentionally, update the model order to match the
contract's exact validation order and keep the fixed seed in the corpus.

The current registry exports:

```text
init
get_storage_schema_version
upgrade_storage
propose_admin
cancel_admin_transfer
accept_admin
get_schema_version
is_admin
is_issuer
add_credential_root
revoke_credential_root
get_credential_root
add_issuer
revoke_issuer
set_verifier
get_verifier
set_proof_ttl
get_proof_ttl
register_anonymous
register_anonymous_verified
register_source
register_seal
revoke_proof
get_proof
get_by_video
has_nullifier
get_issuer
rotate_issuer
finalize_issuer_rotation
get_issuer_rotation
is_issuer_verifiable
set_revocation_root
get_revocation_root
check_non_revocation
get_proof_status
get_proof_history
get_proof_history_at
get_proof_history_count
open_dispute
respond_dispute
resolve_dispute
dismiss_dispute
supersede_dispute
get_dispute
get_open_dispute_count
verify_proof
expire_proof
correct_proof
set_guardian
get_guardian
pause
unpause
is_paused
get_pause_state
version
```

## Staged verifier rotation

The registry now supports a staged verifier transition so a new verifier can be introduced without an unsafe instant cutover:

1. The admin schedules a pending verifier with an activation ledger and rollback window.
2. Once the ledger reaches the activation threshold, the admin activates the pending verifier.
3. During the rollback window, the admin can revert to the previous verifier if the new verifier misbehaves or fails validation.

The rotation state is persisted and can be inspected via `get_verifier_state`.

### Operational flow

```powershell
./scripts/schedule-verifier-rotation.ps1 -ContractId YOUR_REGISTRY -Admin harpocrates-admin -Verifier YOUR_NEW_VERIFIER -ActivationLedger 1000 -OverlapWindow 100 -RollbackWindow 200
./scripts/activate-verifier-rotation.ps1 -ContractId YOUR_REGISTRY -Admin harpocrates-admin
./scripts/rollback-verifier-rotation.ps1 -ContractId YOUR_REGISTRY -Admin harpocrates-admin
```

### Rollback and troubleshooting

- Activation is rejected before the configured activation ledger.
- Rollback is rejected once the rollback window clo
