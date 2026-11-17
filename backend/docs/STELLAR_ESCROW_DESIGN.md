# UniFix — Stellar Wallets and Soroban Escrow Design

Status: **Design for review (2026-11-17). Not implemented.** Implemented by Issues 5 (contract + wallets), 6 (funding, release, reconciliation) and 7 (disputes, refunds).

Network: **Stellar testnet** (`Test SDF Network ; September 2015`). Every operation is a real testnet transaction. Nothing is simulated or presented as settled before on-chain confirmation.

---

## 1. Goals and non-goals

**Goals**

1. A single-payment escrow per booking, enforced by a Soroban contract.
2. The contract enforces who may move funds, independently of the backend and the frontend.
3. The backend cannot release, refund or redirect funds by changing data, and holds no key that can.
4. Double release, refund after release, release after refund, and settlement during a dispute are all impossible **on-chain**.
5. The backend database is a verified mirror of chain state, reconciled from trusted RPC data.

**Non-goals (MVP)**

- Milestone or partial payments. A quote's `milestones` field is descriptive only (see §9).
- Platform fees. The fee is zero; adding one is a contract-level decision (§10).
- Fee sponsorship. Customers pay their own XLM network fees, and testnet XLM comes from Friendbot.
- Mainnet.
- Fiat on/off-ramps.

## 2. Actors and keys

| Actor | Key held by | Can do on-chain |
|---|---|---|
| **Customer** | Customer's own wallet (Freighter) | Fund an escrow (with operator co-signature); release to the professional; open a dispute |
| **Professional** | Professional's own wallet | Refund the customer in full (voluntary cancel); open a dispute |
| **Operator** | Backend (`STELLAR_OPERATOR_SECRET`, env only) | **Only** co-authorize `fund`, attesting that escrow ID, parties, amount and agreement hash match an accepted booking. Cannot move funds. |
| **Arbiter** | UniFix operations wallet in Freighter, held by a human admin. **Not** the backend | Resolve **only escrows that a party has put into dispute**: any split from 0–100% between the two parties |
| **Contract admin** | UniFix operations wallet (same person as the arbiter or a different one) | Rotate the arbiter and operator addresses. No upgrade function and no fund access |

## 3. Trust model

What each party must trust, stated plainly:

1. **Customers trust the contract code** to pay only themselves or the professional. Nobody else can receive funds from an escrow. The contract has no function that sends to a third address.
2. **Undisputed escrows are fully non-custodial.** Only the customer can release, and only the professional can refund. UniFix (admin, arbiter, operator, backend) cannot touch them.
3. **Disputed escrows trust the arbiter.** Once either party opens a dispute on-chain, only the arbiter can settle. The arbiter can split funds between the two parties only, never to itself. This is the single point of human trust, and it matches the PRD's "admin reviews the case manually". Mitigations: the arbiter key lives in a human-held wallet rather than on the server; every resolution has an audit entry and an on-chain event; in production the arbiter should be a Stellar multisig account.
4. **The contract admin can replace the arbiter.** A compromised admin key can therefore resolve disputed escrows, and nothing else. Production should use a multisig. The contract is **not upgradeable**: a new version means a new deployment, and existing escrows stay on the old contract.
5. **The operator key, if stolen,** lets an attacker co-sign new `fund` calls. Funding still requires the customer's own signature and moves the customer's own money into an escrow only they and the professional control, so theft through it is impossible. The impact is limited to creating mislabelled escrows, which the backend would reject during verification.
6. **The backend is trusted for liveness and display, not custody.** If the backend goes down, funds stay safe. Parties can still call `release`, `refund` or `open_dispute` directly with any Stellar tool, and the reconciler picks up those events when the backend returns.
7. **Off-chain fact the contract cannot check:** whether the work was done. That is the customer's judgement (release) or the arbiter's (dispute).

**Known MVP limitation.** A customer who never approves and never disputes leaves funds locked. There is deliberately no on-chain timeout. The professional's remedy is to open a dispute, which the arbiter resolves. An automatic deadline refund or release is listed as a decision in §10.

## 4. Contract interface (`backend/contracts/escrow`)

One contract deployment holds many escrows, keyed by a 32-byte `escrow_id`. One **token** (a Stellar Asset Contract) is fixed at construction. That makes asset validation structural: the contract cannot hold any other asset.

```rust
#[contracttype] pub enum EscrowStatus { Funded, Disputed, Released, Refunded, Resolved }

#[contracttype] pub struct Escrow {
    pub customer: Address,
    pub professional: Address,
    pub amount: i128,               // token base units (7 decimals for classic assets)
    pub agreement_hash: BytesN<32>, // SHA-256 of the accepted agreement (DB anchor)
    pub status: EscrowStatus,
    pub funded_at: u64,             // ledger timestamp
    pub disputed_by: Option<Address>,
    pub professional_payout: i128,  // set on release/resolve
    pub customer_refund: i128,      // set on refund/resolve
}

fn __constructor(env, admin: Address, arbiter: Address, operator: Address, token: Address);

/// customer.require_auth() AND operator.require_auth().
/// Fails if escrow_id exists, amount <= 0, customer == professional.
/// Transfers `amount` of `token` from customer to the contract. Status = Funded.
fn fund(env, escrow_id: BytesN<32>, customer: Address, professional: Address,
        amount: i128, agreement_hash: BytesN<32>) -> Result<(), Error>;

/// customer.require_auth(). Requires Funded. Pays professional in full. Status = Released.
fn release(env, escrow_id: BytesN<32>) -> Result<(), Error>;

/// professional.require_auth(). Requires Funded. Refunds customer in full. Status = Refunded.
fn refund(env, escrow_id: BytesN<32>) -> Result<(), Error>;

/// caller.require_auth(); caller must be the customer or professional. Requires Funded. Status = Disputed.
fn open_dispute(env, escrow_id: BytesN<32>, caller: Address) -> Result<(), Error>;

/// arbiter.require_auth(). Requires Disputed. 0 <= professional_amount <= amount.
/// Pays professional_amount to professional, the rest to customer. Status = Resolved.
fn resolve(env, escrow_id: BytesN<32>, professional_amount: i128) -> Result<(), Error>;

fn get_escrow(env, escrow_id: BytesN<32>) -> Result<Escrow, Error>;   // read-only
fn config(env) -> Config;                                          // admin, arbiter, operator, token

fn set_arbiter(env, new_arbiter: Address) -> Result<(), Error>;   // admin.require_auth()
fn set_operator(env, new_operator: Address) -> Result<(), Error>; // admin.require_auth()
```

**Errors** (`#[contracterror]`): `AlreadyExists`, `NotFound`, `InvalidAmount`, `SameParty`, `InvalidState`, `NotParty`, `InvalidSplit`, `Unauthorized`.

**Events** (topics: `("unifix", name, escrow_id)`): `funded {customer, professional, amount, agreement_hash}`, `released {amount}`, `refunded {amount}`, `disputed {by}`, `resolved {professional_amount, customer_amount}`, plus `arbiter_set` and `operator_set`.

**Implementation rules**

- **Checks, then effects, then interactions.** Update status before calling `token.transfer`. Soroban also forbids re-entrancy.
- Escrow records live in **persistent** storage. Every state-changing call extends TTL to keep live escrows from being archived. Config lives in instance storage.
- No `upgrade` function. No function sends funds to any address other than the stored customer and professional.
- `i128` overflow checks: `overflow-checks = true` in the release profile.

**Invariants (property-tested in Rust)**

- I1: the contract's token balance equals the sum of `amount` over escrows in `Funded` or `Disputed`.
- I2: for terminal escrows, `professional_payout + customer_refund == amount`.
- I3: terminal states (`Released`, `Refunded`, `Resolved`) are final. Every mutating call on them fails with `InvalidState`.
- I4: `release` and `refund` fail when `Disputed`, and `resolve` fails unless `Disputed`.

## 5. Identifiers and the agreement anchor

- `escrow_id = SHA-256("unifix-escrow-v1" ‖ network_passphrase ‖ booking_id ‖ ESCROW_ID_SECRET)`. It is deterministic per booking and unique (DB unique index, plus `AlreadyExists` on-chain). The server secret stops outsiders from deriving IDs to squat on them. Operator co-signing already blocks squatting, so this is a second layer.
- `agreement_hash` is the `agreements.terms_hash` written when the quote was accepted. It ties the on-chain escrow to the exact immutable terms in our database.

## 6. Wallet ownership (SEP-53)

1. `POST /wallets/challenge {address}` checks the StrKey (`G…`, valid checksum) and stores a single-use challenge (five-minute expiry). The message looks like:
   `UniFix wallet verification\nAddress: G…\nUser: <user-id>\nNetwork: Test SDF Network ; September 2015\nNonce: <128-bit hex>\nIssued: <ISO-8601>`
2. The frontend calls Freighter `signMessage(message)`. Freighter signs per SEP-53: ed25519 over `SHA-256("Stellar Signed Message:\n" + message)`.
3. `POST /wallets {address, message, signature}` re-reads the challenge by nonce, checks it matches the user and address, is unused and unexpired, then verifies the signature against the address's public key and marks the challenge used.
4. Network validation: Horizon confirms the account exists on testnet. The response reports whether it has a trustline to the escrow asset, so the UI can prompt the user to add one.
5. Constraint: a verified address belongs to one user. `UNIQUE (network, address) WHERE revoked_at IS NULL`.

**Implementation risk:** the exact signature encoding Freighter returns (`signMessage` → base64 or a buffer) must be confirmed against a **real Freighter-produced fixture** before Issue 5 is closed. Unit tests alone are not enough.

## 7. Payment flows (frontend ↔ backend ↔ chain)

Who does what, for every flow:

| Step | Frontend (Freighter) | Backend | Chain |
|---|---|---|---|
| Prepare | Asks the backend for a transaction | Checks business rules, builds the invoke transaction **with the user's account as source**, simulates it, assembles footprint and fees, co-signs operator auth (fund only), stores `PREPARED` + expected tx hash, returns `unsignedXdr` | — |
| Sign | `signTransaction(unsignedXdr, testnet)` → `signedXdr` | — | — |
| Submit | Posts `signedXdr` | Parses the envelope, checks the network passphrase, checks that the **tx hash equals the prepared hash** (proof the user signed exactly what we built), checks the source-account signature, `sendTransaction`, stores `SUBMITTED`, sets reconciliation to `PENDING_CONFIRMATION` | Transaction enters the queue |
| Confirm | Polls `GET /bookings/{id}` while `PENDING_CONFIRMATION` | Reconciler: `getTransaction` → `SUCCESS`/`FAILED`; on success decodes the contract event **and** calls `get_escrow` to confirm state, parties and amount; commits the booking transition, ledger entry and receipt in one DB transaction | Ledger closes |

Flow-specific rules:

- **Fund** (`POST /bookings/{id}/escrow` then `POST /escrows/{id}/funding`):
  - The caller is the booking's customer; the booking is `PENDING_PAYMENT`.
  - `customer_wallet` is the caller's verified wallet, and the professional has a verified wallet.
  - The amount is the agreement total converted at the locked FX rate (§8).
  - If a still-valid `PREPARED` transaction exists, it is returned again (idempotent). Otherwise a new one is built, for example after a sequence or timebound change.
  - Funding confirmation requires that the on-chain `customer`, `professional`, `amount` and `agreement_hash` **all equal** the escrow row. Any mismatch is flagged `FAILED_VERIFICATION`, raises an admin alert, and never marks the booking funded.
- **Release** (`POST /escrows/{id}/release`, two calls): the customer only; the booking must be `COMPLETION_SUBMITTED` and have no open dispute record. Approval is recorded when the customer requests the unsigned transaction. The booking becomes `COMPLETED` only on confirmation.
- **Refund** (`POST /escrows/{id}/refund`, two calls): the professional only; the booking must be `FUNDED` or `IN_PROGRESS` with no open dispute.
- **Open dispute** (`POST /escrows/{id}/disputes`, two calls): either party. Creating the off-chain dispute record **immediately** blocks the backend from preparing a release or refund. The on-chain lock then blocks everyone else.
- **Resolve** (`POST /disputes/{id}/resolve`, two calls): admin only. The admin's verified wallet must equal the contract's `arbiter`. Outcome `RELEASE` = 100% to professional, `REFUND` = 0%, `SPLIT` = `splitPercentToProfessional`, rounded down to a base unit, with the remainder to the customer.

**Transactions submitted outside our API:** the reconciler's event scan finds them, for example when a customer calls `release` from the Stellar Lab. It applies the same verification and transition rules, and records `actor = chain` in the timeline.

**Failure and retry**

| Situation | Handling |
|---|---|
| User never signs | `PREPARED` expires with the transaction's timebounds (5 min). A new prepare builds a new transaction. Reconciliation shows `AWAITING_SIGNATURE` |
| `sendTransaction` returns `ERROR` / `TRY_AGAIN_LATER` | Stored as `FAILED` with the result code, or retried for `TRY_AGAIN_LATER` up to 3× with backoff. The client can re-prepare |
| Submitted but RPC down | Stays `SUBMITTED`/`PENDING`. The reconciler keeps polling, and the event scan catches it later |
| `getTransaction` `NOT_FOUND` after timebounds + margin | Marked `EXPIRED` (it can never land) and safe to re-prepare |
| Transaction `FAILED` on-chain | Recorded with the result XDR. State is unchanged and the client may retry |
| Reconciler runs twice / crashes midway | Each confirmation is a single DB transaction under row lock, keyed by tx hash (`UNIQUE`). Reprocessing is a no-op |
| RPC event retention exceeded (backend down for days) | Fallback: for every non-terminal escrow, call `get_escrow` and reconcile state directly (`app.cli reconcile --full`) |

**Duplicate-payment prevention:** at most one escrow per booking (`UNIQUE booking_id`). On-chain `AlreadyExists` blocks a second fund for the same `escrow_id`. At most one non-failed transaction per (escrow, kind) (partial unique index). Financial endpoints honour `Idempotency-Key`.

## 8. Asset and amounts

- **Asset:** a classic Stellar asset wrapped by its Stellar Asset Contract. It is configured per environment (`ESCROW_TOKEN_CONTRACT_ID`, `ESCROW_ASSET_CODE`, `ESCROW_ASSET_ISSUER`).
  - Recommended demo asset: **Circle testnet USDC**. Its issuer address is checked against Circle's documentation at implementation time.
  - Automated e2e tests use a **UniFix test asset** whose issuer the harness controls, so test accounts can be funded without a faucet. Each asset has its own contract deployment.
- **Pricing:** quotes are in NGN (or GHS) minor units. At `prepare`, the backend converts with `FX_RATE_<CUR>_PER_<ASSET>` from config. The rate is **locked onto the escrow row** with its source (`configured-testnet`) and timestamp, and returned to the UI as `rate` / `localAmount`. Rounding is up to the next base unit, so the professional is never underpaid. A live FX source is a production decision.
- **Display:** `amount` is a decimal number. `amountUnits` is an exact integer string.

## 9. What the frontend currently assumes and what changes

| Frontend today | Design | Change for Victor |
|---|---|---|
| `openDispute` returns `Dispute` in one call | Dispute lock needs a party signature | Two-step: response includes `unsignedXdr`; sign, then post `{signedXdr}` |
| `resolveDispute` is one call by the admin | The arbiter signs in Freighter | Two-step, like release; the admin wallet must be the arbiter |
| No professional refund action | Professional-initiated refund exists | New `POST /escrows/{id}/refund` flow |
| `EscrowState` lacks `RESOLVED`; `BookingStatus` lacks `REFUNDED`/`RESOLVED` | Needed for split and refund outcomes | Add the enum values |
| `Quote.milestones` with percents | Single-payment escrow | Show milestones as a work plan, not as payment tranches |
| `EscrowTransaction.simulated` | Never `true` in live mode | Remove or ignore |

## 10. Decisions needed (see DEVELOPMENT_PLAN §5)

1. Arbiter custody: human-held Freighter wallet (recommended) versus a backend-held key.
2. Operator co-signature on `fund` (recommended) versus customer-only funding plus backend verification.
3. Demo asset: Circle testnet USDC (recommended) versus XLM.
4. FX: fixed configured rate for testnet (recommended).
5. Platform fee: none for the MVP (recommended).
6. On-chain timeouts: none for the MVP, with disputes covering stalls (recommended), versus an auto-refund after a deadline.
7. Whether the professional may refund during a dispute. Recommended: no; only the arbiter settles disputed escrows.
