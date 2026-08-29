# AGENTS.md

This file governs agent work in the Harmonic Trader repository.

## Repository Boundary

- This repository is independent of `Crypto_Multifactor_Bot` and does not inherit that
  repository's one-active-ticket rule.
- `Crypto_Multifactor_Bot` owns CEX/DEX acquisition and immutable data publication.
  Harmonic Trader consumes accepted releases read-only.
- No price-only substitute, partial CEX bundle, fabricated microstructure, or scored
  experiment is permitted before the complete CEX-002 release is accepted.
- Secrets, credentials, local data paths, and generated research outputs are never
  committed.

## Roles

- **Lead Quantitative Finance Researcher/Engineer (reviewer):** owns architecture,
  experiment semantics, task contracts, source review, independent validation, acceptance,
  commits, and pushes. After baseline commit `6b08a6a`, the reviewer does not author
  production or test implementation for delegated drops.
- **Sr Dev - Grok Build:** authors reviewer-bounded production and test source. It may run
  only the targeted tests and lint commands explicitly authorized by the current task. It
  does not edit governance/research records, use Git, commit, push, access real research
  outcomes, or change architecture.
- **Owner:** relays the repository task prompt and developer completion report. The owner
  is not an acceptance authority.

The reviewer may author and publish governance, architecture, task, and review documents.
Only the reviewer accepts a developer drop.

## Workflow

1. Read `docs/handoff/CURRENT_TASK.md` and its referenced ticket.
2. Verify the exact base commit.
3. Modify only the authorized paths.
4. Run only explicitly authorized commands.
5. Return changed paths, hashes, line counts, test counts, and command results.
6. Stop for reviewer inspection without Git operations.

Unrelated untracked research drafts are owner work. Do not edit, stage, delete, move, or
include them in completion evidence.
