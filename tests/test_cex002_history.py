"""Dated contract interval and real Nautilus identity checks for HT-005."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
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
             *, known: datetime = KNOWN, schema: int = 1,
             unresolved: list[dict] | None = None) -> ContractHistory:
    document = {"document_type": "cex002_contract_history", "schema_version": schema,
                "publication_sha256": publication_sha, "facts_sha256": "b" * 64,
                "known_from": known.isoformat(), "history_complete": False,
                "episodes": episodes, "unresolved_symbols": unresolved if unresolved is not None else [
                    {"native_symbol": "UNSEENUSDT", "reasons": ["no_recovered_launch"]}]}
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    target = root / "history.json"
    target.write_bytes(body)
    return ContractHistory(target, sha256=hashlib.sha256(body).hexdigest(),
                           publication_sha256=publication_sha)


def _confirmed(symbol: str, start: int, end: int | None = None,
               stop: int | None = None, mark: str = "a") -> dict:
    episode = _episode(symbol, start, end, stop, mark)
    episode.update(launch_ms=None, coverage_start_ms=start, start_kind="confirmed_active",
                   launch_terms={})
    episode["events"][0]["event"] = "confirmed_active"
    return episode


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


def test_confirmed_boundaries_knowledge_restrictions_closure_and_evidence(release) -> None:
    root, sha, _reader = release
    episode = _confirmed("BTCUSDT", 100, 500, 400)
    history = _history(root, sha, [episode], schema=2)
    classify = history.classify
    before = classify("BTCUSDT", 0, 100, KNOWN)
    assert before.status == "before_confirmed_active"
    assert before.instrument_id is None
    assert before.evidence == tuple(episode["events"])
    assert before.evidence[0]["effective_ms"] == 100
    assert classify("BTCUSDT", 99, 101, KNOWN).status == "crosses_boundary"
    assert classify("BTCUSDT", 100, 400, KNOWN).status == "within_known_episode"
    assert classify("BTCUSDT", 399, 401, KNOWN).status == "crosses_boundary"
    assert classify("BTCUSDT", 400, 500, KNOWN).status == "new_positions_restricted"
    assert classify("BTCUSDT", 499, 501, KNOWN).status == "crosses_boundary"
    assert classify("BTCUSDT", 500, 501, KNOWN).status == "at_or_after_execution_end"
    unknown = classify("BTCUSDT", 100, 101, datetime(2026, 10, 26, tzinfo=timezone.utc))
    assert unknown.status == "unknown_at_knowledge_time" and unknown.evidence == ()
    assert unknown.instrument_id is None
    assert before.history_complete is before.payment_eligibility_established is False


def test_confirmed_later_bar_reaches_callbacks_earlier_and_crossing_bars_refuse(release) -> None:
    root, sha, reader = release
    first, crossing = list(reader.iter_rows(PRODUCTS[1], component=""))
    history = _history(root, sha, [_confirmed("BTCUSDT", 3_600_001)], schema=2)
    later = replace(crossing, fields={**crossing.fields, "open_time": 7_200_000,
                                     "close_time": 10_800_000})
    kwargs = {"clock_policy": CLOCK_POLICY, "history": history, "knowledge_time": KNOWN,
              "reference_policy": REFERENCE_POLICY, "publication_sha256": sha}
    receipt = deliver_to_nautilus([later], **kwargs)
    assert receipt["custom_count"] == receipt["bar_count"] == 1
    assert receipt["custom_receipts"][0]["fields"] == later.fields
    assert receipt["bar_receipts"][0]["bar_type"].startswith("ins_" + "a" * 64 + ".BINANCE")
    lineage = receipt["custom_receipts"][0]["lineage"]["reference_classification"]
    assert lineage["status"] == "within_known_episode"
    assert lineage["evidence"][0]["event"] == "confirmed_active"
    for row, reason in ((first, "before_confirmed_active"), (crossing, "crosses_boundary")):
        with pytest.raises(Cex002ReaderError, match=reason):
            native_bar(row, **kwargs)
        with pytest.raises(Cex002ReaderError, match=reason):
            deliver_to_nautilus([row], **kwargs)
    funding = next(reader.iter_rows(PRODUCTS[4]))
    funded = deliver_to_nautilus([funding], **kwargs)
    assert funded["custom_receipts"][0]["fields"] == funding.fields
    assert funded["custom_receipts"][0]["lineage"]["reference_classification"][
        "payment_eligibility_established"] is False


def test_schema2_exact_launch_compatibility_mixed_sorting_and_pending_gaib(release) -> None:
    root, sha, _reader = release
    exact = _episode("BTCUSDT", 0, 100, None, "b")
    confirmed = _confirmed("BTCUSDT", 200, mark="c")
    legacy = _history(root, sha, [exact])
    unresolved = [{"native_symbol": "GAIBUSDT", "reasons": ["launch_postponed_indefinitely"],
                   "events": [{"event": "launch", "event_status": "postponed",
                               "executable_boundary": False,
                               "source_url": "https://example.test/gaib"}]}]
    mixed = _history(root, sha, [confirmed, exact], schema=2, unresolved=unresolved)
    assert mixed.document["episodes"][1] == legacy.document["episodes"][0]
    assert mixed.classify("BTCUSDT", 0, 1, KNOWN) == legacy.classify("BTCUSDT", 0, 1, KNOWN)
    assert mixed.classify("BTCUSDT", 100, 200, KNOWN).status == "between_episodes"
    assert mixed.classify("BTCUSDT", 199, 201, KNOWN).status == "crosses_boundary"
    assert mixed.classify("BTCUSDT", 200, 201, KNOWN).instrument_id == confirmed["instrument_id"]
    assert mixed.classify("GAIBUSDT", 0, 1, KNOWN).status == "unknown_symbol"
    assert mixed.unresolved_symbols == tuple(unresolved)
    assert _history(root, sha, [_episode("ETHUSDT", 100, None, None, "d")], schema=2).classify(
        "ETHUSDT", 0, 100, KNOWN).status == "before_known_launch"


@pytest.mark.parametrize("schema,change", [
    (1, {}), (2, {"start_kind": "launch"}), (2, {"start_kind": None}),
    (2, {"coverage_start_ms": None}), (2, {"coverage_start_ms": True}),
    (2, {"coverage_start_ms": -1}), (2, {"coverage_start_ms": 101}),
    (2, {"launch_terms": {"tick_size": "0.01"}}),
    (2, {"source_urls": []}), (2, {"events": []}), (2, {"events": [None]}),
    (2, {"events": [{"event": "confirmed_active", "effective_ms": 100, "source_urls": []}]}),
    (2, {"events": [{"event": "confirmed_active", "effective_ms": 100,
                     "source_urls": ["https://example.test/other"]}]}),
    (2, {"events": [{"event": "confirmed_active", "effective_ms": 100,
                     "native_symbol": "ETHUSDT", "source_urls": ["https://example.test/a"]}]}),
    (2, {"events": [{"event": "launch", "effective_ms": 100,
                     "source_urls": ["https://example.test/a"]}]}),
    (2, {"execution_end_ms": 100}), (2, {"new_positions_stop_ms": 100}),
])
def test_reader_rejects_malformed_or_unsupported_confirmed_episode(release, schema, change) -> None:
    root, sha, _reader = release
    episode = _confirmed("BTCUSDT", 100)
    episode.update(change)
    with pytest.raises(Cex002ReaderError):
        _history(root, sha, [episode], schema=schema)


@pytest.mark.parametrize("change", [
    {"coverage_start_ms": 101}, {"coverage_start_ms": True}, {"coverage_start_ms": None},
    {"start_kind": "confirmed_active"}, {"start_kind": "unknown"},
])
def test_exact_launch_cannot_claim_conflicting_coverage(release, change) -> None:
    root, sha, _reader = release
    episode = _episode("BTCUSDT", 100, None, None, "a")
    episode.update(change)
    with pytest.raises(Cex002ReaderError, match="conflicting coverage"):
        _history(root, sha, [episode], schema=2)


@pytest.mark.parametrize("confirmed_first", [True, False])
def test_reader_rejects_overlapping_confirmation_and_exact_launch(release, confirmed_first) -> None:
    root, sha, _reader = release
    confirmed = _confirmed("BTCUSDT", 100 if confirmed_first else 200)
    exact = _episode("BTCUSDT", 200 if confirmed_first else 100, None, None, "b")
    with pytest.raises(Cex002ReaderError, match="overlapping"):
        _history(root, sha, [exact, confirmed], schema=2)
