"""Operator next-step text for first-run server/client failures.

Keep these honest: OPEN MODE is never the suggested fix. Cancel
terminalization (lifecycle §9.1) is out of scope here.
"""

from __future__ import annotations

import os


def cli_name() -> str:
    return 'rdap.cmd' if os.name == 'nt' else './rdap'


def invite_host(advertised_host: str, bind_host: str = '') -> str:
    shown = str(advertised_host or bind_host or '127.0.0.1').strip()
    if shown in {'0.0.0.0', '::', '[::]'}:
        return '127.0.0.1'
    return shown


def first_run_next_steps(*, public_url: str, advertised_host: str, port: int) -> str:
    """Exact commands to print after a successful bind (other terminal)."""
    cli = cli_name()
    host = invite_host(advertised_host)
    url = str(public_url).rstrip('/')
    return (
        f'next (other terminal; keep this process running; do not pass --open):\n'
        f'  {cli} health --url {url}\n'
        f'  {cli} invite --ip {host} --port {port}\n'
        f'  {cli} trust \'<complete invite including the http URL>\'\n'
        f'  {cli} ping --name <peer>\n'
        f'  {cli} ask \'Reply exactly: RDAP_OK\' --name <peer>'
    )


def warn_unsigned_env_without_flag(*, open_flag: bool) -> None:
    """TEAM_REQUIRE_SIGNED=0 must not silently open a node without --open."""
    if open_flag:
        return
    if os.environ.get('TEAM_REQUIRE_SIGNED', '1') == '0':
        print(  # noqa: T201
            'TEAM_REQUIRE_SIGNED=0 is ignored unless you pass --open. '
            'Signed tasks stay required. Do not pass --open for a first run.',
            flush=True,
        )


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


def hint_llm_config(provider: str = '', detail: str = '') -> str:
    cli = cli_name()
    head = f'{detail}. '.lstrip('. ') if detail else ''
    wanted = str(provider or 'this provider').strip() or 'this provider'
    return (
        f'{head}invalid or incomplete LLM configuration for {wanted}. next: '
        f'first run uses `{cli} start --ip 127.0.0.1 --port 9001 --provider echo` '
        '(no API key). Hosted brains need the matching env key '
        '(OPENAI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY) or '
        'TEAM_LLM_API_KEY for custom. Do not pass --open.'
    )


def hint_bearer_http() -> str:
    return (
        'refusing Bearer over HTTP (including loopback). next: use HTTPS, '
        'or unset TEAM_AUTH_TOKEN / --token-file and send a signed Raven '
        'task (`rdap ask` / `python -m team_agents send` without Bearer). '
        'Do not pass --open.'
    )


def hint_missing_peer_pin() -> str:
    cli = cli_name()
    return (
        'peer Raven pin is missing or incomplete. next: start the other node, '
        f'run `{cli} invite --ip <peer-ip> --port <peer-port>`, then '
        f'`{cli} trust \'<complete invite including the http URL>\'`. '
        'Do not pass --open.'
    )


def format_serve_failure(exc: BaseException, *, keys_dir: str, provider: str = '') -> str:
    text = str(exc).strip() or type(exc).__name__
    lowered = text.lower()
    if any(token in lowered for token in ('seed', 'keys directory', 'keys dir', '0600')):
        return f'{text}. {hint_missing_keys(keys_dir)}'
    if any(
        token in lowered
        for token in (
            'llm', 'provider', 'api key', 'openai', 'groq', 'openrouter',
            'ollama', 'base url', 'base_url',
        )
    ):
        return hint_llm_config(provider, detail=text)
    if isinstance(exc, PermissionError):
        return f'{text}. {hint_missing_keys(keys_dir)}'
    return (
        f'{text}. next: check keys at {keys_dir} and LLM config '
        f'(`{cli_name()} start --provider echo`). Do not pass --open.'
    )


def format_client_failure(exc: BaseException, url: str) -> str:
    text = str(exc).strip() or type(exc).__name__
    if 'next:' in text:
        return text
    name = type(exc).__name__.lower()
    lowered = text.lower()
    if 'bearer' in name or 'bearer' in lowered:
        return hint_bearer_http()
    if 'timeout' in name or 'timed out' in lowered or 'timeout' in lowered:
        return hint_timeout(url)
    if any(token in name for token in ('connect', 'connection')) or 'refused' in lowered:
        return hint_unreachable(url)
    if any(token in lowered for token in ('card', 'kid', 'signature', 'pin', 'fingerprint')):
        return f'{text}. {hint_peer_pin()}'
    if any(token in lowered for token in ('public key', 'rvn address', 'peer')):
        return f'{text}. {hint_missing_peer_pin()}'
    return (
        f'{text}. next: `{cli_name()} health --url {url.rstrip("/")}` then '
        f're-run `{cli_name()} trust` with the live invite. Do not pass --open.'
    )
