"""Signature checks: signed transaction envelopes (== the prepared one) and SEP-53 messages."""

from __future__ import annotations

import base64
import binascii

from stellar_sdk import FeeBumpTransactionEnvelope, Keypair, StrKey, TransactionEnvelope
from stellar_sdk.exceptions import BadSignatureError

from app.modules.stellar.errors import TxMismatch


def is_account_address(address: str) -> bool:
    """A valid ``G…`` StrKey (version byte and CRC16 checksum)."""
    return StrKey.is_valid_ed25519_public_key(address)


def verify_signed_envelope(
    signed_xdr: str, *, prepared_hash: str, source: str, passphrase: str
) -> TransactionEnvelope:
    """The signed envelope must be byte-for-byte the prepared transaction, signed by its source.

    The transaction hash covers the network id, every operation, auth entry, fee and time
    bound, so any modification (or a different network) changes it.
    """
    try:
        envelope = TransactionEnvelope.from_xdr(signed_xdr, passphrase)
    except Exception as exc:
        if _is_fee_bump(signed_xdr, passphrase):
            raise TxMismatch("Fee-bump envelopes are not accepted.") from exc
        raise TxMismatch("The signed transaction could not be parsed.") from exc
    if envelope.hash_hex() != prepared_hash:
        raise TxMismatch()
    if envelope.transaction.source.account_id != source:
        raise TxMismatch("The transaction source is not the expected wallet.")
    keypair = Keypair.from_public_key(source)
    tx_hash = envelope.hash()
    for signature in envelope.signatures:
        if signature.signature_hint != keypair.signature_hint():
            continue
        try:
            keypair.verify(tx_hash, signature.signature)
            return envelope
        except BadSignatureError:
            continue
    raise TxMismatch("The transaction is not signed by the expected wallet.")


def _is_fee_bump(xdr: str, passphrase: str) -> bool:
    try:
        FeeBumpTransactionEnvelope.from_xdr(xdr, passphrase)
    except Exception:
        return False
    return True


def decode_signature(signature: str) -> bytes | None:
    """Freighter ``signMessage`` returns the 64-byte ed25519 signature base64-encoded."""
    try:
        raw = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 64 else None


def verify_message(address: str, message: str, signature: str) -> bool:
    """SEP-53: ed25519 over SHA-256("Stellar Signed Message:\\n" + message)."""
    raw = decode_signature(signature)
    if raw is None or not is_account_address(address):
        return False
    try:
        Keypair.from_public_key(address).verify_message(message.encode(), raw)
    except BadSignatureError:
        return False
    return True
