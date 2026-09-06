# Newcomer: what an RDAP task looks like

Operator bridge only. This page does **not** replace or amend the Sprint 0
freeze. Normative current semantics and open gaps live in
[`rdap-task-lifecycle.md`](rdap-task-lifecycle.md). Address deny-list /
`TEAM_REVOCATIONS` honesty: [`rdap-revocation.md`](rdap-revocation.md).

## After `trust` + `ask`

The peer runs an A2A task. Statuses you may see:

- **REJECTED** — signed-mode auth/delegation failed; payload is not journaled;
  not retained in history.
- **SUBMITTED → WORKING → COMPLETED** — happy path for `rdap ask` with
  echo/provider.
- **FAILED** — executor/brain error.
- **CANCELED** — Cancel RPC by the **task owner** (same Raven principal that
  created it); other peers get task-not-found.

Tasks are **owner-scoped**: List/Get/Subscribe/Cancel only see your signed
Raven identity’s tasks.

Two independent auth checks: (1) every JSON-RPC request is Raven HTTP-signed;
(2) the task/answer payload carries a separate delegation signature. Both must
pass in signed mode. Do **not** use `--open` for normal use.

## Cancel caveat (honest, not fully terminalized)

Cancel currently force-saves a `CANCELED` status for the Cancel caller, but the
in-flight brain may still finish a COMPLETED artifact — open conformance gap;
do not treat cancel as fully terminalized yet (see lifecycle
[§9.1](rdap-task-lifecycle.md#91-critical--cancel-status-skew-open-o5-conformance-gap)).

This is Role #14 Sprint 1 ticket #1. This newcomer PR does not implement that
fix.
