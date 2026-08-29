"""Immutable identity lock required before any scored Harmonic Trader run."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from harmonic_trader.data.contracts import Product
from harmonic_trader.experiments._canonical import canonical_json_bytes, sha256_hex
from harmonic_trader.experiments.trials import (
    ModelFamily,
    PRIMARY_FAMILIES,
    TrialLedger,
)


class ExperimentLockError(ValueError):
    """An experiment lock omits or changes a required scientific identity."""


REQUIRED_BUNDLE_ROLES = (
    "binance_usdm_perpetual_membership",
    Product.MARKET_BAR.value,
    Product.TRADE_FLOW.value,
    Product.OPEN_INTEREST.value,
    Product.FUNDING_REALIZED.value,
    Product.FUNDING_INDICATIVE.value,
    Product.MARK_INDEX_BASIS.value,
    Product.LIQUIDATION_OBSERVED.value,
    Product.COST_CALIBRATION.value,
)
_ROLE_ORDER = {role: index for index, role in enumerate(REQUIRED_BUNDLE_ROLES)}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


def _text(value: object, *, field: str) -> str:
    result = str(value).strip()
    if not result or not _IDENTIFIER.fullmatch(result):
        raise ExperimentLockError(f"{field} is not a valid immutable identifier")
    return result


def _sha256(value: object, *, field: str) -> str:
    result = str(value).strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ExperimentLockError(f"{field} must be a lowercase SHA-256")
    return result


def _commit(value: object) -> str:
    result = str(value).strip().lower()
    if len(result) not in (40, 64) or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise ExperimentLockError("harmonic_commit must be a full Git object identity")
    return result


@dataclass(frozen=True, slots=True)
class BundleProductBinding:
    role: str
    dataset_id: str
    manifest_sha256: str
    schema_name: str
    schema_version: str
    coverage_dataset_id: str
    coverage_manifest_sha256: str

    def __post_init__(self) -> None:
        role = _text(self.role, field="role")
        if role not in _ROLE_ORDER:
            raise ExperimentLockError(f"unexpected bundle role: {role}")
        object.__setattr__(self, "role", role)
        for field in (
            "dataset_id",
            "schema_name",
            "schema_version",
            "coverage_dataset_id",
        ):
            object.__setattr__(
                self, field, _text(getattr(self, field), field=field)
            )
        for field in ("manifest_sha256", "coverage_manifest_sha256"):
            object.__setattr__(
                self, field, _sha256(getattr(self, field), field=field)
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "dataset_id": self.dataset_id,
            "manifest_sha256": self.manifest_sha256,
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "coverage_dataset_id": self.coverage_dataset_id,
            "coverage_manifest_sha256": self.coverage_manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class BundleLock:
    bundle_id: str
    descriptor_sha256: str
    mapping_dataset_id: str
    mapping_manifest_sha256: str
    products: tuple[BundleProductBinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bundle_id", _text(self.bundle_id, field="bundle_id")
        )
        object.__setattr__(
            self,
            "descriptor_sha256",
            _sha256(self.descriptor_sha256, field="descriptor_sha256"),
        )
        object.__setattr__(
            self,
            "mapping_dataset_id",
            _text(self.mapping_dataset_id, field="mapping_dataset_id"),
        )
        object.__setattr__(
            self,
            "mapping_manifest_sha256",
            _sha256(
                self.mapping_manifest_sha256, field="mapping_manifest_sha256"
            ),
        )
        products = tuple(sorted(self.products, key=lambda item: _ROLE_ORDER[item.role]))
        roles = tuple(product.role for product in products)
        if roles != REQUIRED_BUNDLE_ROLES:
            missing = sorted(set(REQUIRED_BUNDLE_ROLES) - set(roles))
            extra = sorted(set(roles) - set(REQUIRED_BUNDLE_ROLES))
            duplicates = sorted(role for role in set(roles) if roles.count(role) > 1)
            raise ExperimentLockError(
                "bundle roles are not complete and unique: "
                f"missing={missing!r}, extra={extra!r}, duplicates={duplicates!r}"
            )
        object.__setattr__(self, "products", products)

    def to_payload(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "descriptor_sha256": self.descriptor_sha256,
            "mapping_dataset_id": self.mapping_dataset_id,
            "mapping_manifest_sha256": self.mapping_manifest_sha256,
            "products": [product.to_payload() for product in self.products],
        }


@dataclass(frozen=True, slots=True)
class RuntimeLock:
    harmonic_commit: str
    environment_lock_sha256: str
    python_version: str
    nautilus_trader_version: str
    catalog_serialization_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "harmonic_commit", _commit(self.harmonic_commit))
        object.__setattr__(
            self,
            "environment_lock_sha256",
            _sha256(self.environment_lock_sha256, field="environment_lock_sha256"),
        )
        for field in (
            "python_version",
            "nautilus_trader_version",
            "catalog_serialization_version",
        ):
            object.__setattr__(
                self, field, _text(getattr(self, field), field=field)
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "harmonic_commit": self.harmonic_commit,
            "environment_lock_sha256": self.environment_lock_sha256,
            "python_version": self.python_version,
            "nautilus_trader_version": self.nautilus_trader_version,
            "catalog_serialization_version": self.catalog_serialization_version,
        }


@dataclass(frozen=True, slots=True)
class ExperimentLock:
    experiment_id: str
    specification_sha256: str
    bundle: BundleLock
    runtime: RuntimeLock
    trial_ledger_sha256: str
    trial_families: tuple[ModelFamily, ...]
    holdout_boundary_us: int
    holdout_state: str = "sealed"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ExperimentLockError("unsupported experiment-lock schema version")
        object.__setattr__(
            self,
            "experiment_id",
            _text(self.experiment_id, field="experiment_id"),
        )
        object.__setattr__(
            self,
            "specification_sha256",
            _sha256(self.specification_sha256, field="specification_sha256"),
        )
        object.__setattr__(
            self,
            "trial_ledger_sha256",
            _sha256(self.trial_ledger_sha256, field="trial_ledger_sha256"),
        )
        families = tuple(sorted(set(self.trial_families), key=lambda item: item.value))
        if set(families) != PRIMARY_FAMILIES:
            missing = sorted(
                family.value for family in PRIMARY_FAMILIES - set(families)
            )
            raise ExperimentLockError(
                f"experiment lock is missing primary trial families: {missing!r}"
            )
        object.__setattr__(self, "trial_families", families)
        if (
            isinstance(self.holdout_boundary_us, bool)
            or not isinstance(self.holdout_boundary_us, int)
            or self.holdout_boundary_us <= 0
        ):
            raise ExperimentLockError("holdout_boundary_us must be a positive timestamp")
        if self.holdout_state != "sealed":
            raise ExperimentLockError("a pre-score experiment lock requires a sealed holdout")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "specification_sha256": self.specification_sha256,
            "bundle": self.bundle.to_payload(),
            "runtime": self.runtime.to_payload(),
            "trial_ledger_sha256": self.trial_ledger_sha256,
            "trial_families": [family.value for family in self.trial_families],
            "holdout_boundary_us": self.holdout_boundary_us,
            "holdout_state": self.holdout_state,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    @property
    def sha256(self) -> str:
        return sha256_hex(self.to_bytes())


def freeze_experiment(
    *,
    experiment_id: str,
    specification_sha256: str,
    bundle: BundleLock,
    runtime: RuntimeLock,
    trial_ledger: TrialLedger,
    holdout_boundary_us: int,
) -> ExperimentLock:
    trial_ledger.require_primary_families()
    return ExperimentLock(
        experiment_id=experiment_id,
        specification_sha256=specification_sha256,
        bundle=bundle,
        runtime=runtime,
        trial_ledger_sha256=trial_ledger.sha256,
        trial_families=tuple(trial_ledger.families),
        holdout_boundary_us=holdout_boundary_us,
    )


_PRODUCT_FIELDS = {
    "role",
    "dataset_id",
    "manifest_sha256",
    "schema_name",
    "schema_version",
    "coverage_dataset_id",
    "coverage_manifest_sha256",
}
_BUNDLE_FIELDS = {
    "bundle_id",
    "descriptor_sha256",
    "mapping_dataset_id",
    "mapping_manifest_sha256",
    "products",
}
_RUNTIME_FIELDS = {
    "harmonic_commit",
    "environment_lock_sha256",
    "python_version",
    "nautilus_trader_version",
    "catalog_serialization_version",
}
_LOCK_FIELDS = {
    "schema_version",
    "experiment_id",
    "specification_sha256",
    "bundle",
    "runtime",
    "trial_ledger_sha256",
    "trial_families",
    "holdout_boundary_us",
    "holdout_state",
}


def parse_experiment_lock(raw: bytes) -> ExperimentLock:
    try:
        payload: Any = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExperimentLockError(f"invalid experiment-lock JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != _LOCK_FIELDS:
        raise ExperimentLockError("experiment lock has unexpected top-level fields")
    bundle_payload = payload["bundle"]
    runtime_payload = payload["runtime"]
    if not isinstance(bundle_payload, dict) or set(bundle_payload) != _BUNDLE_FIELDS:
        raise ExperimentLockError("bundle lock has unexpected fields")
    product_payloads = bundle_payload["products"]
    if not isinstance(product_payloads, list):
        raise ExperimentLockError("bundle products must be a list")
    products: list[BundleProductBinding] = []
    for item in product_payloads:
        if not isinstance(item, dict) or set(item) != _PRODUCT_FIELDS:
            raise ExperimentLockError("bundle product has unexpected fields")
        products.append(BundleProductBinding(**item))
    if not isinstance(runtime_payload, dict) or set(runtime_payload) != _RUNTIME_FIELDS:
        raise ExperimentLockError("runtime lock has unexpected fields")
    try:
        lock = ExperimentLock(
            schema_version=payload["schema_version"],
            experiment_id=payload["experiment_id"],
            specification_sha256=payload["specification_sha256"],
            bundle=BundleLock(
                bundle_id=bundle_payload["bundle_id"],
                descriptor_sha256=bundle_payload["descriptor_sha256"],
                mapping_dataset_id=bundle_payload["mapping_dataset_id"],
                mapping_manifest_sha256=bundle_payload[
                    "mapping_manifest_sha256"
                ],
                products=tuple(products),
            ),
            runtime=RuntimeLock(**runtime_payload),
            trial_ledger_sha256=payload["trial_ledger_sha256"],
            trial_families=tuple(
                ModelFamily(value) for value in payload["trial_families"]
            ),
            holdout_boundary_us=payload["holdout_boundary_us"],
            holdout_state=payload["holdout_state"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentLockError(f"invalid experiment lock: {exc}") from exc
    if raw != lock.to_bytes():
        raise ExperimentLockError("experiment lock is not canonical JSON")
    return lock
