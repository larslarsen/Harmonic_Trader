"""Read the complete published CEX-002 release in place, one selected file at a time.

The publication hash is the authority. Manifests describe the only readable files;
the reader neither searches the data tree nor creates a second data catalog. Source
availability is unknown. Millisecond event filters are UTC half-open [start, end).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

PUBLICATION_SHA256 = "5ea22270b71064c94c4f6dc60f3f045219742a3130cfdb1293b6cbe47a99a30d"
PUBLICATION_DIR = "data/.cex002_harmonic_bundle/.publication"
PRODUCTS = (
    "binance_usdm_perpetual_membership",
    "binance_usdm_bar_1h",
    "binance_usdm_trade_flow_1h",
    "binance_usdm_open_interest_5m",
    "binance_usdm_funding_realized",
    "binance_usdm_funding_indicative_1h",
    "binance_usdm_mark_index_basis_1h",
    "binance_usdm_liquidation_observed_daily",
    "binance_usdm_cost_calibration",
    "binance_usdm_coverage_gap",
    "binance_usdm_harmonic_bundle",
)
MANIFEST_LIMIT = 64 * 2**20
PUBLICATION_LIMIT = 8 * 2**20
METADATA_LIMIT = 64 * 2**20
MAX_BATCH_ROWS = 65_536
HASH_CHUNK = 1024 * 1024

_TIME_FIELDS = {
    "binance_usdm_bar_1h": {"": "close_time"},
    "binance_usdm_trade_flow_1h": {"": "close_time"},
    "binance_usdm_open_interest_5m": {"": "create_time"},
    "binance_usdm_funding_realized": {"": "calc_time"},
    "binance_usdm_funding_indicative_1h": {"": "close_time"},
    "binance_usdm_mark_index_basis_1h": {"": "close_time"},
    "binance_usdm_liquidation_observed_daily": {"": "event_time_ms"},
    "binance_usdm_cost_calibration": {
        "retained_book_depth": "timestamp", "retained_book_ticker": "event_time",
    },
}


class Cex002ReaderError(ValueError):
    """A release identity, selected file, filter, or schema is invalid."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise Cex002ReaderError(message)


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _safe_path(root: Path, relative: str) -> Path:
    _need(type(relative) is str and relative and not relative.startswith("/") and "\\" not in relative,
          "release path is not relative")
    parts = relative.split("/")
    _need(all(part not in {"", ".", ".."} for part in parts), "release path escapes its root")
    current = root
    for index, part in enumerate(parts):
        current = current / part
        facts = current.lstat()
        _need(not stat.S_ISLNK(facts.st_mode), "release path has a symlink")
        _need(stat.S_ISREG(facts.st_mode) if index == len(parts) - 1 else stat.S_ISDIR(facts.st_mode),
              "release path has an unexpected file type")
    return current


def _signature(facts: os.stat_result) -> tuple[int, int, int, int, int]:
    return facts.st_dev, facts.st_ino, facts.st_size, facts.st_mtime_ns, facts.st_ctime_ns


def _hash_file(root: Path, relative: str, maximum: int | None = None) -> tuple[bytes | None, int, tuple[int, int, int, int, int], str]:
    path = _safe_path(root, relative)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        first = os.fstat(descriptor)
        _need(stat.S_ISREG(first.st_mode), "release input is not regular")
        if maximum is not None:
            _need(first.st_size <= maximum, "release metadata exceeds its read bound")
        digest = hashlib.sha256()
        body = bytearray() if maximum is not None else None
        size = 0
        while block := os.read(descriptor, HASH_CHUNK):
            size += len(block)
            _need(maximum is None or size <= maximum, "release metadata exceeds its read bound")
            digest.update(block)
            if body is not None:
                body.extend(block)
        last = os.fstat(descriptor)
        _need(_signature(first) == _signature(last) and size == first.st_size,
              "release input changed during hashing")
        rebound = _safe_path(root, relative).stat()
        _need(_signature(first) == _signature(rebound),
              "release path changed during hashing")
        return (bytes(body) if body is not None else None, size, _signature(first), digest.hexdigest())
    finally:
        os.close(descriptor)


def _json_file(root: Path, relative: str, sha256: str, size: int | None, maximum: int) -> dict[str, Any]:
    body, found_size, _signature_value, found_sha = _hash_file(root, relative, maximum)
    _need(found_sha == sha256 and (size is None or size == found_size), "release metadata pin mismatch")
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise Cex002ReaderError("release metadata is not JSON") from exc
    _need(type(parsed) is dict, "release metadata root is not an object")
    return parsed


@dataclass(frozen=True, slots=True)
class FileRef:
    dataset_id: str
    product: str
    manifest_sha256: str
    relative_path: str
    sha256: str
    byte_size: int
    rows: int
    kind: str
    role: str
    component: str
    native_symbol: str | None
    utc_month: str | None
    schema_ref: str | None


@dataclass(frozen=True, slots=True)
class ReleasedRow:
    file: FileRef
    ordinal: int  # zero-based physical row ordinal within this Parquet file
    fields: Mapping[str, Any]


class Cex002ReleaseReader:
    """Immutable manifest index with on-demand physical authentication and Arrow reads."""

    def __init__(self, root: Path | str, publication_sha256: str = PUBLICATION_SHA256) -> None:
        self.root = Path(root).absolute()
        facts = self.root.lstat()
        _need(stat.S_ISDIR(facts.st_mode) and not stat.S_ISLNK(facts.st_mode),
              "data root must be a real directory")
        _need(_hex64(publication_sha256), "publication SHA-256 must be lowercase hex")
        self.publication_sha256 = publication_sha256
        self.publication = _json_file(
            self.root, f"{PUBLICATION_DIR}/{publication_sha256}.json",
            publication_sha256, None, PUBLICATION_LIMIT,
        )
        publication = self.publication
        _need(publication.get("document_type") == "cex002_harmonic_bundle_publication"
              and publication.get("schema_version") == 1 and publication.get("consumable") is True
              and publication.get("catalog_commit_required") is True,
              "publication is not an admitted consumable CEX-002 release")
        _need(_hex64(publication.get("prepared_sha256")) and _hex64(publication.get("proof_sha256"))
              and _hex64(publication.get("checker_source_sha256")),
              "publication authority bindings are malformed")
        entries = publication.get("datasets")
        _need(type(entries) is list and len(entries) == len(PRODUCTS), "publication does not contain eleven datasets")
        self._manifests: dict[str, dict[str, Any]] = {}
        self._files: dict[str, tuple[FileRef, ...]] = {}
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for expected_type, entry in zip(PRODUCTS, entries, strict=True):
            _need(type(entry) is dict and entry.get("dataset_type") == expected_type,
                  "publication dataset order or type changed")
            manifest_sha = entry.get("manifest_sha256")
            manifest_file_sha = entry.get("manifest_file_sha256")
            manifest_bytes = entry.get("manifest_bytes")
            _need(_hex64(manifest_sha) and _hex64(manifest_file_sha)
                  and type(manifest_bytes) is int and 0 < manifest_bytes <= MANIFEST_LIMIT,
                  "manifest authority is malformed")
            manifest = _json_file(self.root, entry.get("manifest_relative_path"),
                                  manifest_file_sha, manifest_bytes, MANIFEST_LIMIT)
            dataset_id = entry.get("dataset_id")
            _need(type(dataset_id) is str and dataset_id.startswith("ds_")
                  and dataset_id not in seen_ids and manifest.get("dataset_id") == dataset_id
                  and manifest.get("dataset_type") == expected_type
                  and manifest.get("manifest_sha256") == manifest_sha,
                  "manifest does not match publication identity")
            seen_ids.add(dataset_id)
            registry = manifest.get("quality_summary", {}).get("schema_registry")
            _need(type(registry) is dict and registry.get("version") == 1
                  and type(registry.get("contracts")) is dict,
                  "manifest schema registry is missing")
            for key, contract in registry["contracts"].items():
                _need(_hex64(key) and type(contract) is list and contract
                      and hashlib.sha256(_canonical(contract)).hexdigest() == key,
                      "manifest schema contract hash changed")
            files = manifest.get("files")
            _need(type(files) is list and files, "manifest contains no files")
            references: list[FileRef] = []
            for item in files:
                _need(type(item) is dict and type(item.get("partition")) is dict,
                      "manifest file reference is malformed")
                partition = item["partition"]
                relative = item.get("relative_path")
                kind = partition.get("kind")
                _need(type(relative) is str and relative not in seen_paths
                      and _hex64(item.get("sha256")) and type(item.get("bytes")) is int
                      and item["bytes"] >= 0 and type(item.get("rows")) is int and item["rows"] >= 0
                      and kind in {"table", "metadata"},
                      "manifest file identity is malformed or duplicated")
                seen_paths.add(relative)
                schema_ref = partition.get("schema_ref")
                _need((kind == "table" and schema_ref in registry["contracts"])
                      or (kind == "metadata" and schema_ref is None and item["rows"] == 0),
                      "file schema reference is not in its manifest")
                references.append(FileRef(
                    dataset_id, expected_type, manifest_sha, relative, item["sha256"],
                    item["bytes"], item["rows"], kind, partition.get("role") or "",
                    partition.get("component") or "", partition.get("native_symbol"),
                    partition.get("utc_month"), schema_ref,
                ))
            self._manifests[expected_type] = manifest
            self._files[expected_type] = tuple(references)
        bundle = self._manifests[PRODUCTS[-1]]
        edges = bundle.get("dependencies")
        _need(type(edges) is list and {(edge.get("role"), edge.get("id")) for edge in edges}
              == {(product, self._manifests[product]["dataset_id"]) for product in PRODUCTS[:-1]}
              and len(edges) == 10, "bundle dependency closure is incomplete")
        self._verified: dict[str, tuple[int, int, int, int, int]] = {}

    def inventory(self) -> tuple[dict[str, Any], ...]:
        result = []
        for product in PRODUCTS:
            files = self._files[product]
            classes = sorted({(item.kind, item.role, item.component) for item in files})
            result.append({
                "product": product, "dataset_id": self._manifests[product]["dataset_id"],
                "manifest_sha256": self._manifests[product]["manifest_sha256"],
                "files": len(files), "rows": sum(item.rows for item in files),
                "components": [{"kind": kind, "role": role, "component": component}
                               for kind, role, component in classes],
            })
        return tuple(result)

    def select(self, product: str, *, symbol: str | None = None, month: str | None = None,
               component: str | None = None, kind: str = "table") -> tuple[FileRef, ...]:
        _need(product in self._files, "product is not in the complete publication")
        _need(kind in {"table", "metadata"}, "kind must be table or metadata")
        _need(symbol is None or type(symbol) is str and bool(symbol), "symbol filter is invalid")
        _need(month is None or type(month) is str and bool(month), "month filter is invalid")
        _need(component is None or type(component) is str, "component filter is invalid")
        chosen = tuple(item for item in self._files[product] if item.kind == kind
                       and (symbol is None or item.native_symbol == symbol)
                       and (month is None or item.utc_month == month)
                       and (component is None or item.component == component))
        _need(bool(chosen), "no declared files match the selection")
        return chosen

    def _verify(self, file: FileRef) -> Path:
        cached = self._verified.get(file.relative_path)
        if cached is None:
            _body, size, signature, digest = _hash_file(self.root, file.relative_path)
            _need((size, digest) == (file.byte_size, file.sha256),
                  "selected file bytes differ from published manifest")
            self._verified[file.relative_path] = signature
        else:
            path = _safe_path(self.root, file.relative_path)
            facts = path.stat()
            _need(_signature(facts) == cached,
                  "previously verified file path changed")
        return _safe_path(self.root, file.relative_path)

    def _schema(self, file: FileRef, actual: pa.Schema) -> None:
        contract = self._manifests[file.product]["quality_summary"]["schema_registry"]["contracts"][file.schema_ref]
        def normal_type(value: str) -> str:
            return "list<string>" if value in {"list<item: string>", "list<element: string>"} else value
        expected = [(field["name"], normal_type(field["arrow_type"]), field["nullable"])
                    for field in contract]
        observed = [(field.name, normal_type(str(field.type)), field.nullable) for field in actual]
        _need(observed == expected, "selected Parquet schema differs from manifest registry")

    @staticmethod
    def event_time_ms(product: str, component: str, fields: Mapping[str, Any]) -> int:
        key = _TIME_FIELDS.get(product, {}).get(component)
        _need(key is not None, "selected rows have no supported market event-time projection")
        value = fields.get(key)
        _need(type(value) is int and value >= 0, "market event time is not a millisecond integer")
        if product == "binance_usdm_liquidation_observed_daily":
            interval = fields.get("source_interval_seconds")
            _need(type(interval) is int and interval > 0,
                  "liquidation source interval is invalid")
            value += interval * 1000
        return value

    def iter_batches(self, product: str, *, symbol: str | None = None, month: str | None = None,
                     component: str | None = None, start_ms: int | None = None,
                     end_ms: int | None = None, batch_rows: int = 2048) -> Iterator[tuple[FileRef, pa.RecordBatch]]:
        for file, batch, _ordinals in self._iter_batches_with_ordinals(
                product, symbol=symbol, month=month, component=component,
                start_ms=start_ms, end_ms=end_ms, batch_rows=batch_rows):
            yield file, batch

    def _iter_batches_with_ordinals(self, product: str, *, symbol: str | None,
                                    month: str | None, component: str | None,
                                    start_ms: int | None, end_ms: int | None,
                                    batch_rows: int) -> Iterator[tuple[FileRef, pa.RecordBatch, list[int]]]:
        _need(type(batch_rows) is int and 0 < batch_rows <= MAX_BATCH_ROWS,
              "batch_rows exceeds the bounded Arrow read size")
        _need((start_ms is None or type(start_ms) is int and start_ms >= 0)
              and (end_ms is None or type(end_ms) is int and end_ms >= 0)
              and (start_ms is None or end_ms is None or start_ms < end_ms),
              "time filters must be nonnegative UTC milliseconds in [start,end)")
        files = self.select(product, symbol=symbol, month=month, component=component)
        if start_ms is not None or end_ms is not None:
            _need(all(item.component in _TIME_FIELDS.get(product, {}) for item in files),
                  "time filter is unsupported for a selected reference or gap component")
        for file in files:
            path = self._verify(file)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            with os.fdopen(descriptor, "rb") as stream:
                facts = os.fstat(stream.fileno())
                _need(_signature(facts) == self._verified[file.relative_path],
                      "selected file changed after authentication")
                parquet = pq.ParquetFile(stream)
                self._schema(file, parquet.schema_arrow)
                _need(parquet.metadata.num_rows == file.rows,
                      "selected Parquet footer row count differs from manifest")
                offset = 0
                for batch in parquet.iter_batches(batch_size=batch_rows):
                    ordinals = list(range(offset, offset + batch.num_rows))
                    offset += batch.num_rows
                    if start_ms is not None or end_ms is not None:
                        key = _TIME_FIELDS[product][file.component]
                        times = batch.column(batch.schema.get_field_index(key))
                        if product == "binance_usdm_liquidation_observed_daily":
                            intervals = batch.column(batch.schema.get_field_index("source_interval_seconds"))
                            times = pc.add(times, pc.multiply(intervals, 1000))
                        mask = None
                        if start_ms is not None:
                            mask = pc.greater_equal(times, start_ms)
                        if end_ms is not None:
                            below = pc.less(times, end_ms)
                            mask = below if mask is None else pc.and_(mask, below)
                        chosen = pc.indices_nonzero(mask).to_pylist()
                        ordinals = [ordinals[index] for index in chosen]
                        batch = batch.take(pa.array(chosen, type=pa.int32()))
                    if batch.num_rows:
                        yield file, batch, ordinals
                current = _safe_path(self.root, file.relative_path).stat()
                _need(_signature(current) == self._verified[file.relative_path],
                      "selected file changed while reading")

    def iter_rows(self, product: str, *, symbol: str | None = None, month: str | None = None,
                  component: str | None = None, start_ms: int | None = None,
                  end_ms: int | None = None, batch_rows: int = 2048) -> Iterator[ReleasedRow]:
        for file, batch, ordinals in self._iter_batches_with_ordinals(
                product, symbol=symbol, month=month, component=component,
                start_ms=start_ms, end_ms=end_ms, batch_rows=batch_rows):
            for ordinal, values in zip(ordinals, batch.to_pylist(), strict=True):
                yield ReleasedRow(file, ordinal, values)

    def iter_metadata(self, product: str, *, symbol: str | None = None, month: str | None = None,
                      component: str | None = None) -> Iterator[tuple[FileRef, Any]]:
        for file in self.select(product, symbol=symbol, month=month,
                                component=component, kind="metadata"):
            _need(file.byte_size <= METADATA_LIMIT, "selected metadata exceeds read bound")
            path = self._verify(file)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            with os.fdopen(descriptor, "rb") as stream:
                _need(_signature(os.fstat(stream.fileno())) == self._verified[file.relative_path],
                      "selected metadata changed after authentication")
                body = stream.read(METADATA_LIMIT + 1)
                _need(len(body) == file.byte_size
                      and _signature(os.fstat(stream.fileno())) == self._verified[file.relative_path]
                      and _signature(_safe_path(self.root, file.relative_path).stat())
                      == self._verified[file.relative_path], "selected metadata changed while reading")
            try:
                yield file, json.loads(body)
            except (TypeError, ValueError) as exc:
                raise Cex002ReaderError("selected metadata is not JSON") from exc
