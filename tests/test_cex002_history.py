"""Dated contract interval and real Nautilus identity checks for HT-005."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harmonic_trader.cex002 import main
from harmonic_trader.data.cex002 import Cex002ReaderError, Cex002ReleaseReader, PRODUCTS
from harmonic_trader.data.cex002_history import (
    ContractHistory, REFERENCE_POLICY, annotate_row, iter_history_rows, row_interval,
)
from harmonic_trader.integration.cex002_data import (
    CLOCK_POLICY, deliver_to_nautilus, native_bar,
)
import test_cex002_reader as fixture_source


KNOWN = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


@pytest.fixture
def release(tmp_path: Path):
    sha = fixture_source.release_fixture(tmp_path)
    return tmp_path, sha, Cex002ReleaseReader(tmp_path, sha)


def _episode(symbol: str, launch: int, end: int | None, stop: int | None, mark: str) -> dict:
    return {"native_symbol": symbol, "asset_id": "ast_" + mark * 64,
            "instrument_id": "ins_" + mark * 64,
            "instrument_version_id": "iv_" + mark * 64,
            "launch_ms": launch, "execution_end_ms": end,
            "new_positions_stop_ms": stop,
            "source_urls": [f"https://example.test/{mark}"],
            "launch_terms": {"settlement_asset": "USDT"},
            "historical_terms_complete": False, "history_complete": False,
            "events": [{"event": "launch", "effective_ms": launch,
                        "source_urls": [f"https://example.test/{mark}"]}],
            "pre_market_events": [], "related_events": []}


def _history(root: Path, publication_sha: str, episodes: list[dict],
             *, known: datetime = KNOWN) -> ContractHistory:
    document = {"document_type": "cex002_contract_history", "schema_version": 1,
                "publication_sha256": publication_sha, "facts_sha256": "b" * 64,
                "known_from": known.isoformat(), "history_complete": False,
                "episodes": episodes, "unresolved_symbols": [{"native_symbol": "UNSEENUSDT",
                                                               "reasons": ["no_recovered_launch"]}]}
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    target = root / "history.json"
    target.write_bytes(body)
    return ContractHistory(target, sha256=hashlib.sha256(body).hexdigest(),
                           publication_sha256=publication_sha)


def test_history_classifies_whole_interval_restrictions_and_relaunch(release) -> None:
    root, sha, reader = release
    history = _history(root, sha, [
        _episode("BTCUSDT", 0, 7_200_000, 5_400_000, "a"),
        _episode("BTCUSDT", 10_000_000, None, None, "c"),
    ])
    classify = history.classify
    assert classify("BTCUSDT", 0, 3_600_001, KNOWN).status == "within_known_episode"
    assert classify("BTCUSDT", 5_400_000, 5_400_001, KNOWN).status == "new_positions_restricted"
    assert classify("BTCUSDT", 5_399_999, 5_400_001, KNOWN).status == "crosses_boundary"
    assert classify("BTCUSDT", 7_200_000, 7_200_001, KNOWN).status == "between_episodes"
    assert classify("BTCUSDT", 7_200_000, 7_200_001, KNOWN).instrument_id == "ins_" + "a" * 64
    assert classify("BTCUSDT", 7_200_000, 7_200_001, KNOWN).evidence
    assert classify("BTCUSDT", 9_999_999, 10_000_001, KNOWN).status == "crosses_boundary"
    assert classify("BTCUSDT", 10_000_000, 10_000_001, KNOWN).instrument_id == "ins_" + "c" * 64
    assert classify("BTCUSDT", 0, 1, datetime(2026, 10, 27, 11, tzinfo=timezone.utc)).status == "unknown_at_knowledge_time"
    assert classify("BTCUSDT", 11_000_000, 11_000_001, KNOWN).history_complete is False
    assert classify("UNSEENUSDT", 0, 1, KNOWN).status == "unknown_symbol"
    bar_rows = list(reader.iter_rows(PRODUCTS[1], component=""))
    first = annotate_row(bar_rows[0], history, KNOWN)
    second = annotate_row(bar_rows[1], history, KNOWN)
    assert first.classification.status == "within_known_episode"
    assert second.classification.status == "crosses_boundary"
    assert first.row.fields is bar_rows[0].fields
    assert list(iter_history_rows(reader, history, KNOWN, PRODUCTS[1], component=""))[0] == first
    assert row_interval(bar_rows[0]) == ("BTCUSDT", 0, 3_600_001)
    assert annotate_row(next(reader.iter_rows(PRODUCTS[1], component="quality_gap")),
                        history, KNOWN).classification is None


def test_native_bar_uses_episode_identity_and_refuses_crossing_before_engine(release) -> None:
    root, sha, reader = release
    history = _history(root, sha, [_episode("BTCUSDT", 0, 7_200_000, 5_400_000, "a")])
    first, second = list(reader.iter_rows(PRODUCTS[1], component=""))
    kwargs = {"clock_policy": CLOCK_POLICY, "history": history, "knowledge_time": KNOWN,
              "reference_policy": REFERENCE_POLICY, "publication_sha256": sha}
    native = native_bar(first, **kwargs)
    assert str(native.bar_type.instrument_id) == "ins_" + "a" * 64 + ".BINANCE"
    assert first.fields["venue_symbol"] == "BTCUSDT"
    receipt = deliver_to_nautilus([first], **kwargs)
    assert receipt["custom_count"] == receipt["bar_count"] == 1
    assert receipt["bar_receipts"][0]["bar_type"] == str(native.bar_type)
    assert receipt["custom_receipts"][0]["fields"] == first.fields
    assert receipt["qualification"] == REFERENCE_POLICY and receipt["history_sha256"] == history.sha256
    with pytest.raises(Cex002ReaderError, match="crosses_boundary"):
        native_bar(second, **kwargs)
    with pytest.raises(Cex002ReaderError, match="crosses_boundary"):
        deliver_to_nautilus([first, second], **kwargs)
    with pytest.raises(Cex002ReaderError, match="matching publication"):
        native_bar(first, **{**kwargs, "publication_sha256": "0" * 64})
    with pytest.raises(Cex002ReaderError, match="reviewed notices"):
        native_bar(first, **{**kwargs, "reference_policy": None})


def test_funding_after_end_is_preserved_without_payment_claim(release) -> None:
    root, sha, reader = release
    history = _history(root, sha, [_episode("BTCUSDT", 0, 3_599_995, None, "a")])
    funding = next(reader.iter_rows(PRODUCTS[4]))
    annotation = annotate_row(funding, history, KNOWN)
    assert annotation.classification.status == "at_or_after_execution_end"
    assert annotation.classification.instrument_id == "ins_" + "a" * 64
    assert annotation.classification.evidence
    assert annotation.classification.payment_eligibility_established is False
    assert annotation.row.fields["last_funding_rate"] == funding.fields["last_funding_rate"]
    receipt = deliver_to_nautilus([funding], clock_policy=CLOCK_POLICY, history=history,
        knowledge_time=KNOWN, reference_policy=REFERENCE_POLICY, publication_sha256=sha)
    assert receipt["custom_count"] == 1 and receipt["bar_count"] == 0
    assert receipt["custom_receipts"][0]["fields"] == funding.fields
    lineage = receipt["custom_receipts"][0]["lineage"]
    assert lineage["history_sha256"] == history.sha256
    assert lineage["reference_classification"]["status"] == "at_or_after_execution_end"
    assert lineage["reference_classification"]["payment_eligibility_established"] is False
    with pytest.raises(Cex002ReaderError, match="timezone-aware"):
        deliver_to_nautilus([funding], clock_policy=CLOCK_POLICY, history=history,
            knowledge_time=datetime(2026, 10, 27), reference_policy=REFERENCE_POLICY,
            publication_sha256=sha)


def test_companion_pin_publication_overlap_and_knowledge_validation(release) -> None:
    root, sha, _reader = release
    episodes = [_episode("BTCUSDT", 0, 7_200_000, None, "a")]
    history = _history(root, sha, episodes)
    path = root / "history.json"
    with pytest.raises(Cex002ReaderError, match="digest differs"):
        ContractHistory(path, sha256="0" * 64, publication_sha256=sha)
    with pytest.raises(Cex002ReaderError, match="publication binding"):
        ContractHistory(path, sha256=history.sha256, publication_sha256="0" * 64)
    alias = root / "history-link.json"
    alias.symlink_to(path)
    with pytest.raises(Cex002ReaderError, match="non-symlink"):
        ContractHistory(alias, sha256=history.sha256, publication_sha256=sha)
    with pytest.raises(Cex002ReaderError, match="timezone-aware"):
        history.classify("BTCUSDT", 0, 1, datetime(2026, 10, 27))
    with pytest.raises(Cex002ReaderError, match="overlapping"):
        _history(root, sha, [*episodes, _episode("BTCUSDT", 3_600_000, None, None, "c")])
    with pytest.raises(Cex002ReaderError, match="duplicated"):
        _history(root, sha, [*episodes, _episode("ETHUSDT", 0, None, None, "a")])


def test_cli_complete_options_rows_annotation_and_qualified_native_delivery(release, capsys) -> None:
    root, sha, _reader = release
    history = _history(root, sha, [_episode("BTCUSDT", 0, None, None, "a")])
    prefix = ["--root", str(root), "--publication-sha", sha]
    options = ["--history", str(root / "history.json"), "--history-sha", history.sha256,
               "--knowledge-time", KNOWN.isoformat()]
    with pytest.raises(Cex002ReaderError, match="supplied together"):
        main([*prefix, "rows", "--product", PRODUCTS[1], "--history", str(root / "history.json")])
    assert main([*prefix, "rows", "--product", PRODUCTS[1], "--component", "",
                 "--limit", "1", *options]) == 0
    displayed = json.loads(capsys.readouterr().out)
    assert displayed["reference_classification"]["status"] == "within_known_episode"
    assert displayed["fields"]["venue_symbol"] == "BTCUSDT"
    assert main([*prefix, "nautilus", "--product", PRODUCTS[1], "--limit", "1",
                 "--clock-policy", CLOCK_POLICY, "--reference-policy", REFERENCE_POLICY,
                 *options]) == 0
    delivered = json.loads(capsys.readouterr().out)
    assert delivered["bar_count"] == 1
    assert delivered["qualification"] == REFERENCE_POLICY
    assert delivered["history_sha256"] == history.sha256
