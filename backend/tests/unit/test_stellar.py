"""Stellar adapter: SEP-53, envelope verification, contract bindings, configuration guards."""

from __future__ import annotations

import base64

import pytest
from stellar_sdk import Account, Keypair, Network, StrKey, TransactionBuilder, scval

from app.core.config import StellarNetwork
from app.modules.stellar import contract, signing
from app.modules.stellar.errors import TxMismatch
from tests.chain import contract_strkey
from tests.conftest import OPERATOR, make_settings

PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
CONTRACT = contract_strkey("unit")

# Published SEP-53 test vector (stellar-protocol ecosystem/sep-0053.md).
SEP53_SECRET = "SAKICEVQLYWGSOJS4WW7HZJWAHZVEEBS527LHK5V4MLJALYKICQCJXMW"
SEP53_ADDRESS = "GBXFXNDLV4LSWA4VB7YIL5GBD7BVNR22SGBTDKMO2SBZZHDXSKZYCP7L"
SEP53_SIGNATURE = "fO5dbYhXUhBMhe6kId/cuVq/AfEnHRHEvsP8vXh03M1uLpi5e46yO2Q8rEBzu3feXQewcQE5GArp88u6ePK6BA=="


def test_sep53_published_vector() -> None:
    assert Keypair.from_secret(SEP53_SECRET).public_key == SEP53_ADDRESS
    assert signing.verify_message(SEP53_ADDRESS, "Hello, World!", SEP53_SIGNATURE)
    assert not signing.verify_message(SEP53_ADDRESS, "Hello, World?", SEP53_SIGNATURE)


def test_sep53_generated_keys_and_bad_encodings() -> None:
    keypair, other = Keypair.random(), Keypair.random()
    message = "UniFix wallet verification\nNonce: abc"
    signature = base64.b64encode(keypair.sign_message(message)).decode()
    assert signing.verify_message(keypair.public_key, message, signature)
    assert not signing.verify_message(other.public_key, message, signature)
    assert not signing.verify_message(keypair.public_key, message, keypair.sign_message(message).hex())
    assert not signing.verify_message(keypair.public_key, message, "not base64!")
    assert not signing.verify_message(keypair.public_key, message, base64.b64encode(b"x" * 63).decode())


def test_strkey_checksum() -> None:
    address = Keypair.random().public_key
    assert signing.is_account_address(address)
    corrupted = address[:-1] + ("A" if address[-1] != "A" else "B")
    assert not signing.is_account_address(corrupted)
    assert not signing.is_account_address(CONTRACT)
    assert not signing.is_account_address(Keypair.random().secret)


def _prepared(source: Keypair, *, passphrase: str = PASSPHRASE, amount: int = 5) -> tuple[str, str]:
    escrow_id = bytes(32)
    args = contract.fund_args(escrow_id, source.public_key, Keypair.random().public_key, amount, bytes(32), 1)
    tx = (
        TransactionBuilder(Account(source.public_key, 10), passphrase, base_fee=100)
        .append_invoke_contract_function_op(CONTRACT, "fund", args)
        .add_time_bounds(0, 2_000_000_000)
        .build()
    )
    unsigned = tx.to_xdr()
    tx.sign(source)
    return unsigned, tx.to_xdr()


def test_envelope_verifier_accepts_the_prepared_transaction() -> None:
    source = Keypair.random()
    unsigned, signed = _prepared(source)
    from stellar_sdk import TransactionEnvelope

    prepared_hash = TransactionEnvelope.from_xdr(unsigned, PASSPHRASE).hash_hex()
    envelope = signing.verify_signed_envelope(
        signed, prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE
    )
    assert envelope.hash_hex() == prepared_hash


def test_envelope_verifier_rejects_tampering() -> None:
    from stellar_sdk import TransactionEnvelope

    source = Keypair.random()
    unsigned, signed = _prepared(source)
    prepared_hash = TransactionEnvelope.from_xdr(unsigned, PASSPHRASE).hash_hex()
    check = signing.verify_signed_envelope

    # A different amount: a different transaction.
    _, tampered = _prepared(source, amount=6)
    with pytest.raises(TxMismatch):
        check(tampered, prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE)
    # Signed for another network.
    _, other_network = _prepared(source, passphrase=Network.PUBLIC_NETWORK_PASSPHRASE)
    with pytest.raises(TxMismatch):
        check(other_network, prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE)
    # Not signed at all.
    with pytest.raises(TxMismatch, match="not signed"):
        check(unsigned, prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE)
    # Signed by somebody else.
    envelope = TransactionEnvelope.from_xdr(unsigned, PASSPHRASE)
    envelope.sign(Keypair.random())
    with pytest.raises(TxMismatch, match="not signed"):
        check(envelope.to_xdr(), prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE)
    # A different source account.
    with pytest.raises(TxMismatch):
        check(signed, prepared_hash=prepared_hash, source=Keypair.random().public_key, passphrase=PASSPHRASE)
    with pytest.raises(TxMismatch):
        check("garbage", prepared_hash=prepared_hash, source=source.public_key, passphrase=PASSPHRASE)


def test_builders_encode_contract_arguments() -> None:
    customer, professional = Keypair.random().public_key, Keypair.random().public_key
    args = contract.fund_args(b"\x01" * 32, customer, professional, 2**100, b"\x02" * 32, 1_800_000_000)
    decoded = [contract.native(arg) for arg in args]
    assert decoded == ["01" * 32, customer, professional, 2**100, "02" * 32, 1_800_000_000]
    assert args[3].type.name == "SCV_I128"
    assert args[5].type.name == "SCV_U64"
    assert [contract.native(a) for a in contract.resolve_args(b"\x01" * 32, 7)] == ["01" * 32, 7]
    assert [contract.native(a) for a in contract.open_dispute_args(b"\x01" * 32, customer)][1] == customer
    with pytest.raises(ValueError, match="32 bytes"):
        contract.escrow_only_args(b"short")


def test_escrow_and_event_decoding() -> None:
    customer, professional = Keypair.random().public_key, Keypair.random().public_key
    raw = scval.to_map(
        {
            scval.to_symbol("customer"): scval.to_address(customer),
            scval.to_symbol("professional"): scval.to_address(professional),
            scval.to_symbol("amount"): scval.to_int128(212_121_213),
            scval.to_symbol("terms_hash"): scval.to_bytes(b"\xab" * 32),
            scval.to_symbol("status"): scval.to_vec([scval.to_symbol("CompletionSubmitted")]),
            scval.to_symbol("funded_at"): scval.to_uint64(10),
            scval.to_symbol("refund_after"): scval.to_uint64(20),
            scval.to_symbol("review_window"): scval.to_uint64(30),
            scval.to_symbol("review_deadline"): scval.to_uint64(40),
            scval.to_symbol("disputed_at"): scval.to_void(),
            scval.to_symbol("evidence_hash"): scval.to_bytes(b"\x07" * 32),
            scval.to_symbol("disputed_by"): scval.to_void(),
            scval.to_symbol("professional_payout"): scval.to_int128(0),
            scval.to_symbol("customer_refund"): scval.to_int128(0),
            scval.to_symbol("settled_by"): scval.to_vec([scval.to_symbol("Unsettled")]),
        }
    )
    escrow = contract.decode_escrow(raw)
    assert escrow.status is contract.OnchainStatus.COMPLETION_SUBMITTED
    assert (escrow.amount, escrow.terms_hash, escrow.review_deadline) == (212_121_213, "ab" * 32, 40)
    assert escrow.settled_by is None
    assert escrow.disputed_by is None

    topics = [scval.to_symbol("unifix"), scval.to_symbol("released"), scval.to_bytes(b"\x01" * 32)]
    data = scval.to_map(
        {
            scval.to_symbol("professional_payout"): scval.to_int128(5),
            scval.to_symbol("customer_refund"): scval.to_int128(0),
            scval.to_symbol("settled_by"): scval.to_vec([scval.to_symbol("Customer")]),
        }
    )
    event = contract.decode_event(topics, data)
    assert event is not None
    assert (event.name, event.escrow_key, event.payload["settled_by"]) == (
        "released",
        b"\x01" * 32,
        "CUSTOMER",
    )
    # Somebody else's events are ignored.
    assert contract.decode_event([scval.to_symbol("transfer"), scval.to_symbol("x")], data) is None
    assert contract.contract_error_name("HostError: Error(Contract, #5)") == "InvalidState"
    assert contract.contract_error_name("no error here") is None


def test_settings_guards(migrated_database: str) -> None:
    with pytest.raises(ValueError, match="does not match STELLAR_OPERATOR_ADDRESS"):
        make_settings(migrated_database, stellar_operator_address=Keypair.random().public_key)
    with pytest.raises(ValueError, match="ESCROW_TOKEN_CONTRACT_ID does not match"):
        make_settings(migrated_database, escrow_token_contract_id=contract_strkey("other"))
    with pytest.raises(ValueError, match="only allowed on TESTNET"):
        make_settings(
            migrated_database,
            stellar_network=StellarNetwork.PUBLIC,
            escrow_token_contract_id="CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75",
            escrow_token_issuer="GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        )
    with pytest.raises(ValueError, match="ESCROW_ID_SECRET"):
        make_settings(migrated_database, escrow_id_secret=None)
    with pytest.raises(ValueError, match="not a valid contract"):
        make_settings(migrated_database, escrow_contract_id="CNOTACONTRACT")
    disabled = make_settings(migrated_database, escrow_contract_id=None)
    assert not disabled.escrow_enabled
    assert StrKey.is_valid_ed25519_public_key(OPERATOR.public_key)
