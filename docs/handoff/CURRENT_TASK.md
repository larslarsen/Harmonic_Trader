# Current Task

Ticket: HT-003

State: AUTHORIZED

Actor: Sr Dev - Grok Build High

Implement the bounded independent Nautilus execution and accounting reconciliation
fixtures specified in [HT-003](../../tickets/HT-003.md).

The accepted implementation source baseline is
`8df6a8aa70bbb1582b1b1a4a430977a161b26088`. Prove it is an ancestor of `HEAD`; the only
committed paths between that baseline and this reviewer handoff may be this file and the
HT-003 ticket. Do not require `HEAD` to equal the source baseline.

Modify only the three paths authorized by HT-003. Use the already provisioned exact
NautilusTrader 2.0.0rc3 environment, run only the two commands authorized there, stop on
the first nonzero command, and return the required source hashes, line counts, test count,
and command results. Do not use Git, install packages, access the network or real data,
inspect research outcomes, or edit governance/research files.

This is a fixture-only financial-semantic drop. It does not authorize an accepted-bundle
adapter, production strategy, final numerical execution/holding rule, liquidation model,
real-data backtest, or scored experiment.

The five unrelated untracked research drafts and owner-created `graphify-out/` directory
remain out of scope. Preserve them unchanged.
