from __future__ import annotations

import json
from dataclasses import replace

import pytest

from harmonic_trader.experiments.lock import (
    REQUIRED_BUNDLE_ROLES,
    BundleLock,
    BundleProductBinding,
    ExperimentLock,
    ExperimentLockError,
    RuntimeLock,
    freeze_experiment,
    parse_experiment_lock,
)
from harmonic_trader.experiments.trials import (
    ModelFamily,
    TrialLedger,
    TrialLedgerError,
    parse_trial_ledger,
)


def _hash(character: str) -> str:
    return character * 64


def _ledger(*, include_all: bool = True) -> TrialLedger:
    ledger = TrialLedger()
    families = tuple(ModelFamily)
    if not include_all:
        families = families[:-1]
    for index, family in enumerate(families, start=1):
        character = format(index, "x")
        ledger = ledger.append(
            trial_id=f"{family.value}-primary",
            family=family,
            pivot_config_sha256=_hash(character),
            feature_config_sha256=_hash(character),
            model_config_sha256=_hash(character),
            selection_config_sha256=_hash(character),
            execution_config_sha256=_hash(character),
            universe_config_sha256=_hash(character),
            outcome_config_sha256=_hash(character),
        )
    return ledger


def _product(role: str, index: int) -> BundleProductBinding:
    character = format(index + 1, "x")
    return BundleProductBinding(
        role=role,
        dataset_id=f"ds_{index}",
        manifest_sha256=_hash(character),
        schema_name=f"schema_{index}",
        schema_version="1.0.0",
        coverage_dataset_id=f"coverage_{index}",
        coverage_manifest_sha256=_hash(character),
    )


def _bundle(*, reverse: bool = False) -> BundleLock:
    products = tuple(
        _product(role, index) for index, role in enumerate(REQUIRED_BUNDLE_ROLES)
    )
    if reverse:
        products = tuple(reversed(products))
    return BundleLock(
        bundle_id="binance-usdm-harmonic-v1",
        descriptor_sha256=_hash("a"),
        mapping_dataset_id="binance-usdm-contract-map-v1",
        mapping_manifest_sha256=_hash("b"),
        products=products,
    )


def _runtime() -> RuntimeLock:
    return RuntimeLock(
        harmonic_commit="c" * 40,
        environment_lock_sha256=_hash("d"),
        python_version="3.13.7",
        nautilus_trader_version="1.220.0",
        catalog_serialization_version="1",
    )


def _lock() -> ExperimentLock:
    return freeze_experiment(
        experiment_id="cex-primary-v1",
        specification_sha256=_hash("e"),
        bundle=_bundle(),
        runtime=_runtime(),
        trial_ledger=_ledger(),
        holdout_boundary_us=2_000_000,
    )


def test_trial_ledger_is_append_only_and_content_addressed() -> None:
    empty = TrialLedger()
    first = empty.append(
        trial_id="full-primary",
        family=ModelFamily.FULL,
        pivot_config_sha256=_hash("1"),
        feature_config_sha256=_hash("1"),
        model_config_sha256=_hash("1"),
        selection_config_sha256=_hash("1"),
        execution_config_sha256=_hash("1"),
        universe_config_sha256=_hash("1"),
        outcome_config_sha256=_hash("1"),
    )
    second = first.append(
        trial_id="micro-primary",
        family=ModelFamily.MICRO,
        pivot_config_sha256=_hash("2"),
        feature_config_sha256=_hash("2"),
        model_config_sha256=_hash("2"),
        selection_config_sha256=_hash("2"),
        execution_config_sha256=_hash("2"),
        universe_config_sha256=_hash("2"),
        outcome_config_sha256=_hash("2"),
    )
    assert empty.records == ()
    assert second.records[:1] == first.records
    assert second.sha256 != first.sha256


def test_trial_ledger_round_trips_only_canonical_bytes() -> None:
    ledger = _ledger()
    assert parse_trial_ledger(ledger.to_bytes()) == ledger
    pretty = json.dumps(ledger.to_payload(), indent=2).encode()
    with pytest.raises(TrialLedgerError, match="canonical"):
        parse_trial_ledger(pretty)


def test_trial_ids_and_ordinals_must_be_unique_and_contiguous() -> None:
    ledger = _ledger()
    with pytest.raises(TrialLedgerError, match="contiguous"):
        TrialLedger(records=(replace(ledger.records[0], ordinal=2),))
    with pytest.raises(TrialLedgerError, match="duplicate"):
        TrialLedger(records=(ledger.records[0], replace(ledger.records[0], ordinal=2)))


def test_bundle_requires_every_role_and_canonicalizes_order() -> None:
    assert _bundle(reverse=True) == _bundle()
    with pytest.raises(ExperimentLockError, match="complete and unique"):
        BundleLock(
            bundle_id="bundle",
            descriptor_sha256=_hash("a"),
            mapping_dataset_id="mapping",
            mapping_manifest_sha256=_hash("b"),
            products=_bundle().products[:-1],
        )


def test_freeze_refuses_a_price_only_or_incomplete_trial_family() -> None:
    with pytest.raises(TrialLedgerError, match="missing primary families"):
        freeze_experiment(
            experiment_id="cex-primary-v1",
            specification_sha256=_hash("e"),
            bundle=_bundle(),
            runtime=_runtime(),
            trial_ledger=_ledger(include_all=False),
            holdout_boundary_us=2_000_000,
        )


def test_lock_round_trip_preserves_every_identity() -> None:
    lock = _lock()
    parsed = parse_experiment_lock(lock.to_bytes())
    assert parsed == lock
    assert parsed.sha256 == lock.sha256
    assert tuple(product.role for product in parsed.bundle.products) == REQUIRED_BUNDLE_ROLES
    assert parsed.trial_ledger_sha256 == _ledger().sha256


def test_any_product_identity_change_changes_experiment_identity() -> None:
    lock = _lock()
    products = list(lock.bundle.products)
    products[3] = replace(products[3], manifest_sha256=_hash("f"))
    changed = replace(lock, bundle=replace(lock.bundle, products=tuple(products)))
    assert changed.sha256 != lock.sha256


def test_holdout_must_be_sealed_and_runtime_fully_identified() -> None:
    with pytest.raises(ExperimentLockError, match="sealed holdout"):
        replace(_lock(), holdout_state="opened")
    with pytest.raises(ExperimentLockError, match="full Git"):
        replace(_runtime(), harmonic_commit="abc")


def test_parser_rejects_unknown_fields_and_noncanonical_json() -> None:
    lock = _lock()
    payload = lock.to_payload()
    payload["unexpected"] = True
    with pytest.raises(ExperimentLockError, match="unexpected top-level"):
        parse_experiment_lock(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
    with pytest.raises(ExperimentLockError, match="canonical"):
        parse_experiment_lock(json.dumps(lock.to_payload(), indent=2).encode())
