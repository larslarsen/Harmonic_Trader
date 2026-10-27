"""Read and deliver bounded selections from the complete published CEX-002 release."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any

from harmonic_trader.data.cex002 import Cex002ReaderError, Cex002ReleaseReader, PUBLICATION_SHA256
from harmonic_trader.data.cex002_history import ContractHistory, REFERENCE_POLICY, annotate_row
from harmonic_trader.integration.cex002_data import CLOCK_POLICY, deliver_to_nautilus


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"cannot display {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="root containing data/.cex002_harmonic_bundle")
    parser.add_argument("--publication-sha", default=PUBLICATION_SHA256,
                        help="trusted publication SHA-256; override only for a known fixture/release")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory", help="list all eleven published products")
    for name in ("rows", "nautilus"):
        command = commands.add_parser(name)
        command.add_argument("--product", required=True)
        command.add_argument("--symbol")
        command.add_argument("--month", help="declared partition month; ticker uses transaction time")
        command.add_argument("--component")
        command.add_argument("--start-ms", type=int, help="inclusive UTC event milliseconds")
        command.add_argument("--end-ms", type=int, help="exclusive UTC event milliseconds")
        command.add_argument("--limit", type=int, default=10)
        command.add_argument("--history", type=Path, help="pinned retrospective contract companion")
        command.add_argument("--history-sha", help="required SHA-256 of --history")
        command.add_argument("--knowledge-time", help="explicit UTC research knowledge time")
        if name == "nautilus":
            command.add_argument("--clock-policy", required=True, choices=[CLOCK_POLICY])
            command.add_argument("--reference-policy", choices=[REFERENCE_POLICY])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "inventory" and not 1 <= args.limit <= 65_536:
        raise Cex002ReaderError("limit must be in 1..65536")
    reader = Cex002ReleaseReader(args.root, args.publication_sha)
    if args.command == "inventory":
        for item in reader.inventory():
            print(json.dumps(item, sort_keys=True))
        return 0
    supplied = (args.history is not None, args.history_sha is not None,
                args.knowledge_time is not None)
    if any(supplied) and not all(supplied):
        raise Cex002ReaderError("history, history-sha and knowledge-time must be supplied together")
    history = (ContractHistory(args.history, sha256=args.history_sha,
                               publication_sha256=reader.publication_sha256)
               if all(supplied) else None)
    if args.command == "nautilus" and ((history is None and args.reference_policy is not None)
                                      or (history is not None and args.reference_policy != REFERENCE_POLICY)):
        raise Cex002ReaderError("history-aware Nautilus projection requires reviewed notices policy")
    component = args.component
    if args.command == "nautilus" and component is None and args.product in {
        "binance_usdm_bar_1h", "binance_usdm_trade_flow_1h",
        "binance_usdm_open_interest_5m", "binance_usdm_funding_realized",
        "binance_usdm_funding_indicative_1h", "binance_usdm_mark_index_basis_1h",
        "binance_usdm_liquidation_observed_daily",
    }:
        component = ""
    rows = list(islice(reader.iter_rows(
        args.product, symbol=args.symbol, month=args.month, component=component,
        start_ms=args.start_ms, end_ms=args.end_ms,
    ), args.limit))
    if args.command == "rows":
        for row in rows:
            record = {
                "product": row.file.product, "component": row.file.component,
                "dataset_id": row.file.dataset_id, "file": row.file.relative_path,
                "file_sha256": row.file.sha256, "ordinal": row.ordinal,
                "fields": row.fields, "source_available_at": None,
            }
            if history is not None:
                annotation = annotate_row(row, history, args.knowledge_time)
                record["reference_classification"] = (
                    annotation.classification.as_dict() if annotation.classification
                    else {"status": "no_market_interval", "reason": annotation.interval_reason})
                record["history_sha256"] = history.sha256
            print(json.dumps(record, sort_keys=True, default=_json_default))
        return 0
    if not rows:
        raise Cex002ReaderError("Nautilus delivery selection has no market rows")
    delivered = deliver_to_nautilus(rows, clock_policy=args.clock_policy,
                                    history=history, knowledge_time=args.knowledge_time,
                                    reference_policy=args.reference_policy,
                                    publication_sha256=(reader.publication_sha256 if history else None))
    print(json.dumps({"custom_count": delivered["custom_count"],
                      "bar_count": delivered["bar_count"],
                      "first_custom": delivered["custom_receipts"][0],
                      "first_bar": (delivered["bar_receipts"][0]
                                    if delivered["bar_receipts"] else None),
                      "clock_policy": delivered["clock_policy"],
                      "qualification": delivered["qualification"],
                      "history_sha256": delivered["history_sha256"],
                      "source_available_at": None}, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
