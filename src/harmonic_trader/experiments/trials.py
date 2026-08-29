"""Immutable predeclared trial accounting for the complete searched family."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from harmonic_trader.experiments._canonical import canonical_json_bytes, sha256_hex


class TrialLedgerError(ValueError):
    """A trial definition or ledger is incomplete, ambiguous, or mutable."""


class ModelFamily(StrEnum):
    FULL = "full"
    MICRO = "micro"
    GEOMETRY = "geometry"
    CARNEY_MICRO = "carney_micro"
    CARNEY = "carney"
    NULL = "null"


PRIMARY_FAMILIES = frozenset(ModelFamily)
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _identifier(value: object, *, field: str) -> str:
    result = str(value).strip()
    if not _IDENTIFIER.fullmatch(result):
        raise TrialLedgerError(
            f"{field} must contain lowercase letters, digits, dots, underscores, or hyphens"
        )
    return result


def _sha256(value: object, *, field: str) -> str:
    result = str(value).strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise TrialLedgerError(f"{field} must be a lowercase SHA-256")
    return result


@dataclass(frozen=True, slots=True)
class TrialDefinition:
    ordinal: int
    trial_id: str
    family: ModelFamily
    pivot_config_sha256: str
    feature_config_sha256: str
    model_config_sha256: str
    selection_config_sha256: str
    execution_config_sha256: str
    universe_config_sha256: str
    outcome_config_sha256: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal <= 0
        ):
            raise TrialLedgerError("ordinal must be a positive integer")
        object.__setattr__(
            self, "trial_id", _identifier(self.trial_id, field="trial_id")
        )
        if not isinstance(self.family, ModelFamily):
            raise TrialLedgerError("family must be a ModelFamily")
        for field in (
            "pivot_config_sha256",
            "feature_config_sha256",
            "model_config_sha256",
            "selection_config_sha256",
            "execution_config_sha256",
            "universe_config_sha256",
            "outcome_config_sha256",
        ):
            object.__setattr__(
                self, field, _sha256(getattr(self, field), field=field)
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "trial_id": self.trial_id,
            "family": self.family.value,
            "pivot_config_sha256": self.pivot_config_sha256,
            "feature_config_sha256": self.feature_config_sha256,
            "model_config_sha256": self.model_config_sha256,
            "selection_config_sha256": self.selection_config_sha256,
            "execution_config_sha256": self.execution_config_sha256,
            "universe_config_sha256": self.universe_config_sha256,
            "outcome_config_sha256": self.outcome_config_sha256,
        }


@dataclass(frozen=True, slots=True)
class TrialLedger:
    records: tuple[TrialDefinition, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrialLedgerError("unsupported trial-ledger schema version")
        identifiers: set[str] = set()
        for expected, record in enumerate(self.records, start=1):
            if record.ordinal != expected:
                raise TrialLedgerError("trial ordinals must be contiguous from one")
            if record.trial_id in identifiers:
                raise TrialLedgerError(f"duplicate trial_id: {record.trial_id}")
            identifiers.add(record.trial_id)

    @property
    def families(self) -> frozenset[ModelFamily]:
        return frozenset(record.family for record in self.records)

    def require_primary_families(self) -> None:
        missing = sorted(family.value for family in PRIMARY_FAMILIES - self.families)
        if missing:
            raise TrialLedgerError(f"trial ledger is missing primary families: {missing!r}")

    def append(
        self,
        *,
        trial_id: str,
        family: ModelFamily,
        pivot_config_sha256: str,
        feature_config_sha256: str,
        model_config_sha256: str,
        selection_config_sha256: str,
        execution_config_sha256: str,
        universe_config_sha256: str,
        outcome_config_sha256: str,
    ) -> TrialLedger:
        record = TrialDefinition(
            ordinal=len(self.records) + 1,
            trial_id=trial_id,
            family=family,
            pivot_config_sha256=pivot_config_sha256,
            feature_config_sha256=feature_config_sha256,
            model_config_sha256=model_config_sha256,
            selection_config_sha256=selection_config_sha256,
            execution_config_sha256=execution_config_sha256,
            universe_config_sha256=universe_config_sha256,
            outcome_config_sha256=outcome_config_sha256,
        )
        return TrialLedger(records=(*self.records, record))

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "records": [record.to_payload() for record in self.records],
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    @property
    def sha256(self) -> str:
        return sha256_hex(self.to_bytes())


_TRIAL_FIELDS = {
    "ordinal",
    "trial_id",
    "family",
    "pivot_config_sha256",
    "feature_config_sha256",
    "model_config_sha256",
    "selection_config_sha256",
    "execution_config_sha256",
    "universe_config_sha256",
    "outcome_config_sha256",
}


def parse_trial_ledger(raw: bytes) -> TrialLedger:
    try:
        payload: Any = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TrialLedgerError(f"invalid trial-ledger JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "records"}:
        raise TrialLedgerError("trial ledger has unexpected top-level fields")
    if not isinstance(payload["records"], list):
        raise TrialLedgerError("trial ledger records must be a list")
    records: list[TrialDefinition] = []
    for item in payload["records"]:
        if not isinstance(item, dict) or set(item) != _TRIAL_FIELDS:
            raise TrialLedgerError("trial definition has unexpected fields")
        try:
            records.append(
                TrialDefinition(
                    ordinal=item["ordinal"],
                    trial_id=item["trial_id"],
                    family=ModelFamily(item["family"]),
                    pivot_config_sha256=item["pivot_config_sha256"],
                    feature_config_sha256=item["feature_config_sha256"],
                    model_config_sha256=item["model_config_sha256"],
                    selection_config_sha256=item["selection_config_sha256"],
                    execution_config_sha256=item["execution_config_sha256"],
                    universe_config_sha256=item["universe_config_sha256"],
                    outcome_config_sha256=item["outcome_config_sha256"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TrialLedgerError(f"invalid trial definition: {exc}") from exc
    ledger = TrialLedger(
        records=tuple(records), schema_version=payload["schema_version"]
    )
    if raw != ledger.to_bytes():
        raise TrialLedgerError("trial ledger is not canonical JSON")
    return ledger
