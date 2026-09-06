"""M2 plaintext-to-daemon SealUnderSession client. NON-RELEASE / HOLD.

Companion to RAVEN #54 (`IpcRequest::SealUnderSession`). This module submits
application payload bytes to local raven-node IPC and returns the daemon's
``envelope_b64``. It does **not** seal ATSAM/RVNA1 locally, does not lift
RVN1 HOLD, and is not O6 E2E / confidential-delivery Proven.

Wire (must match raven-core ``ipc.rs`` / ash ``ipc_client.rs``):

- Framing: 4-byte big-endian length + JSON (``IPC_VERSION = 1``)
- Request ``op``: ``seal_under_session``
- Fields: ``v``, ``peer_hint``, ``app_payload_b64`` (no field name may
  contain the substring ``plaintext``)
- Success ``ok``: ``seal_under_session_result`` with ``envelope_b64``
- Fail-closed codes (do not collapse): ``ATSAM_SESSION_REQUIRED``,
  ``ATSAM_LINEAGE_REVOKED``

Transport: Unix domain socket ``<data_dir>/raven-node.sock`` or the
canonical Windows named pipe ``\\\\.\\pipe\\raven-node``. Peer-cred /
pipe ACL is enforced by raven-node (ADR 0003); this client only talks
the existing local IPC path.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Mapping

IPC_VERSION = 1
MAX_IPC_FRAME = 256 * 1024
IPC_IO_TIMEOUT_SEC = 10.0
OP_SEAL_UNDER_SESSION = 'seal_under_session'
OK_SEAL_UNDER_SESSION_RESULT = 'seal_under_session_result'
ATSAM_SESSION_REQUIRED = 'ATSAM_SESSION_REQUIRED'
ATSAM_LINEAGE_REVOKED = 'ATSAM_LINEAGE_REVOKED'
WINDOWS_NAMED_PIPE = r'\\.\pipe\raven-node'
UNIX_SOCKET_NAME = 'raven-node.sock'
_FORBIDDEN_JSON_SUBSTRINGS = ('seed', 'private_key', 'plaintext', 'recovery')
_PIPE_BUSY_WINERROR = 231
_PIPE_BUSY_ATTEMPTS = 40

TransactFn = Callable[[dict[str, object]], Mapping[str, object]]


class RavenIpcError(RuntimeError):
    """Local raven-node IPC failed. ``code`` is the daemon/client refuse token."""

    def __init__(self, code: str, message: str = '') -> None:
        self.code = str(code)
        text = message or code
        super().__init__(text)
        self.message = text


class AtsamSessionRequired(RavenIpcError):
    """No persisted authenticated ATSAM session is usable."""

    def __init__(self, message: str = '') -> None:
        super().__init__(
            ATSAM_SESSION_REQUIRED,
            message or (
                f'{ATSAM_SESSION_REQUIRED}: raven-node has no usable ATSAM session; '
                'SealUnderSession is fail-closed (NON-RELEASE / HOLD)'
            ),
        )


class AtsamLineageRevoked(RavenIpcError):
    """Session lineage is covered by Identity RVDR1 / denylist.

    Distinct from :class:`AtsamSessionRequired`. Do not collapse the two.
    """

    def __init__(self, message: str = '') -> None:
        super().__init__(
            ATSAM_LINEAGE_REVOKED,
            message or (
                f'{ATSAM_LINEAGE_REVOKED}: session lineage is revoked; '
                f'not {ATSAM_SESSION_REQUIRED} (NON-RELEASE / HOLD)'
            ),
        )


@dataclass(frozen=True)
class IpcEndpoint:
    """Platform-local raven-node connect target (ash/raven convention)."""

    kind: str
    target: str

    def __str__(self) -> str:
        return self.target


def default_raven_data_dir(
    *,
    raven_data_dir: str = '',
    ash_data_dir: str = '',
    rdap_raven_data_dir: str = '',
    home: str | None = None,
) -> Path:
    """Resolve the ash/raven-node profile directory.

    Order matches raven-core ``paths.rs``: ``RAVEN_DATA_DIR``, ``ASH_DATA_DIR``,
    else keep ``~/.raven-ash`` when that legacy dir exists and ``~/.raven``
    does not, else ``~/.raven``. RDAP also accepts ``RDAP_RAVEN_DATA_DIR``
    (same plane as ``raven-bind --from-node``) after the Raven env vars.
    """
    raven = (raven_data_dir or os.environ.get('RAVEN_DATA_DIR') or '').strip()
    if raven:
        return Path(raven)
    ash = (ash_data_dir or os.environ.get('ASH_DATA_DIR') or '').strip()
    if ash:
        return Path(ash)
    rdap = (
        rdap_raven_data_dir or os.environ.get('RDAP_RAVEN_DATA_DIR') or ''
    ).strip()
    if rdap:
        return Path(rdap)
    if home is None:
        home = os.environ.get('HOME') or os.environ.get('USERPROFILE') or ''
    if not home:
        return Path('./raven-data')
    root = Path(home)
    raven_path = root / '.raven'
    raven_ash = root / '.raven-ash'
    if raven_ash.is_dir() and not raven_path.exists():
        return raven_ash
    return raven_path


def unix_socket_path(data_dir: str | Path) -> Path:
    """``<data_dir>/raven-node.sock`` — raven-core ``default_socket_path``."""
    return Path(data_dir) / UNIX_SOCKET_NAME


def ipc_endpoint(data_dir: str | Path | None = None) -> IpcEndpoint:
    """Unix UDS vs canonical Windows named pipe. Never a UDS path on Windows."""
    if os.name == 'nt':
        return IpcEndpoint('named_pipe', WINDOWS_NAMED_PIPE)
    root = Path(data_dir) if data_dir is not None else default_raven_data_dir()
    return IpcEndpoint('unix_socket', str(unix_socket_path(root)))


def normalize_peer_hint(peer_hint: str) -> str:
    """Require 64 hex chars (device Ed25519), same plane as LanDial expected_pub_hex."""
    hint = str(peer_hint).strip().lower()
    if len(hint) != 64:
        raise ValueError(
            'SEAL_PEER_HINT: peer_hint must be 64 hex chars (device Ed25519)'
        )
    try:
        raw = bytes.fromhex(hint)
    except ValueError as exc:
        raise ValueError(
            'SEAL_PEER_HINT: peer_hint must be 64 hex chars (device Ed25519)'
        ) from exc
    if len(raw) != 32:
        raise ValueError(
            'SEAL_PEER_HINT: peer_hint must be 64 hex chars (device Ed25519)'
        )
    return hint


def encode_app_payload_b64(app_payload: bytes) -> str:
    """Standard base64 of application payload bytes. Not a ``plaintext*`` field."""
    if not isinstance(app_payload, (bytes, bytearray)):
        raise TypeError('app payload must be bytes')
    return base64.b64encode(bytes(app_payload)).decode('ascii')


def seal_under_session_request(
    peer_hint: str,
    app_payload: bytes,
    *,
    v: int = IPC_VERSION,
) -> dict[str, object]:
    """Build the exact RAVEN #54 ``SealUnderSession`` JSON object."""
    body = {
        'op': OP_SEAL_UNDER_SESSION,
        'v': int(v),
        'peer_hint': normalize_peer_hint(peer_hint),
        'app_payload_b64': encode_app_payload_b64(app_payload),
    }
    _refuse_forbidden_json(body)
    return body


def encode_request(req: Mapping[str, object]) -> bytes:
    """Length-prefixed JSON request (4-byte big-endian + body)."""
    _refuse_forbidden_json(req)
    body = json.dumps(req, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    if len(body) > MAX_IPC_FRAME:
        raise RavenIpcError('IPC_FRAME', 'ipc request too large')
    return len(body).to_bytes(4, 'big') + body


def decode_response_frame(frame: bytes) -> dict[str, object]:
    """Parse one length-prefixed IPC response frame into a JSON object."""
    if len(frame) < 4:
        raise RavenIpcError('IPC_FRAME', 'short frame')
    n = int.from_bytes(frame[:4], 'big')
    if n == 0 or n > MAX_IPC_FRAME or len(frame) < 4 + n:
        raise RavenIpcError('IPC_FRAME', 'bad length')
    try:
        parsed = json.loads(frame[4:4 + n].decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RavenIpcError('IPC_FRAME', 'response is not JSON') from exc
    if not isinstance(parsed, dict):
        raise RavenIpcError('IPC_FRAME', 'response must be a JSON object')
    return parsed


def map_seal_response(resp: Mapping[str, object]) -> str:
    """Return ``envelope_b64`` or raise the frozen fail-closed errors."""
    ok = str(resp.get('ok') or '')
    if ok == OK_SEAL_UNDER_SESSION_RESULT:
        envelope = resp.get('envelope_b64')
        if not isinstance(envelope, str) or not envelope.strip():
            raise RavenIpcError('IPC_FRAME', 'SealUnderSessionResult missing envelope_b64')
        return envelope
    if ok == 'error' or 'code' in resp:
        raise_fail_closed(str(resp.get('code') or 'IPC_ERROR'), str(resp.get('message') or ''))
    raise RavenIpcError('IPC_FRAME', f'unexpected IPC response ok={ok!r}')


def raise_fail_closed(code: str, message: str = '') -> None:
    """Map daemon refuse strings. LINEAGE_REVOKED is not SESSION_REQUIRED."""
    token = str(code or '').strip()
    text = str(message or '')
    haystack = f'{token} {text}'
    if haystack.startswith(ATSAM_LINEAGE_REVOKED) or token == ATSAM_LINEAGE_REVOKED:
        raise AtsamLineageRevoked(text or haystack.strip())
    if haystack.startswith(ATSAM_SESSION_REQUIRED) or token == ATSAM_SESSION_REQUIRED:
        raise AtsamSessionRequired(text or haystack.strip())
    raise RavenIpcError(token or 'IPC_ERROR', text or token or 'IPC_ERROR')


def seal_under_session(
    peer_hint: str,
    app_payload: bytes,
    *,
    data_dir: str | Path | None = None,
    transact: TransactFn | None = None,
    timeout: float = IPC_IO_TIMEOUT_SEC,
) -> str:
    """Submit payload bytes to raven-node; return daemon ``envelope_b64``.

    ``transact`` is injectable for unit tests (no live daemon). Live calls
    use the existing local IPC path only.
    """
    req = seal_under_session_request(peer_hint, app_payload)
    if transact is not None:
        return map_seal_response(transact(req))
    endpoint = ipc_endpoint(data_dir)
    return map_seal_response(ipc_transact(req, endpoint, timeout=timeout))


def ipc_transact(
    req: Mapping[str, object],
    endpoint: IpcEndpoint,
    *,
    timeout: float = IPC_IO_TIMEOUT_SEC,
) -> dict[str, object]:
    """One request/response over the platform local IPC endpoint."""
    if endpoint.kind == 'unix_socket':
        return _transact_unix(req, endpoint.target, timeout)
    if endpoint.kind == 'named_pipe':
        return _transact_named_pipe(req, endpoint.target, timeout)
    raise RavenIpcError('ipc_transport_missing', 'ipc_transport_missing')


def _transact_unix(
    req: Mapping[str, object],
    path: str,
    timeout: float,
) -> dict[str, object]:
    if not hasattr(socket, 'AF_UNIX'):
        raise RavenIpcError('ipc_transport_missing', 'ipc_transport_missing')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        try:
            sock.connect(path)
        except OSError as exc:
            raise RavenIpcError(
                'IPC_CONNECT',
                f'cannot connect to raven-node UDS {path}: {exc}',
            ) from exc
        return _transact_stream(req, sock)
    finally:
        sock.close()


def _transact_named_pipe(
    req: Mapping[str, object],
    name: str,
    timeout: float,
) -> dict[str, object]:
    if os.name != 'nt':
        raise RavenIpcError('ipc_transport_missing', 'ipc_transport_missing')
    handle = _open_named_pipe(name)
    try:
        return _transact_file(req, handle, timeout)
    finally:
        handle.close()


def _open_named_pipe(name: str) -> BinaryIO:
    last: OSError | None = None
    for attempt in range(_PIPE_BUSY_ATTEMPTS):
        try:
            return open(name, 'r+b', buffering=0)  # noqa: SIM115
        except OSError as exc:
            last = exc
            winerror = getattr(exc, 'winerror', None)
            if winerror == _PIPE_BUSY_WINERROR and attempt + 1 < _PIPE_BUSY_ATTEMPTS:
                time.sleep(0.05)
                continue
            raise RavenIpcError(
                'IPC_CONNECT',
                f'cannot connect to raven-node named pipe {name}: {exc}',
            ) from exc
    raise RavenIpcError(
        'IPC_CONNECT',
        f'cannot connect to raven-node named pipe {name}: {last}',
    )


def _transact_stream(req: Mapping[str, object], sock: socket.socket) -> dict[str, object]:
    frame = encode_request(req)
    sock.sendall(frame)
    header = _recv_exact_sock(sock, 4)
    n = int.from_bytes(header, 'big')
    if n == 0 or n > MAX_IPC_FRAME:
        raise RavenIpcError('IPC_FRAME', 'IPC_FRAME')
    body = _recv_exact_sock(sock, n)
    return decode_response_frame(header + body)


def _transact_file(
    req: Mapping[str, object],
    handle: BinaryIO,
    timeout: float,
) -> dict[str, object]:
    del timeout
    frame = encode_request(req)
    handle.write(frame)
    handle.flush()
    header = _read_exact_file(handle, 4)
    n = int.from_bytes(header, 'big')
    if n == 0 or n > MAX_IPC_FRAME:
        raise RavenIpcError('IPC_FRAME', 'IPC_FRAME')
    body = _read_exact_file(handle, n)
    return decode_response_frame(header + body)


def _recv_exact_sock(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RavenIpcError('IPC_FRAME', 'ipc connection closed')
        buf.extend(chunk)
    return bytes(buf)


def _read_exact_file(handle: BinaryIO, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = handle.read(n - len(buf))
        if not chunk:
            raise RavenIpcError('IPC_FRAME', 'ipc connection closed')
        buf.extend(chunk)
    return bytes(buf)


def _refuse_forbidden_json(obj: Mapping[str, object]) -> None:
    """Refuse JSON field names matching the raven-core ipc.rs denylist."""
    for key in obj:
        name = str(key).lower()
        for bad in _FORBIDDEN_JSON_SUBSTRINGS:
            if bad in name:
                raise RavenIpcError('forbidden field', 'forbidden field')


def honesty_banner() -> str:
    """Operator-facing NON-RELEASE claim language. Not a Proven / HOLD-lift."""
    return (
        'NON-RELEASE / HOLD active. plaintext-to-daemon SealUnderSession only. '
        'Not O6 E2E Proven. No HOLD lift. Soft-load P0 held. '
        'Seal still requires a raven-node ATSAM session.'
    )
