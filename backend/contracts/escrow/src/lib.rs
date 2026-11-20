//! UniFix escrow: one single-payment escrow per booking, between a customer and a professional.
//!
//! Trust model (STELLAR_ESCROW_DESIGN §3): funds only ever move to the stored customer or the
//! stored professional. Undisputed escrows always have a deadline exit (`finalize_expired`);
//! disputed escrows are settled only by the arbiter or by a party conceding toward the other
//! party. There is no upgrade path and no automatic settlement of disputed funds.
#![no_std]

use soroban_sdk::{
    contract, contracterror, contractevent, contractimpl, contracttype, panic_with_error, token, Address,
    BytesN, Env,
};

pub const HOUR: u64 = 3_600;
pub const DAY: u64 = 24 * HOUR;
/// The unit of the on-chain deadline bounds. The `short-windows` feature (a separate,
/// test-only build used by the testnet smoke run) shrinks it to one minute so timeout paths can
/// be exercised in real time. Production builds never enable it.
#[cfg(not(feature = "short-windows"))]
const BOUND_DAY: u64 = DAY;
#[cfg(feature = "short-windows")]
const BOUND_DAY: u64 = 60;
/// `funded_at + MIN_REFUND_DELAY <= refund_after <= funded_at + MAX_REFUND_DELAY`.
pub const MIN_REFUND_DELAY: u64 = BOUND_DAY;
pub const MAX_REFUND_DELAY: u64 = 180 * BOUND_DAY;
pub const MIN_REVIEW_WINDOW: u64 = BOUND_DAY;
pub const MAX_REVIEW_WINDOW: u64 = 14 * BOUND_DAY;
/// Re-extend an entry's TTL when fewer than this many ledgers remain (~1 day at 5 s/ledger).
const TTL_HEADROOM: u32 = 17_280;

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    AlreadyExists = 1,
    NotFound = 2,
    InvalidAmount = 3,
    SameParty = 4,
    InvalidState = 5,
    NotParty = 6,
    InvalidSplit = 7,
    InvalidDeadline = 8,
    DeadlinePassed = 9,
    NotExpired = 10,
}

#[contracttype]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum EscrowStatus {
    Funded,
    CompletionSubmitted,
    Disputed,
    Released,
    Refunded,
    Resolved,
}

impl EscrowStatus {
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Released | Self::Refunded | Self::Resolved)
    }
}

#[contracttype]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum SettledBy {
    /// Not yet settled. (A plain enum rather than `Option`, which contract enums cannot nest in.)
    Unsettled,
    Customer,
    Professional,
    Arbiter,
    Timeout,
}

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Escrow {
    pub customer: Address,
    pub professional: Address,
    /// Token base units.
    pub amount: i128,
    /// SHA-256 of the canonical escrow-terms document (STELLAR_ESCROW_DESIGN §6).
    pub terms_hash: BytesN<32>,
    pub status: EscrowStatus,
    pub funded_at: u64,
    pub refund_after: u64,
    /// Copied from the configuration at funding; later config changes never affect it.
    pub review_window: u64,
    pub review_deadline: Option<u64>,
    pub disputed_at: Option<u64>,
    pub evidence_hash: Option<BytesN<32>>,
    pub disputed_by: Option<Address>,
    pub professional_payout: i128,
    pub customer_refund: i128,
    pub settled_by: SettledBy,
}

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    pub admin: Address,
    pub arbiter: Address,
    pub operator: Address,
    pub token: Address,
    pub review_window: u64,
}

#[contracttype]
#[derive(Clone)]
enum DataKey {
    Config,
    Escrow(BytesN<32>),
}

// --- Events: topics ("unifix", <name>, escrow_id) -------------------------------------------

#[contractevent(topics = ["unifix", "funded"])]
pub struct Funded {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub customer: Address,
    pub professional: Address,
    pub amount: i128,
    pub terms_hash: BytesN<32>,
    pub refund_after: u64,
    pub review_window: u64,
}

#[contractevent(topics = ["unifix", "completion_submitted"])]
pub struct CompletionSubmitted {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub evidence_hash: BytesN<32>,
    pub review_deadline: u64,
}

#[contractevent(topics = ["unifix", "extended"])]
pub struct Extended {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub refund_after: u64,
}

#[contractevent(topics = ["unifix", "disputed"])]
pub struct Disputed {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub disputed_by: Address,
    pub disputed_at: u64,
}

/// Every terminal event carries the final split and who settled it.
#[contractevent(topics = ["unifix", "released"])]
pub struct Released {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub professional_payout: i128,
    pub customer_refund: i128,
    pub settled_by: SettledBy,
}

#[contractevent(topics = ["unifix", "refunded"])]
pub struct Refunded {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub professional_payout: i128,
    pub customer_refund: i128,
    pub settled_by: SettledBy,
}

#[contractevent(topics = ["unifix", "resolved"])]
pub struct Resolved {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub professional_payout: i128,
    pub customer_refund: i128,
    pub settled_by: SettledBy,
}

/// A deadline exit; `status` is `Released` (auto-release) or `Refunded` (timeout refund).
#[contractevent(topics = ["unifix", "expired"])]
pub struct Expired {
    #[topic]
    pub escrow_id: BytesN<32>,
    pub status: EscrowStatus,
    pub professional_payout: i128,
    pub customer_refund: i128,
    pub settled_by: SettledBy,
}

#[contractevent(topics = ["unifix", "arbiter_set"])]
pub struct ArbiterSet {
    pub arbiter: Address,
}

#[contractevent(topics = ["unifix", "operator_set"])]
pub struct OperatorSet {
    pub operator: Address,
}

#[contractevent(topics = ["unifix", "admin_set"])]
pub struct AdminSet {
    pub admin: Address,
}

#[contract]
pub struct EscrowContract;

#[contractimpl]
impl EscrowContract {
    pub fn __constructor(
        env: Env,
        admin: Address,
        arbiter: Address,
        operator: Address,
        token: Address,
        review_window: u64,
    ) {
        if !(MIN_REVIEW_WINDOW..=MAX_REVIEW_WINDOW).contains(&review_window) {
            panic_with_error!(&env, Error::InvalidDeadline);
        }
        let config = Config { admin, arbiter, operator, token, review_window };
        env.storage().instance().set(&DataKey::Config, &config);
        bump_instance(&env);
    }

    /// Locks `amount` from the customer. Needs the customer's and the operator's authorization:
    /// the operator attests that the terms were derived from an accepted agreement.
    pub fn fund(
        env: Env,
        escrow_id: BytesN<32>,
        customer: Address,
        professional: Address,
        amount: i128,
        terms_hash: BytesN<32>,
        refund_after: u64,
    ) -> Result<(), Error> {
        let config = load_config(&env);
        customer.require_auth();
        config.operator.require_auth();
        let key = DataKey::Escrow(escrow_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if customer == professional {
            return Err(Error::SameParty);
        }
        let now = env.ledger().timestamp();
        if refund_after < now + MIN_REFUND_DELAY || refund_after > now + MAX_REFUND_DELAY {
            return Err(Error::InvalidDeadline);
        }
        let escrow = Escrow {
            customer: customer.clone(),
            professional: professional.clone(),
            amount,
            terms_hash: terms_hash.clone(),
            status: EscrowStatus::Funded,
            funded_at: now,
            refund_after,
            review_window: config.review_window,
            review_deadline: None,
            disputed_at: None,
            evidence_hash: None,
            disputed_by: None,
            professional_payout: 0,
            customer_refund: 0,
            settled_by: SettledBy::Unsettled,
        };
        save(&env, &escrow_id, &escrow);
        token::Client::new(&env, &config.token).transfer(&customer, env.current_contract_address(), &amount);
        Funded {
            escrow_id,
            customer,
            professional,
            amount,
            terms_hash,
            refund_after,
            review_window: config.review_window,
        }
        .publish(&env);
        Ok(())
    }

    /// The professional declares the work done, which starts the customer's review window.
    pub fn submit_completion(env: Env, escrow_id: BytesN<32>, evidence_hash: BytesN<32>) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        escrow.professional.require_auth();
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        let now = env.ledger().timestamp();
        if now >= escrow.refund_after {
            return Err(Error::DeadlinePassed);
        }
        let review_deadline = now + escrow.review_window;
        escrow.status = EscrowStatus::CompletionSubmitted;
        escrow.review_deadline = Some(review_deadline);
        escrow.evidence_hash = Some(evidence_hash.clone());
        save(&env, &escrow_id, &escrow);
        CompletionSubmitted { escrow_id, evidence_hash, review_deadline }.publish(&env);
        Ok(())
    }

    /// The customer pays the professional (approval, or a concession while disputed).
    pub fn release(env: Env, escrow_id: BytesN<32>) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        escrow.customer.require_auth();
        require_open(&escrow)?;
        let amount = escrow.amount;
        settle(&env, &escrow_id, &mut escrow, EscrowStatus::Released, amount, SettledBy::Customer);
        Released {
            escrow_id,
            professional_payout: amount,
            customer_refund: 0,
            settled_by: SettledBy::Customer,
        }
        .publish(&env);
        Ok(())
    }

    /// The professional returns the funds (cancellation, or a concession while disputed).
    pub fn refund(env: Env, escrow_id: BytesN<32>) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        escrow.professional.require_auth();
        require_open(&escrow)?;
        settle(&env, &escrow_id, &mut escrow, EscrowStatus::Refunded, 0, SettledBy::Professional);
        Refunded {
            escrow_id,
            professional_payout: 0,
            customer_refund: escrow.amount,
            settled_by: SettledBy::Professional,
        }
        .publish(&env);
        Ok(())
    }

    /// The customer gives the professional more time before the timeout refund.
    pub fn extend(env: Env, escrow_id: BytesN<32>, new_refund_after: u64) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        escrow.customer.require_auth();
        if escrow.status != EscrowStatus::Funded {
            return Err(Error::InvalidState);
        }
        if env.ledger().timestamp() >= escrow.refund_after {
            return Err(Error::DeadlinePassed);
        }
        if new_refund_after <= escrow.refund_after || new_refund_after > escrow.funded_at + MAX_REFUND_DELAY {
            return Err(Error::InvalidDeadline);
        }
        escrow.refund_after = new_refund_after;
        save(&env, &escrow_id, &escrow);
        Extended { escrow_id, refund_after: new_refund_after }.publish(&env);
        Ok(())
    }

    /// Either party locks the escrow for arbitration, before the current state's deadline.
    pub fn open_dispute(env: Env, escrow_id: BytesN<32>, caller: Address) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        caller.require_auth();
        if caller != escrow.customer && caller != escrow.professional {
            return Err(Error::NotParty);
        }
        let deadline = match (escrow.status, escrow.review_deadline) {
            (EscrowStatus::Funded, _) => escrow.refund_after,
            (EscrowStatus::CompletionSubmitted, Some(review_deadline)) => review_deadline,
            _ => return Err(Error::InvalidState),
        };
        let now = env.ledger().timestamp();
        if now >= deadline {
            return Err(Error::DeadlinePassed);
        }
        escrow.status = EscrowStatus::Disputed;
        escrow.disputed_at = Some(now);
        escrow.disputed_by = Some(caller.clone());
        save(&env, &escrow_id, &escrow);
        Disputed { escrow_id, disputed_by: caller, disputed_at: now }.publish(&env);
        Ok(())
    }

    /// The arbiter splits a disputed escrow between the two parties.
    pub fn resolve(env: Env, escrow_id: BytesN<32>, professional_amount: i128) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        load_config(&env).arbiter.require_auth();
        if escrow.status != EscrowStatus::Disputed {
            return Err(Error::InvalidState);
        }
        if professional_amount < 0 || professional_amount > escrow.amount {
            return Err(Error::InvalidSplit);
        }
        let status = if professional_amount == escrow.amount {
            EscrowStatus::Released
        } else if professional_amount == 0 {
            EscrowStatus::Refunded
        } else {
            EscrowStatus::Resolved
        };
        settle(&env, &escrow_id, &mut escrow, status, professional_amount, SettledBy::Arbiter);
        Resolved {
            escrow_id,
            professional_payout: escrow.professional_payout,
            customer_refund: escrow.customer_refund,
            settled_by: SettledBy::Arbiter,
        }
        .publish(&env);
        Ok(())
    }

    /// Permissionless deadline exit for undisputed escrows. The outcome is fixed by the contract:
    /// a refund once `refund_after` passes in Funded, or an auto-release once `review_deadline`
    /// passes in CompletionSubmitted. Disputed and terminal escrows fail with `InvalidState`.
    pub fn finalize_expired(env: Env, escrow_id: BytesN<32>) -> Result<(), Error> {
        let mut escrow = load(&env, &escrow_id)?;
        let now = env.ledger().timestamp();
        let (deadline, status, payout) = match (escrow.status, escrow.review_deadline) {
            (EscrowStatus::Funded, _) => (escrow.refund_after, EscrowStatus::Refunded, 0),
            (EscrowStatus::CompletionSubmitted, Some(review_deadline)) => {
                (review_deadline, EscrowStatus::Released, escrow.amount)
            }
            _ => return Err(Error::InvalidState),
        };
        if now < deadline {
            return Err(Error::NotExpired);
        }
        settle(&env, &escrow_id, &mut escrow, status, payout, SettledBy::Timeout);
        Expired {
            escrow_id,
            status,
            professional_payout: escrow.professional_payout,
            customer_refund: escrow.customer_refund,
            settled_by: SettledBy::Timeout,
        }
        .publish(&env);
        Ok(())
    }

    pub fn get_escrow(env: Env, escrow_id: BytesN<32>) -> Result<Escrow, Error> {
        load(&env, &escrow_id)
    }

    pub fn config(env: Env) -> Config {
        load_config(&env)
    }

    pub fn set_arbiter(env: Env, arbiter: Address) {
        let mut config = admin_config(&env);
        config.arbiter = arbiter.clone();
        store_config(&env, &config);
        ArbiterSet { arbiter }.publish(&env);
    }

    pub fn set_operator(env: Env, operator: Address) {
        let mut config = admin_config(&env);
        config.operator = operator.clone();
        store_config(&env, &config);
        OperatorSet { operator }.publish(&env);
    }

    pub fn set_admin(env: Env, admin: Address) {
        let mut config = admin_config(&env);
        config.admin = admin.clone();
        store_config(&env, &config);
        AdminSet { admin }.publish(&env);
    }
}

fn require_open(escrow: &Escrow) -> Result<(), Error> {
    match escrow.status {
        EscrowStatus::Funded | EscrowStatus::CompletionSubmitted | EscrowStatus::Disputed => Ok(()),
        _ => Err(Error::InvalidState),
    }
}

/// Records the terminal state first, then pays the stored parties (checks, effects, interactions).
fn settle(
    env: &Env,
    escrow_id: &BytesN<32>,
    escrow: &mut Escrow,
    status: EscrowStatus,
    professional_payout: i128,
    settled_by: SettledBy,
) {
    let customer_refund = escrow.amount - professional_payout;
    escrow.status = status;
    escrow.professional_payout = professional_payout;
    escrow.customer_refund = customer_refund;
    escrow.settled_by = settled_by;
    save(env, escrow_id, escrow);
    let token = token::Client::new(env, &load_config(env).token);
    let contract = env.current_contract_address();
    if professional_payout > 0 {
        token.transfer(&contract, &escrow.professional, &professional_payout);
    }
    if customer_refund > 0 {
        token.transfer(&contract, &escrow.customer, &customer_refund);
    }
}

fn load(env: &Env, escrow_id: &BytesN<32>) -> Result<Escrow, Error> {
    bump_instance(env);
    env.storage().persistent().get(&DataKey::Escrow(escrow_id.clone())).ok_or(Error::NotFound)
}

fn save(env: &Env, escrow_id: &BytesN<32>, escrow: &Escrow) {
    let key = DataKey::Escrow(escrow_id.clone());
    let storage = env.storage().persistent();
    storage.set(&key, escrow);
    let max = env.storage().max_ttl();
    storage.extend_ttl(&key, max.saturating_sub(TTL_HEADROOM), max);
}

fn load_config(env: &Env) -> Config {
    env.storage().instance().get(&DataKey::Config).expect("constructed")
}

fn admin_config(env: &Env) -> Config {
    let config = load_config(env);
    config.admin.require_auth();
    config
}

fn store_config(env: &Env, config: &Config) {
    env.storage().instance().set(&DataKey::Config, config);
    bump_instance(env);
}

fn bump_instance(env: &Env) {
    let max = env.storage().max_ttl();
    env.storage().instance().extend_ttl(max.saturating_sub(TTL_HEADROOM), max);
}

#[cfg(all(test, not(feature = "short-windows")))]
mod test;
