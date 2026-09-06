"""M1 public same-RVN1 bind (ADR 0004 D3). NON-RELEASE / HOLD.

Import **public** raven-node / ash whoami material so RDAP's principal is the
same user-identity RVN1 as the local node. This is not a signing-key import,
not ATSAM, and not a confidential carrier.

RAVEN M1 export MUST match this schema (or the ash-field aliases below).
If the RAVEN whoami JSON is not yet merged, this document is the stable
contract the export must emit.

Schema ``raven.whoami.public.v1`` (JSON object):

    {
      "schema": "raven.whoami.public.v1",
      "address": "rvn1…",
      "public_key": "<64 hex user-identity Ed25519>",
      "fingerprint": "<RavenDeviceFingerprintV1>",
      "pin": {"kind": "ash-contact", "fingerprint": "<same>"}
    }

Aliases accepted so an ash-style block can be JSON-wrapped without renaming:

- ``pub_hex`` → ``public_key`` (user identity that **derives** the RVN1)
- ``pin`` may be that fingerprint string, or omitted (then derived)

Forbidden:

- Private key / seed / JWK ``d`` / PEM PRIVATE KEY anywhere in the document
- Using ``device_ed_pub`` (or aliases) as the pin — pin ≢ device_ed_pub
- ``confidential`` / ``atsam_rvn1`` / E2EE send claims

This module never logs import values (they may be hostile). Errors name the
*class* of problem, not the rejected material.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .raven_identity import fingerprint_for_public_key, validate_address_public_key

WHOAMI_SCHEMA = 'raven.whoami.public.v1'
WHOAMI_SCHEMA_ALIASES = frozenset({WHOAMI_SCHEMA, 'raven.whoami.v1'})
ASH_CONTACT_PIN_KIND = 'ash-contact'
MAX_WHOAMI_BYTES = 64 * 1024

# User-identity public material only. These derive the RVN1 address.
_PUBLIC_KEY_FIELDS = ('public_key', 'pub_hex', 'publicKey', 'pubkey')
_ADDRESS_FIELDS = ('address', 'rvn1', 'raven_id')
_FINGERPRINT_FIELDS = ('fingerprint', 'fp')

# Pin must stay the user-identity RVN1. device_ed_pub is G5 device lineage.
_DEVICE_KEY_FIELDS = frozenset({
    'device_ed_pub',
    'device_ed_pub_hex',
    'deviceedpub',
    'deviceedpubhex',
    'device_public_key',
    'devicepublickey',
    'device_pubkey',
    'devicepubkey',
    'device_cert_pub',
    'devicecertpub',
    'device_ed25519_pub',
    'deviceed25519pub',
})

# Normalized (alnum, lower) names that mean private material.
_PRIVATE_KEY_NAMES = frozenset({
    'seed',
    'rawseed',
    'private',
    'privatekey',
    'privatekeyhex',
    'privatebytes',
    'priv',
    'privkey',
    'secret',
    'secretkey',
    'signingkey',
    'identityseed',
    'identityprivate',
    'deviceed25519',
    'deviceed25519seed',
    'ed25519seed',
    'sk',
    'd',
})

_CONFIDENTIAL_TRUE_KEYS = frozenset({
    'confidential',
    'confidentiality',
    'e2ee',
    'e2e',
    'sealed',
    'atsam',
})


class PrivateKeyMaterialError(ValueError):
    """Import contained private-key material and was rejected fail-closed."""


class ConfidentialClaimError(ValueError):
    """M1 bind refuses any confidential / atsam_rvn1 send claim."""


@dataclass(frozen=True)
class PublicWhoami:
    """Public user-identity RVN1 + ash-style contact pin. No private fields."""

    address: str
    public_key: str
    fingerprint: str
    pin_kind: str = ASH_CONTACT_PIN_KIND

    def as_public_dict(self) -> dict[str, object]:
        return {
            'schema': WHOAMI_SCHEMA,
            'address': self.address,
            'public_key': self.public_key,
            'fingerprint': self.fingerprint,
            'pin': {
                'kind': self.pin_kind,
                'address': self.address,
                'public_key': self.public_key,
                'fingerprint': self.fingerprint,
                'invite': ash_contact_invite(self.address, self.public_key),
            },
        }

    def ash_invite(self) -> str:
        return ash_contact_invite(self.address, self.public_key)


def ash_contact_invite(address: str, public_key: str) -> str:
    """Ash-style contact pin of the user-identity RVN1 (not device_ed_pub)."""
    return f'raven:{address}:{public_key}'


def refuse_confidential_claim(carrier: str = 'atsam_rvn1') -> None:
    """Always fail-closed. M1 is public bind only; HOLD is active."""
    raise ConfidentialClaimError(
        'NON-RELEASE / HOLD: M1 same-RVN1 public bind cannot claim confidential '
        f'delivery or carrier {carrier!r}; no ATSAM seal / atsam_rvn1 send'
    )


def _norm_key(name: object) -> str:
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def _looks_like_pem_private(value: object) -> bool:
    if not isinstance(value, str):
        return False
    upper = value.upper()
    return 'BEGIN' in upper and 'PRIVATE KEY' in upper


def _reject_private_and_confidential(document: object) -> None:
    """Walk the import. Never include node values in raised messages."""
    stack: list[object] = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            for raw_key, value in node.items():
                key = _norm_key(raw_key)
                if key in _PRIVATE_KEY_NAMES or _looks_like_pem_private(value):
                    raise PrivateKeyMaterialError(
                        'whoami import rejected: private key material is present'
                    )
                if key in _CONFIDENTIAL_TRUE_KEYS and value not in (
                    False, 0, '0', 'false', 'no', '', None,
                ):
                    refuse_confidential_claim(str(raw_key))
                if key in {'carrier', 'carriertype', 'sendpath'} and _norm_key(
                    value
                ) in {'atsamrvn1', 'atsam', 'confidential'}:
                    refuse_confidential_claim(str(value))
                stack.append(value)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif _looks_like_pem_private(node):
            raise PrivateKeyMaterialError(
                'whoami import rejected: private key material is present'
            )


def _first_string(document: Mapping[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = document.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ''


def parse_public_whoami(document: object) -> PublicWhoami:
    """Parse and validate a public whoami object. Fail-closed on private keys."""
    if not isinstance(document, Mapping):
        raise ValueError('whoami document must be a JSON object')
    _reject_private_and_confidential(document)

    schema = str(document.get('schema') or document.get('$schema') or '').strip()
    if schema and schema not in WHOAMI_SCHEMA_ALIASES:
        raise ValueError('unsupported whoami schema')

    address = _first_string(document, _ADDRESS_FIELDS)
    public_key = _first_string(document, _PUBLIC_KEY_FIELDS)
    if not public_key:
        for raw_key in document:
            if _norm_key(raw_key) in _DEVICE_KEY_FIELDS:
                raise ValueError(
                    'whoami pin must be the user-identity RVN1; '
                    'pin is not device_ed_pub'
                )
        raise ValueError('whoami is missing public_key / pub_hex')
    if not address:
        raise ValueError('whoami is missing RVN1 address')

    try:
        validate_address_public_key(address, public_key)
    except ValueError as exc:
        raise ValueError('whoami address/public-key mismatch') from exc
    public_key = public_key.lower()
    derived_fp = fingerprint_for_public_key(public_key)

    stated_fp = _first_string(document, _FINGERPRINT_FIELDS)
    pin = document.get('pin')
    pin_kind = ASH_CONTACT_PIN_KIND
    pin_fp = ''
    if isinstance(pin, str):
        pin_fp = pin.strip()
    elif isinstance(pin, Mapping):
        _reject_private_and_confidential(pin)
        pin_kind = str(pin.get('kind') or ASH_CONTACT_PIN_KIND).strip() or (
            ASH_CONTACT_PIN_KIND
        )
        if pin_kind not in {ASH_CONTACT_PIN_KIND, 'rvn1', 'user-identity'}:
            raise ValueError('whoami pin kind must be ash-contact / user-identity RVN1')
        pin_fp = _first_string(pin, _FINGERPRINT_FIELDS)
        pin_pub = _first_string(pin, _PUBLIC_KEY_FIELDS)
        pin_addr = _first_string(pin, _ADDRESS_FIELDS)
        if pin_pub and pin_pub.lower() != public_key:
            raise ValueError('whoami pin public key does not match user-identity RVN1')
        if pin_addr and pin_addr != address:
            raise ValueError('whoami pin address does not match user-identity RVN1')
        for raw_key in pin:
            if _norm_key(raw_key) in _DEVICE_KEY_FIELDS:
                raise ValueError(
                    'whoami pin must be the user-identity RVN1; '
                    'pin is not device_ed_pub'
                )
    if stated_fp and stated_fp != derived_fp:
        raise ValueError('whoami fingerprint does not match public key')
    if pin_fp and pin_fp != derived_fp:
        raise ValueError('whoami pin fingerprint does not match public key')

    return PublicWhoami(
        address=address,
        public_key=public_key,
        fingerprint=derived_fp,
        pin_kind=ASH_CONTACT_PIN_KIND,
    )


def apply_bind(
    state: Mapping[str, Any],
    whoami: PublicWhoami,
    *,
    source: str = 'file',
) -> dict[str, Any]:
    """Return a copy of RDAP state with the bound public principal.

    Replaces the advertised principal so invite/trust use the ash-style
    contact pin of this RVN1. Does not write a seed or trust root.
    """
    out = dict(state)
    public = whoami.as_public_dict()
    out['address'] = whoami.address
    out['public_key'] = whoami.public_key
    out['fingerprint'] = whoami.fingerprint
    out['raven_bind'] = {
        'schema': WHOAMI_SCHEMA,
        'source': str(source),
        'hold': True,
        'release': False,
        'confidential': False,
        'carrier': 'http_signed',
        'pin': public['pin'],
    }
    return out


def bound_principal(state: Mapping[str, Any] | None) -> PublicWhoami | None:
    """Return the bound public principal, or None if this home is not bound."""
    if not isinstance(state, Mapping):
        return None
    meta = state.get('raven_bind')
    if not isinstance(meta, Mapping):
        return None
    address = str(state.get('address') or '').strip()
    public_key = str(state.get('public_key') or '').strip()
    if not address or not public_key:
        return None
    try:
        return parse_public_whoami({
            'schema': WHOAMI_SCHEMA,
            'address': address,
            'public_key': public_key,
            'fingerprint': state.get('fingerprint', ''),
        })
    except (ValueError, PrivateKeyMaterialError, ConfidentialClaimError):
        return None


def resolve_node_export(data_dir) -> 'Path':
    """Locate a public whoami export under a raven-node data-dir.

    Never reads the encrypted identity store or seed files.
    """
    from pathlib import Path

    root = Path(data_dir)
    if root.is_file() and not root.is_symlink():
        return root
    if not root.is_dir() or root.is_symlink():
        raise ValueError(
            'raven-node data-dir must be a real directory containing a '
            'public whoami export'
        )
    candidates = (
        root / 'whoami.public.json',
        root / 'whoami.json',
        root / 'export' / 'whoami.public.json',
    )
    for path in candidates:
        if path.is_symlink():
            continue
        if path.is_file():
            return path
    raise ValueError(
        'no public whoami export in data-dir (expected whoami.public.json); '
        'refusing to read the private identity store'
    )
