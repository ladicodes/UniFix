# UniFix — Stellar Wallets and Soroban Escrow Design

Status: revision 3 (2026-11-17). **Issue 5 implemented and deployed on testnet (§13).** Issues 6 (funding, completion, release, refunds, reconciliation, keeper) and 7 (disputes, arbitration) build on it.

Network: **Stellar testnet** (`Test SDF Network ; September 2015`). Every operation is a real testnet transaction. Nothing is simulated or presented as settled before on-chain confirmation.

Revision 3 (decisions applied):

- No automatic settlement of disputed funds; the escalation and fallback policy is proposed and pending approval (§4.5, P1).
- Voluntary on-chain concessions approved (D17).
- The fixed testnet conversion rate is marked as a demo rate everywhere (§8).

Revision 2 changes:

- Deadline-based cancellation, refund and dispute policy, so no escrow can be locked permanently (§4).
- Party concessions during a dispute (§4.3).
- `submit_completion` moves on-chain (§5).
- A separate `escrow-terms` document binds the escrow to the accepted agreement (§6).
- Fiat and token units are separated (§8).
- The testnet asset configuration was verified against live testnet (§8.1).
- The reconciler's exactly-once design is specified (§10).

---

## 1. Goals and non-goals

**Goals**

1. A single-payment escrow per booking, enforced by a Soroban contract.
2. The contract enforces who may move funds, independently of the backend and the frontend.
3. The backend cannot release, refund or redirect funds by changing data. It holds no key that can choose a recipient or an amount.
4. Double release, refund after release, release after refund, and arbitrary settlement during a dispute are all impossible **on-chain**.
5. **No permanent lock where avoidable.** Every *undisputed* non-terminal state has a path to a terminal state that needs no UniFix key (§4.4). Disputed escrows are settled only by the arbiter or a voluntary concession until a fallback policy is approved (§4.5).
6. The database is a verified mirror of chain state. Each chain event is applied exactly once, including across restarts and multiple instances (§10).

**Non-goals (MVP)**

- Milestone or partial payments (a quote's `milestones` are descriptive work steps only).
- Platform fees.
- Fee sponsorship.
- Mainnet.
- Fiat on/off-ramps.
- Mutual two-signature partial settlements, without the arbiter (proposed as F-D in §4.5, pending approval).

## 2. Actors and keys

| Actor | Key held by | Can do on-chain |
|---|---|---|
| **Customer** | Customer's wallet (Freighter) | `fund` (with operator co-signature), `release`, `extend`, `open_dispute` |
| **Professional** | Professional's wallet | `submit_completion`, `refund`, `open_dispute` |
| **Operator** | Backend (`STELLAR_OPERATOR_SECRET`, env only) | Co-authorize `fund`: attests that the escrow terms are the ones the backend derived from an accepted agreement. As an ordinary fee-paying account it can also call the permissionless `finalize_expired`, whose outcome the contract fixes |
| **Arbiter** | UniFix operations wallet (Freighter, human-held), **not** the backend | `resolve`, only escrows in `Disputed`, only splitting between the two parties |
| **Contract admin** | UniFix operations wallet (multisig before mainnet) | `set_arbiter`, `set_operator`, `set_admin`. It has no access to funds and cannot change any existing escrow's terms or deadlines |
| **Anyone** | — | `finalize_expired` once an **undisputed** deadline has passed. The outcome is fixed by the contract |

## 3. Trust model

1. **Funds can only go to the stored customer or the stored professional.** The contract has no function that pays a third address. This holds for every caller, including the admin, arbiter and operator.
2. **Undisputed escrows are non-custodial.** The customer can pay the professional; the professional can return the funds; deadlines decide the rest. UniFix's keys play no part.
3. **Disputed escrows trust the arbiter**, within limits:
   - The arbiter can act only after a **party** opened the dispute.
   - It splits funds only between the two parties.
   - Either party can concede at any time.
   - There is **no automatic settlement** of disputed funds. If the arbiter does not act, the escalation ladder in §4.5 applies. Its long-stop fallback is not implemented until approved.
4. **The admin can replace the arbiter, operator and admin.** A compromised admin key can therefore decide **disputed** escrows only. It cannot touch undisputed escrows or change deadlines.
5. **A stolen operator key** lets an attacker co-sign new `fund` calls. Each still needs the customer's own signature, and the customer's money still goes only to that customer or professional. The attacker can also trigger deadlines that have already passed, which the contract pays out to the predetermined party anyway. No theft path exists.
6. **The backend is trusted for liveness and display, not custody.** If UniFix disappears:
   - parties can still `release`, `refund` or `open_dispute` with any Stellar tool;
   - anyone can call `finalize_expired` after an undisputed deadline;
   - disputed escrows wait for an arbiter. If the admin and arbiter keys were both lost, those funds would stay locked (§4.4, §4.5);
   - the reconciler catches up from chain events when the backend returns.
7. **Asset issuer risk.** Circle's testnet USDC issuer has `AUTH_REVOCABLE` set, while clawback is disabled (verified 2026-11-17, §8.1). The issuer can freeze balances, including the contract's. This is inherent to regulated stablecoins and is outside our control.
8. **Off-chain facts the contract cannot check:** whether work was done. That is the customer's judgement (release or dispute), the deadlines, or the arbiter's decision.
9. **Not upgradeable.** A new contract version is a new deployment, and existing escrows stay on the old contract.

## 4. Cancellation, refund, dispute and arbitration policy

### 4.1 Deadlines (fixed per escrow at funding, bound in `terms_hash`)

| Deadline | Value | Bounds enforced on-chain |
|---|---|---|
| `refund_after` | Later of (agreed `completion_date` 23:59 Africa/Lagos + `SERVICE_GRACE` [3 days]) or (funding time + 24 h) | `funded_at + 24h ≤ refund_after ≤ funded_at + 180d` |
| `review_window` | 72 h, from `submit_completion` | 24 h – 14 d |

The windows are copied into each escrow record at `fund`. Later admin config changes never affect existing escrows.

### 4.2 On-chain state machine

```
                  fund (customer + operator)
                           │
                           ▼
   ┌──────────────────── Funded ─────────────────────┐
   │  release(customer) → Released                    │
   │  refund(professional) → Refunded                 │
   │  extend(customer, later refund_after)            │
   │  open_dispute(party) [now < refund_after] → Disputed
   │  submit_completion(professional) [now < refund_after] → CompletionSubmitted
   │  finalize_expired(anyone) [now ≥ refund_after] → Refunded (timeout)
   └──────────────────────────────────────────────────┘
   CompletionSubmitted:
      release(customer) → Released
      refund(professional) → Refunded
      open_dispute(party) [now < review_deadline] → Disputed
      finalize_expired(anyone) [now ≥ review_deadline] → Released (auto-release)
   Disputed:
      resolve(arbiter, professional_amount) → Resolved (or Released/Refunded at 100%/0%)
      release(customer)  → Released   (concession: customer accepts professional's position)
      refund(professional) → Refunded (concession: professional accepts customer's position)
      (no timeout exit — finalize_expired fails with InvalidState; see §4.5)
   Released | Refunded | Resolved: terminal, every mutating call fails with InvalidState
```

### 4.3 Policy by booking stage (off-chain UX + on-chain enforcement)

| Stage | Customer wants out | Professional wants out | No one acts |
|---|---|---|---|
| `PENDING_PAYMENT` (no funds) | Cancel → `CANCELLED` | Cancel → `CANCELLED` | Booking expires after 7 days → `CANCELLED` |
| `FUNDED` / `IN_PROGRESS` | *Cancellation request* (off-chain). The professional accepts by signing `refund`, or declines. After a decline, or 48 h without an answer, the customer may open a dispute, or wait for `refund_after` | Signs `refund` → `REFUNDED`. Recorded as a professional cancellation | `refund_after` passes → keeper calls `finalize_expired` → `REFUNDED` |
| `COMPLETION_SUBMITTED` | Opens a dispute within `review_window` | `refund` → `REFUNDED` | `review_deadline` passes → `finalize_expired` → `COMPLETED` (auto-release) |
| `DISPUTED` | Concede (`release`) → `COMPLETED` | Concede (`refund`) → `REFUNDED` | Arbiter resolves under the escalation ladder (§4.5). **No automatic settlement** |

Rules:

- **A professional must submit completion before `refund_after`**, or obtain an extension from the customer (`extend`). After that deadline, the agreed outcome is a refund.
- **Disputes must be opened before the deadline of the current state matures.** Once a deadline has passed, its outcome is final. The concessions are the only settlement actions a party can take during a dispute, and each moves funds **only in the other party's favour**, so neither party can take funds for themselves. This satisfies "disputes block ordinary settlement" while reducing dependence on the arbiter. **D17 is approved:** each concession is authorised on-chain by the conceding party's own wallet (`customer.require_auth()` for `release`, `professional.require_auth()` for `refund`). The backend only prepares the unsigned transaction.
- The arbiter's split: `professional_amount = floor(asset_amount × bps / 10000)`, with the remainder to the customer.
- Notifications warn both parties 24 h before any deadline (Issue 8).

### 4.4 Liveness (avoiding permanent locks)

| State | Exit that needs no UniFix key |
|---|---|
| Funded | `finalize_expired` after `refund_after` (≤ 180 days) |
| CompletionSubmitted | `finalize_expired` after `review_deadline` (≤ 14 days) |
| Disputed | **None in the MVP contract.** Exits are an arbiter decision (the admin can replace an unavailable arbiter) or a voluntary concession by a party. The long-stop fallback awaits policy approval (§4.5) |

Residual risks:

- An issuer freeze (§3.7).
- Ledger-entry archival. Every mutating call extends TTL, and an archived persistent entry can be restored with a `RestoreFootprint` operation. Archival delays access but never destroys an entry.
- **Disputed escrows if both the admin and arbiter keys are lost.** Funds would stay locked. Before any real-value use, mitigate with a 2-of-3 multisig for the admin and arbiter, a documented key-recovery procedure, and the escalation ladder in §4.5.

### 4.5 Dispute escalation and fallback policy — **PROPOSED, PENDING APPROVAL (P1)**

**Decision record (rev 3).** D16a, "refund the whole escrow to the customer when the arbiter fails to act", was **rejected**. Arbiter inaction is UniFix's failure, not evidence about the job, so it must not decide the outcome for either party.

**Nothing in this section that settles funds automatically will be implemented until approved.** The MVP contract has **no** timeout path out of `Disputed`: `finalize_expired` on a disputed escrow fails with `InvalidState`.

**Principles:**

1. A human decision is the normal outcome.
2. No silent default in favour of either party.
3. Any fallback is **explicitly agreed** by both parties before funding: the policy version is part of the agreement and escrow-terms hashes.
4. Liveness comes first from operations (backup arbiters, multisig), not from defaults.

**Proposed escalation ladder** (off-chain process, tracked in `disputes`, visible to both parties):

| Stage | When (from on-chain dispute lock) | What happens |
|---|---|---|
| 1. Evidence | 0–72 h (`evidence_closes_at`) | Both parties submit evidence. Either may concede at any time (D17) |
| 2. Decision | by day 7 (`decision_due_at`) | The primary arbiter decides and records a written rationale, visible to both parties |
| 3. Escalation 1 | day 7, still unresolved | Operations lead alerted; the admin may rotate in a backup arbiter (`set_arbiter`); parties are notified with a new date |
| 4. Escalation 2 | day 14, still unresolved | Two-person review: with an arbiter multisig, two of three signers must approve the split |
| 5. Long-stop | day N (proposed 90), still unresolved | **Only if a fallback option below is approved.** Otherwise funds remain until the arbiter acts |

**Fallback options for decision** (the chosen one applies only to escrows funded on a contract deployment that implements it, because the contract is immutable):

| Option | Rule at long-stop | Pros | Cons |
|---|---|---|---|
| F-A *(MVP default, nothing implemented)* | No automatic settlement | No party is disadvantaged by UniFix's failure | Locked funds if admin and arbiter keys are both lost |
| F-B | 50/50 split | Neutral, simple, easy to explain | Rough justice for both parties |
| F-C | Stage-based: if completion was submitted on-chain before the dispute, 50/50; otherwise a refund minus a declared, pre-agreed call-out fee | Uses on-chain facts | More complex; the call-out fee must be in the agreement |
| F-D | Mutual-settlement only: add `settle_mutual(escrow_id, professional_amount)`, which needs **both** parties' signatures, as a voluntary alternative to the arbiter | Fully voluntary, fits D17 | Not a fallback on its own: both parties must cooperate |

**Recommendation:**

- Keep **F-A** for the testnet MVP.
- Add **F-D** (a voluntary mutual split, which extends the approved concessions) if you approve it before Issue 5's contract is deployed.
- Choose between F-B and F-C before any real-value or mainnet use.
- Whichever is chosen, its identifier (`dispute_policy`) is shown to both parties at quote acceptance and funding, and bound into both hashes (§6).

## 5. Contract interface (`backend/contracts/escrow`)

One deployment holds many escrows, keyed by `escrow_id: BytesN<32>`. One token (Stellar Asset Contract) is fixed at construction, so the contract cannot hold any other asset.

```rust
#[contracttype] pub enum EscrowStatus { Funded, CompletionSubmitted, Disputed, Released, Refunded, Resolved }
#[contracttype] pub enum SettledBy { Customer, Professional, Arbiter, Timeout }

#[contracttype] pub struct Escrow {
    pub customer: Address, pub professional: Address,
    pub amount: i128,                         // token base units
    pub terms_hash: BytesN<32>,               // SHA-256 of the escrow-terms document (§6)
    pub status: EscrowStatus,
    pub funded_at: u64, pub refund_after: u64,
    pub review_window: u64,
    pub review_deadline: Option<u64>, pub disputed_at: Option<u64>,
    pub evidence_hash: Option<BytesN<32>>, pub disputed_by: Option<Address>,
    pub professional_payout: i128, pub customer_refund: i128,
    pub settled_by: Option<SettledBy>,
}

fn __constructor(env, admin, arbiter, operator, token, review_window: u64);
fn fund(env, escrow_id, customer, professional, amount: i128, terms_hash, refund_after: u64) -> Result<(), Error>; // customer + operator auth
fn submit_completion(env, escrow_id, evidence_hash: BytesN<32>) -> Result<(), Error>;                         // professional auth
fn release(env, escrow_id) -> Result<(), Error>;            // customer auth; Funded | CompletionSubmitted | Disputed
fn refund(env, escrow_id) -> Result<(), Error>;             // professional auth; Funded | CompletionSubmitted | Disputed
fn extend(env, escrow_id, new_refund_after: u64) -> Result<(), Error>; // customer auth; Funded; later and ≤ funded_at + 180d
fn open_dispute(env, escrow_id, caller: Address) -> Result<(), Error>; // caller ∈ {customer, professional}, auth; before the current deadline
fn resolve(env, escrow_id, professional_amount: i128) -> Result<(), Error>; // arbiter auth; Disputed; 0 ≤ x ≤ amount
fn finalize_expired(env, escrow_id) -> Result<(), Error>;   // no auth; Funded/CompletionSubmitted only; NotExpired before the deadline; Disputed → InvalidState
fn get_escrow(env, escrow_id) -> Result<Escrow, Error>;
fn config(env) -> Config;
fn set_arbiter(env, a: Address) -> Result<(), Error>;   // admin auth
fn set_operator(env, o: Address) -> Result<(), Error>;  // admin auth
fn set_admin(env, a: Address) -> Result<(), Error>;     // admin auth
```

**Errors:** `AlreadyExists`, `NotFound`, `InvalidAmount`, `SameParty`, `InvalidState`, `NotParty`, `InvalidSplit`, `InvalidDeadline`, `DeadlinePassed`, `NotExpired`.

**Events** (topics `("unifix", name, escrow_id)`): `funded`, `completion_submitted`, `extended`, `disputed`, `released`, `refunded`, `resolved`, `expired`, plus config events. Each terminal event carries `professional_payout`, `customer_refund` and `settled_by`.

**Implementation rules:**

- Update state before calling `token.transfer` (checks, effects, interactions).
- Transfers go only to the stored parties.
- Persistent storage with TTL extension on every write.
- `overflow-checks = true`.
- No `upgrade` function.

**Invariants (randomised property tests):**

- I1: token balance = Σ `amount` over non-terminal escrows.
- I2: for terminal escrows, `professional_payout + customer_refund = amount`.
- I3: terminal states are final.
- I4: `resolve` is valid only in `Disputed`.
- I5: in `Disputed`, the customer can only move funds to the professional and the professional only to the customer.
- I6: no *undisputed* escrow stays non-terminal after its deadline once `finalize_expired` is called, and `finalize_expired` never changes a `Disputed` escrow.

## 6. Binding escrow to the accepted agreement

**Quotes cannot change after acceptance** (enforced in three layers):

1. **API:** there is no endpoint that edits a quote. A revision creates a new version that supersedes the old one.
2. **Database:**
   - A trigger rejects `UPDATE` of any term column on `quotes` at any time. Only `status` and `responded_at` may change, and only from `PENDING`.
   - A trigger rejects `DELETE`.
   - `agreements` is append-only.
3. **Cryptography:** the agreement hash is anchored on-chain through the escrow-terms hash (below).

**Two canonical documents**, each serialised with **RFC 8785 (JSON Canonicalization Scheme)** and hashed with SHA-256. Money is integers, there are no floats, timestamps are RFC 3339 UTC to the second, and every field is required (absent values are explicit `null`).

```jsonc
// 1. agreement (written when the quote is accepted) → agreements.terms_hash = agreement_hash
{ "schema": "unifix.agreement.v1", "agreement_id": "…", "booking_id": "…", "quote_id": "…", "quote_version": 2,
  "conversation_id": "…", "service_request_id": null, "customer_id": "…", "professional_id": "…",
  "title": "…", "description": "…", "labour_minor": 2500000, "materials_minor": 1000000, "total_minor": 3500000,
  "currency": "NGN", "completion_date": "2026-11-20", "service_method": "PRO_TO_CUSTOMER",
  "payment_terms": "…", "milestones": [{"title": "…", "percent": 100}], "dispute_policy": "unifix.dispute-policy.v1",
  "accepted_at": "2026-11-17T10:30:00Z" }

// 2. escrow terms (written at escrow preparation) → passed to fund() as terms_hash
{ "schema": "unifix.escrow-terms.v1", "agreement_hash": "<hex>", "booking_id": "…", "escrow_id": "<hex>",
  "network_passphrase": "Test SDF Network ; September 2015", "escrow_contract_id": "C…",
  "asset": {"code": "USDC", "issuer": "G…", "sac_contract_id": "C…", "decimals": 7},
  "asset_amount": "212121213", "fiat": {"amount_minor": 3500000, "currency": "NGN"},
  "fx": {"rate": "1650.00000000", "base": "USDC", "quote": "NGN", "source": "DEMO_FIXED_RATE", "is_demo_rate": true, "locked_at": "…"},
  "customer_wallet": "G…", "professional_wallet": "G…",
  "refund_after": 1764000000, "review_window": 259200, "dispute_policy": "unifix.dispute-policy.v1" }
```

**Binding chain:** quote (immutable) → agreement JSON → `agreement_hash` → escrow-terms JSON (which includes `agreement_hash`, the token amount, wallets and deadlines) → `terms_hash` → stored on-chain by `fund`, which the operator co-signs.

**Verification at confirmation (Issue 6):** the reconciler reads `get_escrow` and requires the following, or the booking is not funded and the escrow is flagged `FAILED_VERIFICATION`:

- on-chain `customer`, `professional`, `amount`, `refund_after` and `review_window` equal the escrow row;
- on-chain `terms_hash` equals SHA-256(JCS(stored escrow-terms document));
- that document's `agreement_hash` equals the agreement row's hash;
- the agreement row's hash equals SHA-256(JCS(agreement document)).

**Independent verification:** `GET /bookings/{id}/agreement` returns both canonical documents as exact strings, with their hashes. Either party can recompute them and compare with the contract state on stellar.expert.

**Escrow ID:** `escrow_id = HMAC-SHA256(ESCROW_ID_SECRET, "unifix-escrow-v1|" + network_passphrase + "|" + booking_id)`. It is deterministic per booking, and it is unique (DB unique index, plus on-chain `AlreadyExists`).

## 7. Wallet ownership (SEP-53)

1. `POST /wallets/challenge {address}` validates the StrKey checksum and stores a single-use challenge (5-minute expiry). The message is `UniFix wallet verification\nAddress: G…\nUser: <id>\nNetwork: Test SDF Network ; September 2015\nNonce: <128-bit hex>\nIssued: <RFC3339>`.
2. Freighter `signMessage` signs ed25519 over `SHA-256("Stellar Signed Message:\n" + message)` (SEP-53).
3. `POST /wallets {address, message, signature}`: the server consumes the challenge atomically, then verifies the signature with the address's key.
4. Horizon check: the account exists on testnet; the response reports `has_escrow_trustline` for the configured asset.
5. A verified address belongs to one user: `UNIQUE (network, address) WHERE revoked_at IS NULL`.

**Must be verified before Issue 5 closes:** the exact signature encoding against a **real Freighter-produced fixture**.

## 8. Units, assets and conversion

**Fiat accounting units** (agreements, quotes, bookings):

- integer **minor units** with an ISO 4217 code: `amount_minor: 3500000`, `currency: "NGN"` (NGN and GHS have exponent 2);
- stored as `bigint`; never floats.

**Token units** (escrow, chain transactions, ledger, receipts):

- integer **base units** of a specific asset;
- stored as `numeric(39,0)`, which fits `i128`;
- serialised in JSON as a **decimal string**, because it can exceed JavaScript's safe-integer range: `asset_amount: "212121213"`;
- always accompanied by an explicit asset object `{code, issuer, sac_contract_id, decimals}`, or the canonical SEP-11 string `USDC:G…`.

**Network fees:** integer stroops of XLM, as a string: `fee_stroops: "104321"`.

**Conversion** (exact integer math, done once at escrow preparation and locked onto the escrow):

```
asset_amount = ceil( amount_minor × 10^asset.decimals / (rate × 10^currency_exponent) )
  rate = fiat major units per 1 whole asset unit, a decimal string with ≤ 8 places (e.g. "1650.00000000")
  example: ₦35,000.00 → 3,500,000 × 10^7 / (1650 × 10^2) = 212,121,212.12… → 212,121,213 base units (21.2121213 USDC)
```

- Rounding is **up**, so the professional is never underpaid by rounding.
- Computed with Python `Decimal` at sufficient precision, then converted to `int`. A unit test with boundary vectors checks it.
- **Demo rate (D14, approved).** On testnet the rate is a fixed configured value (`FX_DEMO_RATE_USDC_NGN`).
  - It is labelled `source = DEMO_FIXED_RATE` and `is_demo_rate = true`. Both values are part of the escrow-terms hash, every API response that carries a converted amount, and every receipt.
  - The frontend must show **"Demo rate — testnet only"** wherever it shows the rate or a converted amount.
  - The service refuses to start with a demo rate on any network other than testnet.
  - A production FX source is a separate, future decision.

### 8.1 Verified testnet asset configuration (checked 2026-11-17)

| Item | Value | How verified |
|---|---|---|
| Asset | `USDC` | Circle docs, "USDC contract addresses", Testnet table, row "Stellar Testnet": `USDC-GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` |
| Issuer | `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` | Horizon testnet `/accounts/…`: `home_domain = centre.io` |
| SAC contract ID | `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` | Computed with stellar-sdk 17.0.1 `Asset.contract_id(testnet)`; matches Horizon `/assets` `contract_id`; instance ledger entry exists via Soroban RPC `getLedgerEntries` |
| Decimals | 7 | All classic Stellar assets |
| Issuer flags | `auth_required=false`, `auth_revocable=true`, `auth_clawback_enabled=false` | Horizon `/assets` |
| Soroban RPC | `https://soroban-testnet.stellar.org`, healthy, retention window 120,960 ledgers (~7 days) | `getHealth` |
| Horizon | `https://horizon-testnet.stellar.org` | — |
| Mainnet issuer (reference only) | `GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN` | Circle docs, Mainnet table |
| Getting testnet USDC | **Not documented on Circle's addresses page.** Circle runs a public faucet, but it was not verified for this plan; check at Issue 5 | — |

- **Startup check (Issue 5):** the service refuses to start unless `ESCROW_TOKEN_CONTRACT_ID` equals `Asset(code, issuer).contract_id(passphrase)` and the instance exists on the configured network.
- **E2E test asset:** a UniFix-issued test asset, whose issuer key is generated per test run and never persisted, wrapped in its own SAC, with its own escrow deployment. This lets the test harness mint balances without a faucet. Its configuration is derived and checked the same way.

## 9. Payment flows (frontend ↔ backend ↔ chain)

| Step | Frontend (Freighter) | Backend | Chain |
|---|---|---|---|
| Prepare | Requests a transaction | Checks business rules; builds the invoke with **the user's account as source**; simulates; assembles; operator auth-entry signature (`fund` only); stores `PREPARED` with the expected tx hash; returns `unsigned_xdr` | — |
| Sign | `signTransaction(unsigned_xdr, testnet)` | — | — |
| Submit | Posts `signed_xdr` | Parses; checks the network passphrase; **signed tx hash must equal the prepared hash**; checks the source signature; `sendTransaction`; `SUBMITTED` → `PENDING_CONFIRMATION` | Transaction queued |
| Confirm | Polls `GET /bookings/{id}` | Reconciler applies the events exactly once (§10) | Ledger closes |

| Action | Signer | Route (prepare, then submit) | Booking result |
|---|---|---|---|
| Fund | customer | `POST /bookings/{id}/escrow` → `POST /escrows/{id}/funding` | `FUNDED` |
| Submit completion | professional | `POST /bookings/{id}/completion` (evidence → `unsigned_xdr`) → `POST /bookings/{id}/completion/submit` | `COMPLETION_SUBMITTED` |
| Release / concede | customer | `POST /escrows/{id}/release` ×2 | `COMPLETED` |
| Refund / concede | professional | `POST /escrows/{id}/refund` ×2 | `REFUNDED` |
| Extend deadline | customer | `POST /escrows/{id}/extend` ×2 | unchanged |
| Open dispute | party | `POST /escrows/{id}/disputes` → `POST /disputes/{id}/lock` | `DISPUTED` |
| Resolve | arbiter (admin) | `POST /disputes/{id}/resolve` ×2 | `COMPLETED` / `REFUNDED` / `RESOLVED` |
| Expiry | keeper (operator account as fee payer) or anyone | internal | `REFUNDED` / `COMPLETED` |

**Keeper.** Part of the reconciler loop. When a deadline has passed, it submits `finalize_expired` with the operator account as source and fee payer. It can only trigger outcomes the contract has already fixed. Policy (D16b): it auto-finalizes both **undisputed** timeout types (refund after `refund_after`; auto-release after `review_deadline`) 15 minutes after maturity. It never touches disputed escrows.

**Failure handling:**

| Situation | Handling |
|---|---|
| Never signed | `PREPARED` expires with the tx timebounds (5 min); the client re-prepares |
| `TRY_AGAIN_LATER` | Retry up to 3× with backoff |
| `ERROR` | `FAILED` with the result code |
| RPC down after submit | Stays `SUBMITTED`; the reconciler resolves it later |
| `NOT_FOUND` after timebounds + 2 ledgers | `EXPIRED`; can never land; safe to re-prepare |
| On-chain failure | Recorded with the result XDR; state unchanged |
| Transaction made outside our API | Found by the event scan and applied with `actor = CHAIN` |

**Duplicate-payment prevention:**

- one escrow per booking;
- on-chain `AlreadyExists`;
- one in-flight transaction per (escrow, kind);
- `Idempotency-Key` on every 💰 route;
- exactly-once event application (§10).

## 10. Reconciler: exactly-once processing, restarts, multiple instances

**Principle:** delivery is at least once and application is idempotent, so the effect is exactly once. All reconciler state lives in PostgreSQL; nothing that matters is held in memory.

**Single path for every chain effect.** Our own submitted transactions and the contract event scan both feed the same steps:

1. **Ingest.** When `getTransaction` reports `SUCCESS`, the events are taken from the transaction meta. The event scan uses `getEvents` filtered by contract ID from the cursor. Both insert into `chain_events` with `INSERT … ON CONFLICT (tx_hash, event_index) DO NOTHING`. Only rows actually inserted (`RETURNING`) proceed.
2. **Apply** `apply_chain_event(event_id)`, in one DB transaction:
   - a. `SELECT … FOR UPDATE` the `chain_events` row (`status = INGESTED`), the escrow row and the booking row.
   - b. Read `get_escrow` from RPC, which is authoritative current state, and verify the terms (§6).
   - c. Compute the transition. If the escrow is already in that state or later, mark the event `APPLIED_NOOP`. If the event contradicts the chain's current state, mark it `CONFLICT` and raise an admin alert. A state never regresses.
   - d. Write the booking transition, escrow state, `ledger_entries` (`UNIQUE (tx_hash, type)`), receipt (`UNIQUE (escrow_id, kind)`), timeline, audit, and `chain_transactions.status = CONFIRMED`.
   - e. Mark the event `APPLIED` and commit.

A crash before commit rolls everything back, and the event is retried. A crash after commit leaves it `APPLIED`, and the retry is a no-op.
3. **Cursor.** `chain_sync_state.last_ledger` / `cursor` advance **in the same transaction** as the ingest of that page of events. After a restart the scan resumes from the last committed cursor. Re-reading a page is harmless because of the unique key.
4. **Ordering.** Events for one escrow are applied in `(ledger, tx_index, event_index)` order: the loop picks the oldest `INGESTED` event per escrow. The state check in 2c makes out-of-order arrival safe anyway.

**Multiple instances and workers:**

- Every API process starts a reconciler task. Each tick, it tries `pg_try_advisory_lock(RECONCILER_LOCK_ID)` on a **dedicated, direct (non-pooled) connection** held for as long as it leads.
- Only the leader polls, scans and runs the keeper. If the leader dies, PostgreSQL drops its session and the lock, and another instance takes over on its next tick (≤ 5 s).
- Session-level advisory locks do not work through PgBouncer in transaction-pooling mode. The leader connection must bypass the pooler, and the deployment guide states this.
- **The lock is an efficiency measure, not the correctness mechanism.** If two leaders ever overlapped (for example during a network partition), the row locks and unique constraints in steps 1–2 would still apply each event once.
- API request handlers may check `getTransaction` once synchronously after submit (fast path). They call the same `apply_chain_event`, so a request handler racing the reconciler is safe.

**Restart behaviour:**

- `SUBMITTED`/`PENDING` transactions are reloaded from the DB and polled again.
- Rows past their timebounds + margin with `NOT_FOUND` become `EXPIRED`.
- `INGESTED` events not yet applied are applied.
- Keeper candidates are recomputed from the escrow deadlines.

**Keeper deduplication:** before submitting `finalize_expired`, the keeper inserts a `chain_transactions` row of kind `FINALIZE`. The partial unique index (one in-flight per escrow and kind) rejects a second row. A duplicate that still reached the chain fails with `InvalidState` and changes nothing.

**RPC retention gap.** RPC keeps about 7 days of events. If the cursor is older than `getHealth.oldest_ledger`, the reconciler runs a **full sweep**: `get_escrow` for every non-terminal escrow, applying any differences as synthetic `STATE_SYNC` events with the same idempotent apply. It then resets the cursor to `oldest_ledger`. The same sweep is available as `app.cli reconcile --full`.

**Observability:** `GET /admin/ops/status` reports the leader instance ID, cursor lag in ledgers, the oldest pending transaction age, the count of `CONFLICT`/`FAILED_VERIFICATION` items and the last error.

## 11. Frontend impact

Listed for Victor in [API_CONTRACT.md §13](API_CONTRACT.md#13-frontend-integration-changes). The escrow-related items are F12–F15 and F22–F25.

## 12. Decisions (see DEVELOPMENT_PLAN §5)

- **Approved:** D14 (fixed testnet rate, labelled as a demo rate); D17 (voluntary concessions with wallet authorization).
- **Rejected:** D16a (automatic full refund on arbiter inaction). Replaced by proposal **P1** (§4.5), pending approval, with nothing implemented.
- **Open, with recommendations:** D11 arbiter custody (human-held wallet; multisig before real value); D12 operator co-signature on `fund`; D13 asset (Circle testnet USDC, verified); D15 no fee; D16b keeper auto-finalizes undisputed timeouts; D16c windows (3-day service grace, 72 h review); P1 dispute fallback (F-A for the MVP, F-D optional, F-B or F-C before real value).

Post-MVP: multisig admin and arbiter; live FX.

## 13. Testnet deployment and verification (Issue 5, 2026-11-17)

Deployed with `uv run python -m scripts.testnet deploy` (throwaway Friendbot-funded keys; the record and keys stay in the gitignored `var/testnet/deployment.json`).

| Deployment | Contract ID | Token | Purpose |
|---|---|---|---|
| `usdc` | `CD5ARDVPAQ26SL7BZHLOKAG2T4CBAAQN47Y2QEPX2KEGSJZYAX2JQVHG` | Circle testnet USDC (`CBIELTK6…DAMA`) | Frontend demos; startup asset check passes against it |
| `test` | `CCW6AN4HJEY4W3ETAJKBRE5CIARWW6SAN4D3QOBKA6GBD35RU3RY5U7P` | UniFix test asset `UFXT` (mintable) | Automated E2E |
| `short` | `CD65GZ4AH23Y7QZPCISGPP7EGXCEHYV6JZOYLOCPDWSRGGEC3XAX7HLI` | `UFXT` | **Test-only `short-windows` build** (deadline bounds in minutes) for real-time timeout paths |

- Wasm SHA-256: production `39fa48c797795dc67915fbfdfd0b407aa8287d4e5d2f92863c1744dac209d45e`; short-windows `ea8e80018628f52a26be2a3a1b946f6d6a6ba215fcce67cfb1836e9ae872ad64`. soroban-sdk 29.0.1, `wasm32v1-none`.
- The admin and arbiter of these testnet deployments are throwaway keys. Before any real value they must be human-held (D11) and multisig (§4.4).
- **P1:** F-A applies (no automatic settlement of disputed funds); F-D was not approved, so `settle_mutual` is not in this contract.

**Smoke run** (`uv run python -m scripts.testnet smoke`), which drives the backend's own `RpcGateway` (simulate → operator auth-entry signing → assemble → submit → confirm → `getEvents` decode):

| Step | Transaction |
|---|---|
| Fund (operator auth entry signed by the backend adapter) | [`f74f47e11de0…`](https://stellar.expert/explorer/testnet/tx/f74f47e11de0fc8a643d9c10a5001c7acd2eaaeaffdbb97ddeecce6efe3eb377) |
| submit_completion | [`902a3667ad99…`](https://stellar.expert/explorer/testnet/tx/902a3667ad992db2a753d695a57c69e6452a7f8382708cb8970a3c4f69e81479) |
| release (customer) | [`11032a8be0c5…`](https://stellar.expert/explorer/testnet/tx/11032a8be0c59d526bb49859677a8cba27b96f033eb04b05fb12b96792562ec4) |
| fund → refund (professional) | [`dd292356ff52…`](https://stellar.expert/explorer/testnet/tx/dd292356ff52f3bc5ce416d722fcc561502f88fc7009b814dd8fa241e6d0eb5c) |
| open_dispute (customer) | [`735157c7e69c…`](https://stellar.expert/explorer/testnet/tx/735157c7e69cec5da07098d4894d27422568d3b427a1d7b471778102e9fbba35) |
| resolve, 30 % to the professional | [`67e820d78069…`](https://stellar.expert/explorer/testnet/tx/67e820d780691b65e50e1e0daa08f83a4d7239f00a9450fe0276b2f08bed0abe) |
| open_dispute (professional) | [`76871081ba19…`](https://stellar.expert/explorer/testnet/tx/76871081ba198012da51608f3f1a542eaf04da86ccf680d4e09937da52db1941) |
| customer concedes (release while disputed) | [`e9b7d6d96b47…`](https://stellar.expert/explorer/testnet/tx/e9b7d6d96b47b51139b5a991f38340f0fcd1a65d1ca5614b756577345a8e78a4) |
| finalize_expired → timeout refund (short-windows build) | [`ff337fe90312…`](https://stellar.expert/explorer/testnet/tx/ff337fe90312a99fbafdbb51fa707e5914ca970388b23aeab7a9b0f7e83937bc) |
| finalize_expired → auto-release (short-windows build) | [`ffed24c5d572…`](https://stellar.expert/explorer/testnet/tx/ffed24c5d5727202d1b20a8252ea18c8ad7c0faab152fce8edaff0f4e2dc94ad) |

Refused on-chain during simulation, as required: a second `release` (`InvalidState`), `resolve` on an undisputed escrow (`InvalidState`), `finalize_expired` on a disputed escrow (`InvalidState`), and `finalize_expired` before the deadline (`NotExpired`).

**Implementation notes:**

- `settled_by` is a plain enum with an `Unsettled` variant (contract enums cannot nest in `Option` in the SDK's XDR conversions). The API maps `Unsettled` to `null`.
- `finalize_expired` emits one `expired` event (with the resulting `status`) rather than `released`/`refunded`.
- Chain events are keyed by `(tx_hash, event_index)` where `event_index` comes from the RPC event ID. Both ingestion paths (transaction confirmation and the cursor scan) read events through `getEvents`, so the key is identical (§10).
- SEP-53 verification passes the published SEP-53 test vector and generated keys. **Still to do before Issue 5 closes:** a signature captured from a real Freighter wallet (it needs a browser wallet, which this environment does not have).

## 14. Issue 6: payments through the API on testnet (2026-11-18)

`UNIFIX_TESTNET=1 uv run pytest -m testnet` drives the HTTP API with the real RPC gateway and reconciler against the `test` and `short` deployments (3 passed):

| Step | Transaction |
|---|---|
| Happy path: fund (operator co-signed, through `POST /bookings/{id}/escrow` → `/escrows/{id}/funding`) | [`ce3161a8fdde…`](https://stellar.expert/explorer/testnet/tx/ce3161a8fdde28be7474c12320e4410fcd50a5e2a22a70387878e1944d717776) |
| Happy path: submit_completion (professional-signed evidence hash) | [`66d107ed1de6…`](https://stellar.expert/explorer/testnet/tx/66d107ed1de6f1c4232c4c8e1e789ef14f7d0d29e2f9317be729452f09fc60a9) |
| Happy path: release (customer approval) → `COMPLETED`, receipts FUNDING + RELEASE | [`6186dbcb8d74…`](https://stellar.expert/explorer/testnet/tx/6186dbcb8d744843c693e7d48dfd95650cbda7d907a7fcac27817f6eabf9cc7e) |
| Refund path: fund | [`1566ff6e3a64…`](https://stellar.expert/explorer/testnet/tx/1566ff6e3a64a45c0fa549b775da297a87bf39842ccd6dbc04e7ed41ee4bce77) |
| Refund path: professional refund → `REFUNDED` | [`43106756a182…`](https://stellar.expert/explorer/testnet/tx/43106756a182357c961ca057dfc1d8f373e17a0e50715dda85d919298a2adbc0) |
| Keeper path (`short` deployment): fund | [`04c17c82eea9…`](https://stellar.expert/explorer/testnet/tx/04c17c82eea934e35043d88f9d94c89681afb1a9bce0741f2ddf93a4e6c205b8) |
| Keeper path: submit_completion | [`d9785c005326…`](https://stellar.expert/explorer/testnet/tx/d9785c005326dfd7cd6498d9d59840d2c3ed6546f62a3457b593b8d64aedf785) |
| Keeper path: `finalize_expired` submitted by the keeper after the review window → `COMPLETED` (auto-release) | [`cc6a6be88472…`](https://stellar.expert/explorer/testnet/tx/cc6a6be88472fb372a11baba449f8c61bea775e730b089b474dcdb605a3699da) |

For each run the tests also check that the on-chain `terms_hash` equals the `terms_hash` returned by `GET /bookings/{id}/agreement`, and that every receipt has `is_demo_rate: true`.

**Implementation notes (Issue 6):**

- Every chain action is prepare → sign → submit. Prepared transactions are stored with their hash; a submitted envelope must hash to the prepared one. The signed envelope is stored before sending, so an RPC outage or a crash after commit is resent by the reconciler (`SUBMITTED` → `PENDING` → `CONFIRMED`/`FAILED`/`EXPIRED`).
- The transaction-result path reads the confirmed ledger's events through `getEvents`, like the cursor scan, so both produce the same `(tx_hash, event_index)` key.
- A retention gap is detected from `getHealth` before calling `getEvents` (a real RPC rejects a stale cursor); the full sweep then synthesises `STATE_SYNC` events from `get_escrow`.
- The booking table gains chain-only `FUNDED`/`IN_PROGRESS` → `COMPLETED`, because the contract lets a customer release before completion is submitted (for example from another wallet). The API itself only offers release after completion is submitted.
- D16b implemented: the keeper finalises undisputed deadlines `KEEPER_DELAY_SECONDS` (default 15 min) after maturity, with the operator account as source; the in-flight unique index makes a second keeper's attempt a no-op. D21 implemented: a professional may refund at any time before settlement.
- `ESCROW_DEADLINE_UNIT_SECONDS` must match the contract build (86400; 60 only for the short-windows test build, refused in production). With 60, `refund_after` is one hour after preparation.
- Funding a booking whose payment window has expired is prevented while a funding transaction is in flight (the booking can neither be cancelled nor expire). If funds still arrive for a cancelled booking (for example funded from another tool), the event is marked `CONFLICT` and audited; the customer's money stays protected by the on-chain deadline refund.
