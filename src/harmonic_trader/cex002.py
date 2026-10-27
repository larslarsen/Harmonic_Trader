"""Read and deliver bounded selections from the complete published CEX-002 release."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any

from harmonic_trader.data.cex002 import Cex002ReaderError, Cex002ReleaseReader, PUBLICATION_SHA256
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
        if name == "nautilus":
            command.add_argument("--clock-policy", required=True, choices=[CLOCK_POLICY])
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
            print(json.dumps({
                "product": row.file.product, "component": row.file.component,
                "dataset_id": row.file.dataset_id, "file": row.file.relative_path,
                "file_sha256": row.file.sha256, "ordinal": row.ordinal,
                "fields": row.fields, "source_available_at": None,
            }, sort_keys=True, default=_json_default))
        return 0
    if not rows:
        raise Cex002ReaderError("Nautilus delivery selection has no market rows")
    delivered = deliver_to_nautilus(rows, clock_policy=args.clock_policy)
    print(json.dumps({"custom_count": delivered["custom_count"],
                      "bar_count": delivered["bar_count"],
                      "first_custom": delivered["custom_receipts"][0],
                      "first_bar": (delivered["bar_receipts"][0]
                                    if delivered["bar_receipts"] else None),
                      "clock_policy": delivered["clock_policy"],
                      "source_available_at": None}, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
