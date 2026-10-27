"""Pinned retrospective CEX-002 contract episodes and row annotations.

Classification describes recovered notice schedules, not observed tradability,
historic notice receipt, funding-payment entitlement, or causal data availability.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from harmonic_trader.data.cex002 import Cex002ReaderError, Cex002ReleaseReader, ReleasedRow

MAX_HISTORY_BYTES = 4 * 1024 * 1024
REFERENCE_POLICY = "reviewed_notices_assumption"
_PERIOD_PRODUCTS = frozenset({
    "binance_usdm_bar_1h", "binance_usdm_trade_flow_1h",
    "binance_usdm_funding_indicative_1h", "binance_usdm_mark_index_basis_1h",
})
_POINT_FIELDS = {
    "binance_usdm_open_interest_5m": "create_time",
    "binance_usdm_funding_realized": "calc_time",
    "binance_usdm_cost_calibration": None,
}


def _need(ok: bool, message: str) -> None:
    if not ok:
        raise Cex002ReaderError(message)


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _need(isinstance(value, datetime) and value.tzinfo is not None,
          "knowledge_time must be timezone-aware UTC")
    _need(value.utcoffset().total_seconds() == 0,
          "knowledge_time must be UTC")
    return value.astimezone(timezone.utc)


def _int_ms(value: object, field: str) -> int:
    _need(type(value) is int and value >= 0, f"{field} must be a nonnegative millisecond integer")
    return value


def _coverage_start(episode: Mapping[str, Any]) -> int:
    return (episode["coverage_start_ms"] if episode["launch_ms"] is None
            else episode["launch_ms"])


@dataclass(frozen=True, slots=True)
class HistoryClassification:
    status: str
    native_symbol: str | None
    start_ms: int | None
    end_ms: int | None
    instrument_id: str | None
    asset_id: str | None
    instrument_version_id: str | None
    evidence: tuple[Mapping[str, Any], ...]
    history_complete: bool = False
    payment_eligibility_established: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "native_symbol": self.native_symbol,
                "start_ms": self.start_ms, "end_ms": self.end_ms,
                "instrument_id": self.instrument_id, "asset_id": self.asset_id,
                "instrument_version_id": self.instrument_version_id,
                "evidence": list(self.evidence), "history_complete": False,
                "payment_eligibility_established": False}


@dataclass(frozen=True, slots=True)
class AnnotatedRow:
    row: ReleasedRow
    classification: HistoryClassification | None
    interval_reason: str | None = None


class ContractHistory:
    """Read one caller-pinned, publication-bound, incomplete reference companion."""

    def __init__(self, path: Path | str, *, sha256: str, publication_sha256: str) -> None:
        _need(_hex64(sha256) and _hex64(publication_sha256), "contract history pin is malformed")
        path = Path(path)
        initial = path.lstat()
        _need(stat.S_ISREG(initial.st_mode) and not stat.S_ISLNK(initial.st_mode)
              and 0 < initial.st_size <= MAX_HISTORY_BYTES,
              "contract history must be a bounded regular non-symlink file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            first = os.fstat(descriptor)
            body = os.read(descriptor, MAX_HISTORY_BYTES + 1)
            last = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        def signature(facts: os.stat_result) -> tuple[int, int, int, int, int]:
            return (facts.st_dev, facts.st_ino, facts.st_size,
                    facts.st_mtime_ns, facts.st_ctime_ns)
        _need(len(body) == first.st_size and len(body) <= MAX_HISTORY_BYTES
              and signature(initial) == signature(first) == signature(last) == signature(path.lstat())
              and hashlib.sha256(body).hexdigest() == sha256,
              "contract history bytes changed or digest differs")
        try:
            document = json.loads(body)
        except ValueError as exc:
            raise Cex002ReaderError("contract history is not JSON") from exc
        _need(type(document) is dict and document.get("document_type") == "cex002_contract_history"
              and type(document.get("schema_version")) is int and document["schema_version"] in {1, 2}
              and document.get("publication_sha256") == publication_sha256
              and _hex64(document.get("facts_sha256"))
              and document.get("history_complete") is False,
              "contract history protocol or publication binding differs")
        self.sha256 = sha256
        self.publication_sha256 = publication_sha256
        self.known_from = _utc(document.get("known_from"))
        self.document = document
        episodes = document.get("episodes")
        unresolved = document.get("unresolved_symbols")
        _need(type(episodes) is list and type(unresolved) is list,
              "contract history episode or unresolved list is malformed")
        self._episodes: dict[str, tuple[dict[str, Any], ...]] = {}
        ids: set[str] = set()
        versions: set[str] = set()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for episode in episodes:
            _need(type(episode) is dict, "contract episode is malformed")
            symbol = episode.get("native_symbol")
            if episode.get("launch_ms") is None:
                _need(document["schema_version"] == 2 and "launch_ms" in episode
                      and episode.get("start_kind") == "confirmed_active",
                      "null episode launch requires schema 2 confirmed_active")
                launch = _int_ms(episode.get("coverage_start_ms"), "episode coverage start")
                _need(episode.get("launch_terms") == {}
                      and type(episode.get("events")) is list
                      and type(episode.get("source_urls")) is list
                      and bool(episode["source_urls"])
                      and all(type(url) is str and bool(url) for url in episode["source_urls"])
                      and all(type(event) is dict for event in episode["events"]),
                      "confirmed-active episode terms or evidence is malformed")
                confirmations = [event for event in episode["events"]
                                 if event.get("event") == "confirmed_active"]
                _need(bool(confirmations) and all(
                    type(event.get("effective_ms")) is int and event["effective_ms"] == launch
                    and event.get("native_symbol", symbol) == symbol
                    and type(event.get("source_urls")) is list and bool(event["source_urls"])
                    and all(type(url) is str and bool(url) and url in episode["source_urls"]
                            for url in event["source_urls"])
                    for event in confirmations)
                    and not any(event.get("event") in {"launch", "replacement_launch"}
                                for event in episode["events"]),
                    "confirmed-active source evidence or coverage start differs")
            else:
                launch = _int_ms(episode["launch_ms"], "episode launch")
                _need(("coverage_start_ms" not in episode
                       or type(episode["coverage_start_ms"]) is int
                       and episode["coverage_start_ms"] == launch)
                      and ("start_kind" not in episode or episode["start_kind"] == "launch"),
                      "exact-launch episode has conflicting coverage fields")
            end = episode.get("execution_end_ms")
            restriction = episode.get("new_positions_stop_ms")
            if end is not None:
                _need(_int_ms(end, "execution end") > launch, "execution end precedes launch")
            if restriction is not None:
                _need(_int_ms(restriction, "new-position stop") > launch
                      and (end is None or restriction <= end),
                      "new-position restriction is outside episode")
            instrument_id = episode.get("instrument_id")
            version_id = episode.get("instrument_version_id")
            _need(type(symbol) is str and bool(symbol)
                  and type(instrument_id) is str and instrument_id.startswith("ins_")
                  and _hex64(instrument_id[4:])
                  and type(episode.get("asset_id")) is str and episode["asset_id"].startswith("ast_")
                  and _hex64(episode["asset_id"][4:])
                  and type(version_id) is str and version_id.startswith("iv_")
                  and _hex64(version_id[3:])
                  and instrument_id not in ids and version_id not in versions
                  and episode.get("historical_terms_complete") is False
                  and episode.get("history_complete") is False
                  and type(episode.get("source_urls")) is list
                  and type(episode.get("launch_terms")) is dict
                  and type(episode.get("events")) is list
                  and type(episode.get("pre_market_events")) is list,
                  "contract episode identity or evidence is malformed/duplicated")
            ids.add(instrument_id)
            versions.add(version_id)
            grouped.setdefault(symbol, []).append(episode)
        for symbol, group in grouped.items():
            group.sort(key=_coverage_start)
            for earlier, later in zip(group, group[1:]):
                _need(earlier["execution_end_ms"] is not None
                      and earlier["execution_end_ms"] <= _coverage_start(later),
                      f"overlapping contract episodes for {symbol}")
            self._episodes[symbol] = tuple(group)
        unresolved_seen: set[str] = set()
        for item in unresolved:
            _need(type(item) is dict and type(item.get("native_symbol")) is str
                  and bool(item["native_symbol"]) and item["native_symbol"] not in unresolved_seen
                  and type(item.get("reasons")) is list and bool(item["reasons"])
                  and all(type(reason) is str and reason for reason in item["reasons"])
                  and type(item.get("events", [])) is list,
                  "contract unresolved-symbol evidence is malformed")
            unresolved_seen.add(item["native_symbol"])
        self.unresolved_symbols = tuple(unresolved)

    def classify(self, symbol: str, start_ms: int, end_ms: int,
                 knowledge_time: datetime | str) -> HistoryClassification:
        start = _int_ms(start_ms, "interval start")
        end = _int_ms(end_ms, "interval end")
        _need(end > start, "observation interval must be nonempty [start,end)")
        _need(type(symbol) is str and bool(symbol), "native symbol is required")
        episode: dict[str, Any] | None = None
        evidence_episode: dict[str, Any] | None = None
        group = self._episodes.get(symbol, ())
        if _utc(knowledge_time) < self.known_from:
            status = "unknown_at_knowledge_time"
        elif not group:
            status = "unknown_symbol"
        else:
            for candidate in group:
                if _coverage_start(candidate) <= start and (candidate["execution_end_ms"] is None
                                                       or start < candidate["execution_end_ms"]):
                    episode = candidate
                    break
            if episode is None:
                preceding = [item for item in group if item["execution_end_ms"] is not None
                             and item["execution_end_ms"] <= start]
                if preceding:
                    episode = preceding[-1]
                if start < _coverage_start(group[0]):
                    if group[0]["launch_ms"] is None:
                        status = "before_confirmed_active"
                        evidence_episode = group[0]
                    else:
                        status = "before_known_launch"
                elif group[-1]["execution_end_ms"] is not None and start >= group[-1]["execution_end_ms"]:
                    status = "at_or_after_execution_end"
                else:
                    status = "between_episodes"
                if any(start < _coverage_start(item) < end for item in group):
                    status = "crosses_boundary"
            else:
                execution_end = episode["execution_end_ms"]
                restricted = episode["new_positions_stop_ms"]
                if execution_end is not None and end > execution_end:
                    status = "crosses_boundary"
                elif restricted is not None and start < restricted < end:
                    status = "crosses_boundary"
                elif restricted is not None and start >= restricted:
                    status = "new_positions_restricted"
                else:
                    status = "within_known_episode"
        evidence_episode = episode or evidence_episode
        evidence = (tuple(evidence_episode["events"] + evidence_episode["pre_market_events"])
                    if evidence_episode else ())
        return HistoryClassification(status, symbol, start, end,
            episode["instrument_id"] if episode else None,
            episode["asset_id"] if episode else None,
            episode["instrument_version_id"] if episode else None, evidence)


def row_interval(row: ReleasedRow) -> tuple[str, int, int] | None:
    """Return original half-open market interval, or None for reference/gap rows."""
    file = row.file
    fields = row.fields
    if (file.component not in {"", "retained_book_depth", "retained_book_ticker"}
            or file.product not in (_PERIOD_PRODUCTS | set(_POINT_FIELDS)
                                     | {"binance_usdm_liquidation_observed_daily"})
            or (file.product == "binance_usdm_cost_calibration"
                and file.component not in {"retained_book_depth", "retained_book_ticker"})):
        return None
    symbol_values = [fields[key] for key in ("venue_symbol", "native_symbol", "symbol")
                     if key in fields and fields[key] is not None]
    _need(all(type(value) is str and value for value in symbol_values),
          "row symbol is malformed")
    if file.native_symbol is not None:
        _need(all(value == file.native_symbol for value in symbol_values),
              "row symbol differs from partition native_symbol")
        symbol = file.native_symbol
    else:
        _need(bool(symbol_values) and len(set(symbol_values)) == 1,
              "market row without partition symbol needs a documented row symbol")
        symbol = symbol_values[0]
    if file.product in _PERIOD_PRODUCTS:
        start = _int_ms(fields.get("open_time"), "period open_time")
        close = _int_ms(fields.get("close_time"), "period close_time")
        _need(close >= start, "period close_time precedes open_time")
        return symbol, start, close + 1
    if file.product == "binance_usdm_liquidation_observed_daily":
        start = _int_ms(fields.get("event_time_ms"), "liquidation UTC day")
        seconds = fields.get("source_interval_seconds")
        _need(type(seconds) is int and seconds > 0, "liquidation day interval is malformed")
        return symbol, start, start + seconds * 1000
    if file.product in _POINT_FIELDS:
        key = _POINT_FIELDS[file.product]
        if key is None:
            key = {"retained_book_depth": "timestamp",
                   "retained_book_ticker": "event_time"}.get(file.component)
            if key is None:
                return None
        point = _int_ms(fields.get(key), key)
        return symbol, point, point + 1
    return None


def annotate_row(row: ReleasedRow, history: ContractHistory,
                 knowledge_time: datetime | str) -> AnnotatedRow:
    knowledge_time = _utc(knowledge_time)
    interval = row_interval(row)
    if interval is None:
        return AnnotatedRow(row, None, "reference_or_gap_has_no_market_interval")
    return AnnotatedRow(row, history.classify(*interval, knowledge_time))


def iter_history_rows(reader: Cex002ReleaseReader, history: ContractHistory,
                      knowledge_time: datetime | str, product: str, **selection: Any) -> Iterator[AnnotatedRow]:
    _need(reader.publication_sha256 == history.publication_sha256,
          "contract history does not bind this market publication")
    for row in reader.iter_rows(product, **selection):
        yield annotate_row(row, history, knowledge_time)
