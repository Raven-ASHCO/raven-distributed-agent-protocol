"""CLI: run an agent node, inspect its raven identity, or delegate tasks.

Newcomer path (signed, no --open): ``./rdap try`` then ``./rdap start`` and
``./rdap health --url http://127.0.0.1:9001``. Advanced equivalent:

    python -m team_agents serve --name you --host 127.0.0.1 --port 9001 \
        --repo team-repo --peers peers.json --provider echo
    curl -sS http://127.0.0.1:9001/health
    python -m team_agents send --url http://127.0.0.1:9001 --text "ping" \
        --keys-dir <sender>/.team/keys --peer-address <rvn1> --peer-public-key <hex>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import NodeConfig, load_trusted_peers
from .raven_identity import RavenIdentity


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument('--repo', default='.', help='shared team repo path')
    p.add_argument(
        '--peers',
        default='',
        help='JSON file of trusted peers {rvn1addr: pubhex} or {alias: {address, pubkey}}',
    )
    p.add_argument(
        '--require-signed', action='store_true',
        help='deprecated no-op: signed tasks are already required by default',
    )
    p.add_argument(
        '--open', action='store_true',
        help='DANGEROUS: explicitly accept unsigned tasks',
    )


def _apply_common(cfg: NodeConfig, args: argparse.Namespace) -> NodeConfig:
    from .runtime_hints import warn_unsigned_env_without_flag

    cfg.repo_path = Path(args.repo).resolve()
    if args.peers:
        cfg.trusted_peers = load_trusted_peers(Path(args.peers))
    # CLI wins: TEAM_REQUIRE_SIGNED=0 must not open a node without --open.
    warn_unsigned_env_without_flag(open_flag=bool(args.open))
    cfg.require_signed_tasks = not args.open
    return cfg


def cmd_serve(args: argparse.Namespace) -> None:
    from .server import serve

    from .config import LLMConfig, Skill, resolve_custom_llm_api_key
    from .runtime_hints import format_serve_failure

    try:
        cfg = NodeConfig.from_env()
        cfg.name = args.name or cfg.name
        cfg.role = args.role or ''
        cfg.host = args.host
        cfg.port = args.port
        if args.url:
            cfg.public_url = args.url
        if args.token or args.token_file:
            from .client import resolve_bearer_token

            cfg.auth_token = resolve_bearer_token(args.token, args.token_file)
        cfg.enable_experimental_mailbox = args.experimental_plaintext_mailbox
        if args.allow_shell:
            cfg.allow_shell = True
        for spec in args.skill or []:
            sid, name, desc = (spec.split(':', 2) + ['', ''])[:3]
            cfg.skills.append(Skill(id=sid, name=name or sid, description=desc))
        provider_overridden = bool(str(args.provider).strip())
        selected_provider = str(
            args.provider or cfg.llm.provider
        ).strip().lower()
        cfg.llm = LLMConfig(
            provider=selected_provider,
            model=(
                args.model
                or ('' if provider_overridden else cfg.llm.model)
            ),
            base_url=(
                args.base_url
                or ('' if provider_overridden else cfg.llm.base_url)
            ),
            _api_key=(
                resolve_custom_llm_api_key() if selected_provider == 'custom' else ''
            ),
        )
        cfg.llm.require_ready()
        _apply_common(cfg, args)
        serve(cfg)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        keys_dir = str(Path(getattr(args, 'repo', '.') or '.').resolve() / '.team' / 'keys')
        raise SystemExit(
            format_serve_failure(
                exc,
                keys_dir=keys_dir,
                provider=str(getattr(args, 'provider', '') or ''),
            )
        ) from exc


def cmd_id(args: argparse.Namespace) -> None:
    identity = RavenIdentity.load_or_create(Path(args.keys_dir))
    print(json.dumps(identity.identity_card(), indent=2))


def cmd_send(args: argparse.Namespace) -> None:
    from .client import (
        CardVerificationError,
        UnsafeBearerTransportError,
        send_task,
    )

    identity = RavenIdentity.load_or_create(args.keys_dir) if args.keys_dir else None
    print(
        f'* sending signed task to {args.url} (timeout 180s) …',
        flush=True,
    )
    try:
        result = __import__('asyncio').run(
            send_task(
                args.url,
                args.text,
                identity=identity,
                expected_peer_address=args.peer_address,
                expected_peer_public_key=args.peer_public_key,
                token_file=args.token_file,
            )
        )
    except (
        TimeoutError,
        ConnectionError,
        RuntimeError,
        ValueError,
        CardVerificationError,
        UnsafeBearerTransportError,
    ) as exc:
        raise SystemExit(str(exc)) from exc
    print(result)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='team_agents',
        description=(
            'Advanced RDAP node CLI. Newcomer path: ./rdap try then '
            './rdap start and ./rdap health. .team/keys is not raven-node. '
            'Signed HTTP is not confidential ATSAM. OPEN MODE (--open) is never default.'
        ),
    )
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('serve', help='run an A2A agent node')
    s.add_argument('--name', default='')
    s.add_argument('--role', default='')
    s.add_argument('--host', default='127.0.0.1')
    s.add_argument('--port', type=int, default=8081)
    s.add_argument('--url', default='', help='public url advertised in the agent card')
    s.add_argument('--token', default='', help='Bearer token (argv-visible; prefer env/file)')
    s.add_argument('--token-file', default='', help='read server Bearer token from file')
    s.add_argument(
        '--experimental-plaintext-mailbox', action='store_true',
        help='DANGEROUS/EXPERIMENTAL: enable non-confidential mailbox adapter',
    )
    s.add_argument('--allow-shell', action='store_true')
    s.add_argument('--skill', action='append', default=[], help='id:name:description')
    s.add_argument(
        '--provider', default='',
        help='echo | openai | groq | openrouter | ollama | custom',
    )
    s.add_argument('--model', default='')
    s.add_argument('--base-url', default='')
    _add_common(s)
    s.set_defaults(fn=cmd_serve)

    i = sub.add_parser('id', help='print raven identity for a keys dir')
    i.add_argument('--keys-dir', required=True)
    i.set_defaults(fn=cmd_id)

    d = sub.add_parser('send', help='delegate a task to a teammate node')
    d.add_argument('--url', required=True)
    d.add_argument('--text', required=True)
    d.add_argument('--keys-dir', required=True)
    d.add_argument('--peer-address', required=True)
    d.add_argument('--peer-public-key', required=True)
    d.add_argument('--token-file', default='', help='Bearer token file')
    d.set_defaults(fn=cmd_send)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
