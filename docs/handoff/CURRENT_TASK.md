# Current Task

Ticket: HT-001

State: AUTHORIZED_FOR_GROK

Actor: Sr Dev - Grok Build High

Source baseline: `6b08a6afc5b44fc3a0867515a80e7ffc8b144a33`

The source baseline must be an ancestor of `HEAD`; it is not the expected `HEAD`
because this handoff is a later reviewer-authored governance commit. Before editing,
confirm that the only committed paths after the baseline are `AGENTS.md`,
`docs/handoff/CURRENT_TASK.md`, and `tickets/HT-001.md`.

Read and implement [HT-001](../../tickets/HT-001.md) exactly. Add the training-only robust
block transform and matched FULL/MICRO/GEOMETRY matrices. Do not add clustering, labels,
returns, Nautilus code, storage adapters, or experiment execution.

Authorized paths:

- `src/harmonic_trader/modeling/__init__.py`
- `src/harmonic_trader/modeling/representation.py`
- `tests/test_representation.py`

The existing five unrelated untracked research drafts are out of scope. Do not use Git.
Run only the two targeted commands in the ticket, then stop with hashes and results for
reviewer inspection.
