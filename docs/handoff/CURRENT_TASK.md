# Current Task

Ticket: HT-002

State: AUTHORIZED

Actor: Sr Dev - Grok Build High

Source baseline: `c552e235bc42ae911d13c7b81fd6e6478136178a`

Implement only the registered NautilusTrader custom-observation envelope, causal clock
guards, and deterministic fixture tests specified in [HT-002](../../tickets/HT-002.md).
The integration targets the exact `nautilus_trader==2.0.0rc3` PyO3 API; the reviewer has
already provisioned the ignored `.venv`, so no install or network operation is authorized.

Authorized paths are exactly:

- `pyproject.toml`;
- `src/harmonic_trader/integration/__init__.py`;
- `src/harmonic_trader/integration/nautilus_data.py`;
- `src/harmonic_trader/integration/strategy_clock.py`;
- `tests/test_nautilus_data.py`; and
- `tests/test_nautilus_strategy_clock.py`.

Run each ticket command at most once, stop on the first nonzero result, and report without
Git operations. No storage adapter, real data, outcomes, trading strategy, order/fill,
execution/accounting, or scored experiment is authorized.

The five unrelated untracked research drafts and owner-created `graphify-out/` directory
remain out of scope. Preserve them unchanged.
