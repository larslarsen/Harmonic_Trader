"""Real rc3 object and callback checks for the published CEX-002 transport."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext

import pytest
from nautilus_trader.model import Bar, CustomData
from nautilus_trader.persistence import ParquetDataCatalog

from harmonic_trader.cex002 import main
from harmonic_trader.data.cex002 import Cex002ReaderError, PRODUCTS
from harmonic_trader.integration.cex002_data import (
    Cex002NativeFields, CLOCK_POLICY, custom_event, deliver_to_nautilus,
    native_bar, native_bar_precision, register_cex002_native_fields,
)
import test_cex002_reader as fixture_source


@pytest.fixture
def release(tmp_path):
    sha = fixture_source.release_fixture(tmp_path)
    return tmp_path, sha, fixture_source.Cex002ReleaseReader(tmp_path, sha)


def test_registered_custom_roundtrip_retains_native_fields_and_unknown_availability(release) -> None:
    _root, _sha, reader = release
    register_cex002_native_fields()
    rows = [next(reader.iter_rows(product, component="")) for product in PRODUCTS[1:8]]
    rows.extend([next(reader.iter_rows(PRODUCTS[8], component="retained_book_depth")),
                 next(reader.iter_rows(PRODUCTS[8], component="retained_book_ticker"))])
    for row in rows:
        wrapper = custom_event(row, clock_policy=CLOCK_POLICY)
        assert isinstance(wrapper, CustomData)
        assert wrapper.data.native_fields == row.fields
        assert wrapper.data.lineage["source_available_at"] is None
        assert wrapper.data.lineage["ordinal"] == row.ordinal
        restored = Cex002NativeFields.from_json(wrapper.data.to_json())
        assert restored.native_fields == row.fields
        batch = wrapper.data.encode_record_batch_py([wrapper.data])
        decoded = Cex002NativeFields.decode_record_batch_py(
            dict(wrapper.data_type.metadata), batch)[0]
        assert decoded.native_fields == row.fields
        assert decoded.ts_event == wrapper.ts_event
    liquidation = custom_event(rows[6], clock_policy=CLOCK_POLICY)
    assert liquidation.ts_event == 86_400_000 * 1_000_000
    assert rows[6].fields["long_liquidation"] == Decimal("1.25")
    with pytest.raises(Cex002ReaderError, match="clock_policy"):
        custom_event(rows[0], clock_policy="source_available_at")
    with pytest.raises(Cex002ReaderError, match="no supported"):
        custom_event(next(reader.iter_rows(PRODUCTS[0])), clock_policy=CLOCK_POLICY)


def test_registered_custom_catalog_roundtrip_uses_native_decoder(release, tmp_path) -> None:
    _root, _sha, reader = release
    row = next(reader.iter_rows(PRODUCTS[5]))
    wrapper = custom_event(row, clock_policy=CLOCK_POLICY)
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    catalog = ParquetDataCatalog(str(catalog_root))
    catalog.write_custom_data((wrapper,))
    restored = catalog.query_custom_data(
        Cex002NativeFields.type_name_static(), identifiers=[wrapper.data_type.identifier])
    assert len(restored) == 1
    assert restored[0].data.native_fields == row.fields
    assert restored[0].data.lineage == wrapper.data.lineage


def test_native_bars_keep_exact_common_precision_even_under_low_decimal_context(release) -> None:
    _root, _sha, reader = release
    rows = list(reader.iter_rows(PRODUCTS[1], component=""))
    with localcontext() as context:
        context.prec = 4
        price_precision, size_precision = native_bar_precision(rows)
        bars = [native_bar(row, clock_policy=CLOCK_POLICY,
                           price_precision=price_precision, size_precision=size_precision)
                for row in rows]
    assert all(isinstance(bar, Bar) for bar in bars)
    assert price_precision == 3 and size_precision == 1
    assert [bar.high.as_decimal() for bar in bars] == [Decimal("101.25"), Decimal("102.125")]
    assert [bar.volume.as_decimal() for bar in bars] == [Decimal("1"), Decimal("2.5")]
    assert all(str(bar.bar_type.instrument_id) == "BTCUSDT.BINANCE" for bar in bars)
    with pytest.raises(Cex002ReaderError, match="only primary"):
        native_bar(next(reader.iter_rows(PRODUCTS[1], component="quality_gap")),
                   clock_policy=CLOCK_POLICY)


def test_actual_nautilus_callbacks_receive_custom_and_native_bar(release) -> None:
    _root, _sha, reader = release
    rows = list(reader.iter_rows(PRODUCTS[1], component=""))
    receipt = deliver_to_nautilus(rows, clock_policy=CLOCK_POLICY)
    assert receipt["custom_count"] == len(rows)
    assert receipt["bar_count"] == len(rows)
    assert [item["fields"] for item in receipt["custom_receipts"]] == [row.fields for row in rows]
    assert [item["close"] for item in receipt["bar_receipts"]] == [
        Decimal("100.5"), Decimal("101.75")]
    assert all(item["callback_ns"] == item["ts_event"] for item in receipt["custom_receipts"])
    assert all(item["callback_ns"] == item["ts_event"] for item in receipt["bar_receipts"])
    oi = [next(reader.iter_rows(PRODUCTS[3]))]
    receipt = deliver_to_nautilus(oi, clock_policy=CLOCK_POLICY)
    assert receipt["custom_count"] == 1 and receipt["bar_count"] == 0
    assert receipt["custom_receipts"][0]["fields"]["sum_open_interest_value"] == Decimal("300")


def test_cli_inventory_rows_and_actual_delivery(release, capsys) -> None:
    root, sha, _reader = release
    prefix = ["--root", str(root), "--publication-sha", sha]
    assert main([*prefix, "inventory"]) == 0
    inventory = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(inventory) == 11 and inventory[-1]["product"] == PRODUCTS[-1]
    assert main([*prefix, "rows", "--product", PRODUCTS[5], "--limit", "1"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["fields"]["indicative_funding_rate"] is None
    assert shown["source_available_at"] is None
    assert main([*prefix, "nautilus", "--product", PRODUCTS[1], "--component", "",
                 "--symbol", "BTCUSDT", "--limit", "2",
                 "--clock-policy", CLOCK_POLICY]) == 0
    delivered = json.loads(capsys.readouterr().out)
    assert delivered["custom_count"] == 2 and delivered["bar_count"] == 2
    assert delivered["source_available_at"] is None
