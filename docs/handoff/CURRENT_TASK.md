# Current Task

Ticket: HT-003

State: ACCEPTED

Actor: Lead Quantitative Finance Researcher/Engineer

HT-003's independent exact linear-perpetual ledger and deterministic NautilusTrader rc3
execution/accounting fixtures are accepted at the exact source and test hashes recorded
in [HT-003](../../tickets/HT-003.md#reviewer-acceptance). Independent reviewer validation
collected 12 passing targeted tests and a clean targeted Ruff result.

The accepted fixture boundary proves causal computation and venue latency, adverse
one-tick fills, exact fees and scheduled funding, netting positions, and independent
cash/equity identities for deterministic long and short cases. It does not authorize an
accepted-bundle adapter, production strategy, final numerical execution/holding rule,
liquidation model, real-data backtest, outcome access, or scored experiment.

No developer or next implementation drop is authorized. The fixture-only pre-release
roadmap is complete. Scored execution remains blocked until the complete CEX-002 release
is accepted and the reviewer publishes a new repository-native task.

The five unrelated untracked research drafts and owner-created `graphify-out/` directory
remain out of scope. Preserve them unchanged.
