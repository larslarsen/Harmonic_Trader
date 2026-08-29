# Current Task

Ticket: HT-003

State: CORRECTION REQUIRED

Actor: Sr Dev - Grok Build High

Perform Reviewer Correction 1 in
[HT-003](../../tickets/HT-003.md#reviewer-correction-1). The first drop failed static
review; the reviewer did not run the acceptance commands.

The accepted implementation source baseline is
`8df6a8aa70bbb1582b1b1a4a430977a161b26088`. Prove it is an ancestor of `HEAD`; the only
committed paths between that baseline and this reviewer handoff may be this file and the
HT-003 ticket. Do not require `HEAD` to equal the source baseline.

Modify only the three paths authorized by HT-003. The correction must bind native funding
to the exact latest declared mark; reject any flat native adjustment including zero;
preserve and validate settlement currency and native commission sign; capture account
state after position-open/position-close processing; add independent exact long/short
decomposition assertions; and add the missing fail-closed tests. The complete findings
and required changes are repository-native in Reviewer Correction 1; no relay prompt
supplements or overrides them.

After editing, run each existing HT-003 authorized command exactly once, stop on the first
nonzero result, and return the required source hashes, line counts, test count, and command
results. Do not use Git, install packages, access the network or real data, inspect
research outcomes, or edit governance/research files.

This is a fixture-only financial-semantic drop. It does not authorize an accepted-bundle
adapter, production strategy, final numerical execution/holding rule, liquidation model,
real-data backtest, or scored experiment.

The five unrelated untracked research drafts and owner-created `graphify-out/` directory
remain out of scope. Preserve them unchanged.
