"""Operator next-step text for first-run server/client failures.

Keep these honest: OPEN MODE is never the suggested fix. Cancel
terminalization (lifecycle §9.1) is out of scope here.
"""

from __future__ import annotations


def hint_port_busy(port: int) -> str:
    return (
        f'configured port {port} is unavailable. next: choose one free port and '
        'use that same value for both `rdap start --port` and `rdap invite --port` '
        f'(or `python -m team_agents serve --port`). Check with `rdap doctor` '
        f'or `rdap health --url http://127.0.0.1:{port}`.'
    )


def hint_unreachable(url: str) -> str:
    base = url.rstrip('/')
    return (
        f'cannot reach {base}. next: start the node '
        '(`rdap start --ip 127.0.0.1 --port <PORT> --provider echo` or '
        '`python -m team_agents serve --host 127.0.0.1 --port <PORT> --provider echo`) '
        f'then `rdap health --url {base}` or `curl -sS {base}/health`.'
    )


def hint_timeout(url: str) -> str:
    base = url.rstrip('/')
    return (
        f'peer at {base} timed out. next: confirm the node is still running '
        f'(`rdap health --url {base}` or `curl -sS {base}/health`). '
        'If /health is ok, the brain may still be working — retry. '
        'HTTP 503 means RPC capacity is exhausted: wait, or raise '
        'TEAM_MAX_CONCURRENT_RPC on the server. Do not pass --open.'
    )


def hint_rpc_capacity() -> str:
    return (
        'RPC capacity exhausted. next: retry shortly, or raise '
        'TEAM_MAX_CONCURRENT_RPC on the server (default 16). '
        'Do not switch to --open to bypass this.'
    )


def hint_missing_keys(path: str) -> str:
    return (
        f'Raven keys are missing or unusable at {path}. next: run '
        '`rdap init --name you --no-internet` in this RDAP_HOME, or pass '
        '`--keys-dir <repo>/.team/keys` to `python -m team_agents`.'
    )


def hint_peer_pin() -> str:
    return (
        'pinned Raven identity did not match the live card. next: the '
        'destination `start` must be running; re-run `rdap trust` with the '
        'complete invite (including http URL). Do not pass --open.'
    )


def hint_unsigned_open() -> str:
    return (
        'this node requires signed tasks (OPEN MODE is off). next: send a '
        'Raven-signed task (`rdap ask` or `python -m team_agents send` with '
        '--keys-dir and peer pins). `--open` / TEAM_REQUIRE_SIGNED=0 is a '
        'dangerous explicit override, never the default.'
    )
