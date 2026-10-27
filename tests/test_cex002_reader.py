"""Small complete-publication fixtures for the in-place CEX-002 reader."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from harmonic_trader.data.cex002 import (
    Cex002ReaderError, Cex002ReleaseReader, PRODUCTS, PUBLICATION_DIR,
)


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


D = pa.decimal128(38, 18)


def _tables() -> dict[str, list[tuple[str, str, str | None, str | None, pa.Table]]]:
    def table(schema: list[tuple[str, pa.DataType]], values: list[tuple[object, ...]]) -> pa.Table:
        return pa.Table.from_pylist([dict(zip((name for name, _ in schema), row, strict=True))
                                     for row in values], schema=pa.schema([pa.field(n, t) for n, t in schema]))

    bar = table([("venue_symbol", pa.string()), ("open_time", pa.int64()),
                 ("close_time", pa.int64()), ("open", D), ("high", D),
                 ("low", D), ("close", D), ("volume", D)], [
        ("BTCUSDT", 0, 3_600_000, Decimal("100"), Decimal("101.25"),
         Decimal("99.5"), Decimal("100.5"), Decimal("1")),
        ("BTCUSDT", 3_600_000, 7_200_000, Decimal("100.5"), Decimal("102.125"),
         Decimal("100"), Decimal("101.75"), Decimal("2.50")),
    ])
    gap = table([("reason", pa.string()), ("required_product", pa.string())],
                [("source_gap", "bar")])
    return {
        PRODUCTS[0]: [("", "reference", None, None, table(
            [("native_symbol", pa.string()), ("membership_state", pa.string())],
            [("BTCUSDT", "included")]))],
        PRODUCTS[1]: [("", "partition", "BTCUSDT", "2025-09", bar),
                      ("quality_gap", "partition", "BTCUSDT", "2025-09", gap)],
        PRODUCTS[2]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("close_time", pa.int64()), ("total_quote_volume", D)],
            [(3_600_000, Decimal("25.000000000000000000"))]))],
        PRODUCTS[3]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("create_time", pa.int64()), ("sum_open_interest", D),
             ("sum_open_interest_value", D)],
            [(3_600_000, Decimal("3"), Decimal("300.000000000000000000"))]))],
        PRODUCTS[4]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("calc_time", pa.int64()), ("last_funding_rate", D)],
            [(3_600_000, Decimal("0.0001"))]))],
        PRODUCTS[5]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("close_time", pa.int64()), ("indicative_funding_rate", D)],
            [(3_600_000, None)]))],
        PRODUCTS[6]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("close_time", pa.int64()), ("relative_basis", D)],
            [(3_600_000, Decimal("-0.066061392662304580"))]))],
        PRODUCTS[7]: [("", "partition", "BTCUSDT", "2025-09", table(
            [("event_time_ms", pa.int64()), ("source_interval_seconds", pa.int64()),
             ("long_liquidation", D), ("short_liquidation", D)],
            [(0, 86_400, Decimal("1.25"), Decimal("2.50"))]))],
        PRODUCTS[8]: [
            ("retained_book_depth", "partition", "BTCUSDT", "2025-09", table(
                [("timestamp", pa.int64()), ("bid_price", D)],
                [(3_600_000, Decimal("100.1"))])),
            ("retained_book_ticker", "partition", "BTCUSDT", "2025-09", table(
                [("event_time", pa.int64()), ("transaction_time", pa.int64()),
                 ("bid_price", D)], [(3_600_000, 4_000_000, Decimal("100.2"))])),
            ("official_fee_schedule", "reference", None, None, table(
                [("tier", pa.string()), ("maker_fee", D)], [("unknown", None)])),
        ],
        PRODUCTS[9]: [("quality_gap", "reference", "BTCUSDT", "2025-09", gap)],
        PRODUCTS[10]: [("", "harmonic_bundle", None, None, table(
            [("bundle_state", pa.string())], [("complete",)]))],
    }


def release_fixture(root: Path) -> str:
    """Write a small, real eleven-manifest publication under a caller-owned temp root."""
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    identities = {product: f"ds_{index:02d}" for index, product in enumerate(PRODUCTS)}
    for product_index, product in enumerate(PRODUCTS):
        files = []
        contracts: dict[str, list[dict[str, object]]] = {}
        for table_index, (component, role, symbol, month, table) in enumerate(_tables()[product]):
            relative = f"data/fixture/{product_index:02d}-{table_index:02d}.parquet"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, target)
            body = target.read_bytes()
            contract = [{"name": field.name, "arrow_type": str(field.type),
                         "nullable": field.nullable} for field in table.schema]
            schema_ref = _sha(_bytes(contract))
            contracts[schema_ref] = contract
            files.append({"relative_path": relative, "sha256": _sha(body), "bytes": len(body),
                          "rows": table.num_rows,
                          "partition": {"kind": "table", "role": role, "component": component,
                                        "native_symbol": symbol, "utc_month": month,
                                        "schema_ref": schema_ref}})
        meta_relative = f"data/fixture/{product_index:02d}-summary.json"
        meta_body = _bytes({"product": product, "source_available_at": None})
        target = root / meta_relative
        target.write_bytes(meta_body)
        files.append({"relative_path": meta_relative, "sha256": _sha(meta_body),
                      "bytes": len(meta_body), "rows": 0,
                      "partition": {"kind": "metadata", "role": "summary", "component": ""}})
        manifest_sha = f"{product_index + 1:064x}"
        manifest = {"dataset_id": identities[product], "dataset_type": product,
                    "manifest_sha256": manifest_sha, "files": files,
                    "quality_summary": {"schema_registry": {"version": 1, "contracts": contracts}},
                    "dependencies": ([{"role": earlier, "id": identities[earlier]}
                                      for earlier in PRODUCTS[:-1]] if product == PRODUCTS[-1] else [])}
        manifest_body = _bytes(manifest)
        manifest_relative = f"data/fixture/{product_index:02d}-manifest.json"
        (root / manifest_relative).write_bytes(manifest_body)
        entries.append({"dataset_type": product, "dataset_id": identities[product],
                        "manifest_sha256": manifest_sha, "manifest_relative_path": manifest_relative,
                        "manifest_file_sha256": _sha(manifest_body), "manifest_bytes": len(manifest_body)})
    publication = {"document_type": "cex002_harmonic_bundle_publication", "schema_version": 1,
                   "consumable": True, "catalog_commit_required": True,
                   "prepared_sha256": "a" * 64, "proof_sha256": "b" * 64,
                   "checker_source_sha256": "c" * 64, "datasets": entries}
    body = _bytes(publication)
    publication_sha = _sha(body)
    target = root / PUBLICATION_DIR / f"{publication_sha}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(body)
    return publication_sha


@pytest.fixture
def release(tmp_path: Path) -> tuple[Path, str, Cex002ReleaseReader]:
    sha = release_fixture(tmp_path)
    return tmp_path, sha, Cex002ReleaseReader(tmp_path, sha)


def test_complete_inventory_all_families_and_metadata(release) -> None:
    _root, _sha, reader = release
    assert tuple(item["product"] for item in reader.inventory()) == PRODUCTS
    for product in PRODUCTS:
        assert len(list(reader.iter_rows(product))) >= 1
        summary = list(reader.iter_metadata(product))
        assert summary[0][1]["product"] == product
    assert reader.select(PRODUCTS[1], symbol="BTCUSDT", month="2025-09", component="")[0].rows == 2
    assert list(reader.iter_rows(PRODUCTS[1], component="quality_gap"))[0].fields["reason"] == "source_gap"
    assert list(reader.iter_rows(PRODUCTS[9]))[0].file.component == "quality_gap"


def test_half_open_filter_preserves_physical_ordinal_and_units(release) -> None:
    _root, _sha, reader = release
    bar = list(reader.iter_rows(PRODUCTS[1], component="", start_ms=7_200_000,
                                    end_ms=7_200_001, batch_rows=1))
    assert len(bar) == 1 and bar[0].ordinal == 1
    assert bar[0].fields["high"] == Decimal("102.125000000000000000")
    assert list(reader.iter_rows(PRODUCTS[1], component="", end_ms=7_200_000,
                                 batch_rows=1))[0].ordinal == 0
    indicative = next(reader.iter_rows(PRODUCTS[5]))
    assert indicative.fields["indicative_funding_rate"] is None
    assert next(reader.iter_rows(PRODUCTS[3])).fields["sum_open_interest_value"] == Decimal("300")
    assert next(reader.iter_rows(PRODUCTS[6])).fields["relative_basis"] == Decimal("-0.066061392662304580")
    liquidation = next(reader.iter_rows(PRODUCTS[7]))
    assert liquidation.fields["long_liquidation"] == Decimal("1.25")
    assert reader.event_time_ms(liquidation.file.product, liquidation.file.component,
                                liquidation.fields) == 86_400_000
    with pytest.raises(Cex002ReaderError, match="unsupported"):
        list(reader.iter_rows(PRODUCTS[1], component="quality_gap", start_ms=1))
    with pytest.raises(Cex002ReaderError, match="unsupported"):
        list(reader.iter_rows(PRODUCTS[0], start_ms=1))


def test_missing_corrupt_and_replaced_selected_files_fail(release) -> None:
    root, sha, reader = release
    file = reader.select(PRODUCTS[1], component="")[0]
    selected = root / file.relative_path
    original = selected.read_bytes()
    selected.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(Cex002ReaderError, match="published manifest"):
        list(reader.iter_rows(PRODUCTS[1], component=""))
    selected.write_bytes(original)
    reader = Cex002ReleaseReader(root, sha)
    assert len(list(reader.iter_rows(PRODUCTS[1], component=""))) == 2
    selected.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(Cex002ReaderError, match="previously verified"):
        list(reader.iter_rows(PRODUCTS[1], component=""))
    selected.unlink()
    with pytest.raises(FileNotFoundError):
        list(reader.iter_rows(PRODUCTS[1], component=""))


def test_publication_pin_and_selection_fail_closed(release) -> None:
    root, sha, reader = release
    with pytest.raises(FileNotFoundError):
        Cex002ReleaseReader(root, "0" * 64)
    with pytest.raises(Cex002ReaderError, match="no declared files"):
        reader.select(PRODUCTS[1], symbol="UNLISTED")
    with pytest.raises(Cex002ReaderError, match="not in"):
        reader.select("unpublished_product")
    with pytest.raises(Cex002ReaderError, match="time filters"):
        list(reader.iter_rows(PRODUCTS[1], start_ms=2, end_ms=2))


def _repin_publication(root: Path, publication: dict) -> str:
    body = _bytes(publication)
    sha = _sha(body)
    (root / PUBLICATION_DIR / f"{sha}.json").write_bytes(body)
    return sha


def test_publication_and_manifest_authorities_fail_closed(release) -> None:
    root, sha, _reader = release
    publication_file = root / PUBLICATION_DIR / f"{sha}.json"
    original = publication_file.read_bytes()
    publication_file.write_bytes(original + b" ")
    with pytest.raises(Cex002ReaderError, match="pin mismatch"):
        Cex002ReleaseReader(root, sha)
    publication_file.write_bytes(original)
    publication = json.loads(original)
    bad_membership = dict(publication)
    bad_membership["datasets"] = publication["datasets"][:-1]
    with pytest.raises(Cex002ReaderError, match="eleven"):
        Cex002ReleaseReader(root, _repin_publication(root, bad_membership))
    not_consumable = dict(publication)
    not_consumable["consumable"] = False
    with pytest.raises(Cex002ReaderError, match="not an admitted"):
        Cex002ReleaseReader(root, _repin_publication(root, not_consumable))
    manifest_path = root / publication["datasets"][0]["manifest_relative_path"]
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    with pytest.raises(Cex002ReaderError, match="pin mismatch"):
        Cex002ReleaseReader(root, sha)


def test_pinned_parquet_schema_mismatch_is_refused(release) -> None:
    root, sha, _reader = release
    publication = json.loads((root / PUBLICATION_DIR / f"{sha}.json").read_bytes())
    entry = publication["datasets"][1]
    manifest_file = root / entry["manifest_relative_path"]
    manifest = json.loads(manifest_file.read_bytes())
    file = manifest["files"][0]
    table_file = root / file["relative_path"]
    original = pq.read_table(table_file)
    altered = original.rename_columns(["wrong_symbol", *original.schema.names[1:]])
    pq.write_table(altered, table_file)
    body = table_file.read_bytes()
    file["sha256"] = _sha(body)
    file["bytes"] = len(body)
    manifest_body = _bytes(manifest)
    manifest_file.write_bytes(manifest_body)
    entry["manifest_file_sha256"] = _sha(manifest_body)
    entry["manifest_bytes"] = len(manifest_body)
    revised_sha = _repin_publication(root, publication)
    reader = Cex002ReleaseReader(root, revised_sha)
    with pytest.raises(Cex002ReaderError, match="schema differs"):
        list(reader.iter_rows(PRODUCTS[1], component=""))
