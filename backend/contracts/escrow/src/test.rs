extern crate std;

use soroban_sdk::testutils::{Address as _, Events as _, Ledger, MockAuth, MockAuthInvoke};
use soroban_sdk::{token, Address, BytesN, Env, Event, IntoVal, Val, Vec};

use crate::*;

const REVIEW: u64 = 72 * HOUR;
const START: u64 = 1_800_000_000;
const AMOUNT: i128 = 212_121_213;

struct Setup {
    env: Env,
    client: EscrowContractClient<'static>,
    token: token::Client<'static>,
    admin: Address,
    arbiter: Address,
    operator: Address,
    customer: Address,
    professional: Address,
}

impl Setup {
    fn new() -> Self {
        let env = Env::default();
        env.mock_all_auths();
        env.ledger().set_timestamp(START);
        let issuer = Address::generate(&env);
        let sac = env.register_stellar_asset_contract_v2(issuer);
        let (admin, arbiter, operator) = (Address::generate(&env), Address::generate(&env), Address::generate(&env));
        let id = env.register(
            EscrowContract,
            (admin.clone(), arbiter.clone(), operator.clone(), sac.address(), REVIEW),
        );
        let client = EscrowContractClient::new(&env, &id);
        let token = token::Client::new(&env, &sac.address());
        let (customer, professional) = (Address::generate(&env), Address::generate(&env));
        let setup = Setup { env, client, token, admin, arbiter, operator, customer, professional };
        setup.mint(&setup.customer, 10 * AMOUNT);
        setup
    }

    fn mint(&self, to: &Address, amount: i128) {
        token::StellarAssetClient::new(&self.env, &self.token.address).mint(to, &amount);
    }

    fn id(&self, n: u8) -> BytesN<32> {
        BytesN::from_array(&self.env, &[n; 32])
    }

    fn terms(&self) -> BytesN<32> {
        BytesN::from_array(&self.env, &[0xAB; 32])
    }

    fn fund(&self, n: u8) -> BytesN<32> {
        let id = self.id(n);
        self.client.fund(&id, &self.customer, &self.professional, &AMOUNT, &self.terms(), &(self.now() + 7 * DAY));
        id
    }

    fn now(&self) -> u64 {
        self.env.ledger().timestamp()
    }

    fn advance(&self, seconds: u64) {
        self.env.ledger().set_timestamp(self.now() + seconds);
    }

    fn escrow(&self, id: &BytesN<32>) -> Escrow {
        self.client.get_escrow(id)
    }

    fn balance(&self, who: &Address) -> i128 {
        self.token.balance(who)
    }

    fn last_event(&self) -> soroban_sdk::xdr::ContractEvent {
        let events = self.env.events().all().filter_by_contract(&self.client.address);
        events.events().last().expect("an event").clone()
    }

    /// Only `signer` authorizes this call (everything else must fail authorization).
    fn only<A: IntoVal<Env, Vec<Val>>>(&self, signer: &Address, fn_name: &'static str, args: A) {
        self.env.mock_auths(&[MockAuth {
            address: signer,
            invoke: &MockAuthInvoke {
                contract: &self.client.address,
                fn_name,
                args: args.into_val(&self.env),
                sub_invokes: &[],
            },
        }]);
    }
}

fn contract_error<T: core::fmt::Debug, C: core::fmt::Debug>(
    result: Result<Result<T, C>, Result<Error, soroban_sdk::InvokeError>>,
) -> Error {
    match result {
        Err(Ok(error)) => error,
        other => panic!("expected a contract error, got {other:?}"),
    }
}

/// A host-level (authorization) failure rather than a contract error.
fn is_auth_failure<T: core::fmt::Debug, C: core::fmt::Debug>(
    result: Result<Result<T, C>, Result<Error, soroban_sdk::InvokeError>>,
) -> bool {
    matches!(result, Err(Err(_)))
}

/// Admin functions have no contract error type, so any host failure is an authorization failure.
fn admin_rejected<T, C>(result: Result<Result<T, C>, Result<soroban_sdk::Error, soroban_sdk::InvokeError>>) -> bool {
    result.is_err()
}

// --- construction and configuration ----------------------------------------------------------

#[test]
fn constructor_stores_config_and_bounds_review_window() {
    let s = Setup::new();
    let config = s.client.config();
    assert_eq!(config.admin, s.admin);
    assert_eq!(config.arbiter, s.arbiter);
    assert_eq!(config.operator, s.operator);
    assert_eq!(config.token, s.token.address);
    assert_eq!(config.review_window, REVIEW);
}

#[test]
#[should_panic]
fn constructor_rejects_short_review_window() {
    let env = Env::default();
    let a = Address::generate(&env);
    env.register(EscrowContract, (a.clone(), a.clone(), a.clone(), a, DAY - 1));
}

#[test]
#[should_panic]
fn constructor_rejects_long_review_window() {
    let env = Env::default();
    let a = Address::generate(&env);
    env.register(EscrowContract, (a.clone(), a.clone(), a.clone(), a, 14 * DAY + 1));
}

#[test]
fn admin_rotates_arbiter_operator_and_admin() {
    let s = Setup::new();
    let (arbiter, operator, admin) = (Address::generate(&s.env), Address::generate(&s.env), Address::generate(&s.env));
    s.client.set_arbiter(&arbiter);
    assert_eq!(s.last_event(), ArbiterSet { arbiter: arbiter.clone() }.to_xdr(&s.env, &s.client.address));
    s.client.set_operator(&operator);
    s.client.set_admin(&admin);
    let config = s.client.config();
    assert_eq!((config.arbiter, config.operator, config.admin), (arbiter.clone(), operator, admin.clone()));

    // The old admin lost its powers; the new one has them.
    s.only(&s.admin, "set_arbiter", (s.arbiter.clone(),));
    assert!(admin_rejected(s.client.try_set_arbiter(&s.arbiter)));
    s.only(&admin, "set_arbiter", (s.arbiter.clone(),));
    s.client.set_arbiter(&s.arbiter);
    assert_eq!(s.client.config().arbiter, s.arbiter);
}

#[test]
fn only_admin_changes_config() {
    let s = Setup::new();
    let other = Address::generate(&s.env);
    for signer in [&s.arbiter, &s.operator, &s.customer] {
        s.only(signer, "set_arbiter", (other.clone(),));
        assert!(admin_rejected(s.client.try_set_arbiter(&other)));
        s.only(signer, "set_operator", (other.clone(),));
        assert!(admin_rejected(s.client.try_set_operator(&other)));
        s.only(signer, "set_admin", (other.clone(),));
        assert!(admin_rejected(s.client.try_set_admin(&other)));
    }
    assert_eq!(s.client.config().admin, s.admin);
}

#[test]
fn rotated_arbiter_settles_and_old_one_cannot() {
    let s = Setup::new();
    let id = s.fund(1);
    s.client.open_dispute(&id, &s.customer);
    let backup = Address::generate(&s.env);
    s.client.set_arbiter(&backup);
    s.only(&s.arbiter, "resolve", (id.clone(), 1_i128));
    assert!(is_auth_failure(s.client.try_resolve(&id, &1)));
    s.only(&backup, "resolve", (id.clone(), 1_i128));
    s.client.resolve(&id, &1);
    assert_eq!(s.escrow(&id).status, EscrowStatus::Resolved);
}

// --- fund -------------------------------------------------------------------------------------

#[test]
fn fund_locks_tokens_and_records_terms() {
    let s = Setup::new();
    let before = s.balance(&s.customer);
    let id = s.fund(1);
    let event = s.last_event();
    let escrow = s.escrow(&id);
    assert_eq!(escrow.status, EscrowStatus::Funded);
    assert_eq!((escrow.customer.clone(), escrow.professional.clone()), (s.customer.clone(), s.professional.clone()));
    assert_eq!(escrow.amount, AMOUNT);
    assert_eq!(escrow.terms_hash, s.terms());
    assert_eq!((escrow.funded_at, escrow.refund_after, escrow.review_window), (START, START + 7 * DAY, REVIEW));
    assert_eq!(s.balance(&s.client.address), AMOUNT);
    assert_eq!(s.balance(&s.customer), before - AMOUNT);
    assert_eq!(
        event,
        Funded {
            escrow_id: id,
            customer: s.customer.clone(),
            professional: s.professional.clone(),
            amount: AMOUNT,
            terms_hash: s.terms(),
            refund_after: START + 7 * DAY,
            review_window: REVIEW,
        }
        .to_xdr(&s.env, &s.client.address)
    );
}

#[test]
fn fund_requires_customer_and_operator_auth() {
    let s = Setup::new();
    let id = s.id(1);
    s.client.fund(&id, &s.customer, &s.professional, &AMOUNT, &s.terms(), &(START + 7 * DAY));
    let auths: std::vec::Vec<Address> = s.env.auths().into_iter().map(|(who, _)| who).collect();
    assert!(auths.contains(&s.customer) && auths.contains(&s.operator) && auths.len() == 2);

    let args = (s.id(2), s.customer.clone(), s.professional.clone(), AMOUNT, s.terms(), START + 7 * DAY);
    for signer in [&s.customer, &s.operator, &s.professional, &s.admin] {
        s.only(signer, "fund", args.clone());
        assert!(is_auth_failure(s.client.try_fund(&s.id(2), &s.customer, &s.professional, &AMOUNT, &s.terms(), &(START + 7 * DAY))));
    }
}

#[test]
fn fund_rejects_invalid_input() {
    let s = Setup::new();
    let id = s.fund(1);
    let ok = START + 7 * DAY;
    let fund = |id: &BytesN<32>, professional: &Address, amount: i128, refund_after: u64| {
        contract_error(s.client.try_fund(id, &s.customer, professional, &amount, &s.terms(), &refund_after))
    };
    assert_eq!(fund(&id, &s.professional, AMOUNT, ok), Error::AlreadyExists);
    assert_eq!(fund(&s.id(2), &s.professional, 0, ok), Error::InvalidAmount);
    assert_eq!(fund(&s.id(2), &s.professional, -5, ok), Error::InvalidAmount);
    assert_eq!(fund(&s.id(2), &s.customer, AMOUNT, ok), Error::SameParty);
    assert_eq!(fund(&s.id(2), &s.professional, AMOUNT, START + DAY - 1), Error::InvalidDeadline);
    assert_eq!(fund(&s.id(2), &s.professional, AMOUNT, START + 180 * DAY + 1), Error::InvalidDeadline);
    // Bounds are inclusive.
    s.client.fund(&s.id(3), &s.customer, &s.professional, &AMOUNT, &s.terms(), &(START + DAY));
    s.client.fund(&s.id(4), &s.customer, &s.professional, &AMOUNT, &s.terms(), &(START + 180 * DAY));
}

#[test]
fn fund_fails_without_balance() {
    let s = Setup::new();
    let poor = Address::generate(&s.env);
    let result = s.client.try_fund(&s.id(1), &poor, &s.professional, &AMOUNT, &s.terms(), &(START + 7 * DAY));
    assert!(result.is_err());
    assert_eq!(contract_error(s.client.try_get_escrow(&s.id(1))), Error::NotFound);
}

#[test]
fn config_changes_do_not_affect_existing_escrows() {
    let s = Setup::new();
    let id = s.fund(1);
    // A new operator cannot be used to retroactively change anything; windows stay copied.
    s.client.set_operator(&Address::generate(&s.env));
    s.client.submit_completion(&id, &s.terms());
    assert_eq!(s.escrow(&id).review_deadline, Some(START + REVIEW));
}

// --- submit_completion -------------------------------------------------------------------------

#[test]
fn submit_completion_starts_review_window() {
    let s = Setup::new();
    let id = s.fund(1);
    s.advance(HOUR);
    let evidence = BytesN::from_array(&s.env, &[7; 32]);
    s.client.submit_completion(&id, &evidence);
    let event = s.last_event();
    let escrow = s.escrow(&id);
    assert_eq!(escrow.status, EscrowStatus::CompletionSubmitted);
    assert_eq!(escrow.review_deadline, Some(START + HOUR + REVIEW));
    assert_eq!(escrow.evidence_hash, Some(evidence.clone()));
    assert_eq!(
        event,
        CompletionSubmitted { escrow_id: id.clone(), evidence_hash: evidence.clone(), review_deadline: START + HOUR + REVIEW }
            .to_xdr(&s.env, &s.client.address)
    );
    assert_eq!(contract_error(s.client.try_submit_completion(&id, &evidence)), Error::InvalidState);
}

#[test]
fn submit_completion_needs_professional_and_deadline() {
    let s = Setup::new();
    let id = s.fund(1);
    let evidence = s.terms();
    for signer in [&s.customer, &s.operator, &s.arbiter] {
        s.only(signer, "submit_completion", (id.clone(), evidence.clone()));
        assert!(is_auth_failure(s.client.try_submit_completion(&id, &evidence)));
    }
    s.env.mock_all_auths();
    s.advance(7 * DAY);
    assert_eq!(contract_error(s.client.try_submit_completion(&id, &evidence)), Error::DeadlinePassed);
    assert_eq!(contract_error(s.client.try_submit_completion(&s.id(9), &evidence)), Error::NotFound);
}

// --- release / refund --------------------------------------------------------------------------

#[test]
fn customer_releases_from_funded_and_completion_submitted() {
    let s = Setup::new();
    let mut last = None;
    let a = s.fund(1);
    let b = s.fund(2);
    s.client.submit_completion(&b, &s.terms());
    for id in [&a, &b] {
        s.client.release(id);
        last = Some(s.last_event());
        let escrow = s.escrow(id);
        assert_eq!(escrow.status, EscrowStatus::Released);
        assert_eq!((escrow.professional_payout, escrow.customer_refund), (AMOUNT, 0));
        assert_eq!(escrow.settled_by, SettledBy::Customer);
    }
    assert_eq!(
        last.clone().unwrap(),
        Released { escrow_id: b, professional_payout: AMOUNT, customer_refund: 0, settled_by: SettledBy::Customer }
            .to_xdr(&s.env, &s.client.address)
    );
    assert_eq!(s.balance(&s.professional), 2 * AMOUNT);
    assert_eq!(s.balance(&s.client.address), 0);
}

#[test]
fn professional_refunds_from_every_open_state() {
    let s = Setup::new();
    let mut last = None;
    let start = s.balance(&s.customer);
    let a = s.fund(1);
    let b = s.fund(2);
    s.client.submit_completion(&b, &s.terms());
    for id in [&a, &b] {
        s.client.refund(id);
        last = Some(s.last_event());
        let escrow = s.escrow(id);
        assert_eq!(escrow.status, EscrowStatus::Refunded);
        assert_eq!((escrow.professional_payout, escrow.customer_refund), (0, AMOUNT));
        assert_eq!(escrow.settled_by, SettledBy::Professional);
    }
    assert_eq!(
        last.clone().unwrap(),
        Refunded { escrow_id: b, professional_payout: 0, customer_refund: AMOUNT, settled_by: SettledBy::Professional }
            .to_xdr(&s.env, &s.client.address)
    );
    assert_eq!(s.balance(&s.customer), start);
}

#[test]
fn release_and_refund_need_the_right_party() {
    let s = Setup::new();
    let id = s.fund(1);
    for signer in [&s.professional, &s.operator, &s.arbiter, &s.admin] {
        s.only(signer, "release", (id.clone(),));
        assert!(is_auth_failure(s.client.try_release(&id)));
    }
    for signer in [&s.customer, &s.operator, &s.arbiter, &s.admin] {
        s.only(signer, "refund", (id.clone(),));
        assert!(is_auth_failure(s.client.try_refund(&id)));
    }
    s.env.mock_all_auths();
    assert_eq!(s.escrow(&id).status, EscrowStatus::Funded);
}

#[test]
fn terminal_states_are_final() {
    let s = Setup::new();
    let released = s.fund(1);
    s.client.release(&released);
    let refunded = s.fund(2);
    s.client.refund(&refunded);
    let resolved = s.fund(3);
    s.client.open_dispute(&resolved, &s.customer);
    s.client.resolve(&resolved, &5);
    s.advance(200 * DAY);
    for id in [&released, &refunded, &resolved] {
        let before = s.escrow(id);
        assert_eq!(contract_error(s.client.try_release(id)), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_refund(id)), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_resolve(id, &1)), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_open_dispute(id, &s.customer)), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_submit_completion(id, &s.terms())), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_extend(id, &(START + 10 * DAY))), Error::InvalidState);
        assert_eq!(contract_error(s.client.try_finalize_expired(id)), Error::InvalidState);
        assert_eq!(s.escrow(id), before);
    }
}

// --- extend ----------------------------------------------------------------------------------

#[test]
fn customer_extends_within_bounds() {
    let s = Setup::new();
    let id = s.fund(1);
    s.client.extend(&id, &(START + 30 * DAY));
    let event = s.last_event();
    assert_eq!(s.escrow(&id).refund_after, START + 30 * DAY);
    assert_eq!(
        event,
        Extended { escrow_id: id.clone(), refund_after: START + 30 * DAY }.to_xdr(&s.env, &s.client.address)
    );
    assert_eq!(contract_error(s.client.try_extend(&id, &(START + 30 * DAY))), Error::InvalidDeadline);
    assert_eq!(contract_error(s.client.try_extend(&id, &(START + 181 * DAY))), Error::InvalidDeadline);
    s.client.extend(&id, &(START + 180 * DAY));

    s.only(&s.professional, "extend", (id.clone(), START + 180 * DAY));
    assert!(is_auth_failure(s.client.try_extend(&id, &(START + 180 * DAY))));
}

#[test]
fn extend_only_in_funded_before_deadline() {
    let s = Setup::new();
    let id = s.fund(1);
    s.client.submit_completion(&id, &s.terms());
    assert_eq!(contract_error(s.client.try_extend(&id, &(START + 30 * DAY))), Error::InvalidState);
    let late = s.fund(2);
    s.advance(7 * DAY);
    assert_eq!(contract_error(s.client.try_extend(&late, &(START + 30 * DAY))), Error::DeadlinePassed);
}

// --- disputes, concessions and arbitration ----------------------------------------------------

#[test]
fn either_party_opens_a_dispute_before_the_deadline() {
    let s = Setup::new();
    let a = s.fund(1);
    s.advance(HOUR);
    s.client.open_dispute(&a, &s.customer);
    let event = s.last_event();
    let escrow = s.escrow(&a);
    assert_eq!(escrow.status, EscrowStatus::Disputed);
    assert_eq!((escrow.disputed_at, escrow.disputed_by), (Some(START + HOUR), Some(s.customer.clone())));
    assert_eq!(
        event,
        Disputed { escrow_id: a.clone(), disputed_by: s.customer.clone(), disputed_at: START + HOUR }
            .to_xdr(&s.env, &s.client.address)
    );
    let b = s.fund(2);
    s.client.submit_completion(&b, &s.terms());
    s.client.open_dispute(&b, &s.professional);
    assert_eq!(s.escrow(&b).disputed_by, Some(s.professional.clone()));
    assert_eq!(contract_error(s.client.try_open_dispute(&b, &s.customer)), Error::InvalidState);
}

#[test]
fn dispute_rules() {
    let s = Setup::new();
    let id = s.fund(1);
    let stranger = Address::generate(&s.env);
    assert_eq!(contract_error(s.client.try_open_dispute(&id, &stranger)), Error::NotParty);
    assert_eq!(contract_error(s.client.try_open_dispute(&id, &s.arbiter)), Error::NotParty);
    // The caller must sign for themselves.
    s.only(&s.professional, "open_dispute", (id.clone(), s.customer.clone()));
    assert!(is_auth_failure(s.client.try_open_dispute(&id, &s.customer)));
    s.env.mock_all_auths();
    // Funded: before refund_after only.
    s.advance(7 * DAY);
    assert_eq!(contract_error(s.client.try_open_dispute(&id, &s.customer)), Error::DeadlinePassed);
    // CompletionSubmitted: before review_deadline only.
    let late = s.fund(2);
    s.client.submit_completion(&late, &s.terms());
    s.advance(REVIEW);
    assert_eq!(contract_error(s.client.try_open_dispute(&late, &s.customer)), Error::DeadlinePassed);
}

#[test]
fn concessions_only_favour_the_other_party() {
    let s = Setup::new();
    let start = s.balance(&s.customer);
    let a = s.fund(1);
    s.client.open_dispute(&a, &s.professional);
    // The customer cannot refund themselves; the professional cannot release to themselves.
    s.only(&s.customer, "refund", (a.clone(),));
    assert!(is_auth_failure(s.client.try_refund(&a)));
    s.only(&s.professional, "release", (a.clone(),));
    assert!(is_auth_failure(s.client.try_release(&a)));
    // The customer concedes: the professional is paid.
    s.only(&s.customer, "release", (a.clone(),));
    s.client.release(&a);
    assert_eq!(s.balance(&s.professional), AMOUNT);

    s.env.mock_all_auths();
    let b = s.fund(2);
    s.client.open_dispute(&b, &s.customer);
    s.only(&s.professional, "refund", (b.clone(),));
    s.client.refund(&b);
    assert_eq!(s.escrow(&b).settled_by, SettledBy::Professional);
    assert_eq!(s.balance(&s.customer), start - AMOUNT);
}

#[test]
fn arbiter_resolves_disputes_with_any_split() {
    let s = Setup::new();
    let cases = [(AMOUNT, EscrowStatus::Released), (0, EscrowStatus::Refunded), (AMOUNT / 3, EscrowStatus::Resolved)];
    for (n, (payout, status)) in cases.iter().enumerate() {
        let id = s.fund(n as u8 + 1);
        s.client.open_dispute(&id, &s.customer);
        let (pro_before, customer_before) = (s.balance(&s.professional), s.balance(&s.customer));
        s.only(&s.arbiter, "resolve", (id.clone(), *payout));
        s.client.resolve(&id, payout);
        let event = s.last_event();
        s.env.mock_all_auths();
        let escrow = s.escrow(&id);
        assert_eq!(escrow.status, *status);
        assert_eq!((escrow.professional_payout, escrow.customer_refund), (*payout, AMOUNT - payout));
        assert_eq!(escrow.settled_by, SettledBy::Arbiter);
        assert_eq!(s.balance(&s.professional) - pro_before, *payout);
        assert_eq!(s.balance(&s.customer) - customer_before, AMOUNT - payout);
        assert_eq!(
            event,
            Resolved {
                escrow_id: id,
                professional_payout: *payout,
                customer_refund: AMOUNT - payout,
                settled_by: SettledBy::Arbiter
            }
            .to_xdr(&s.env, &s.client.address)
        );
    }
}

#[test]
fn resolve_rules() {
    let s = Setup::new();
    let id = s.fund(1);
    assert_eq!(contract_error(s.client.try_resolve(&id, &1)), Error::InvalidState);
    s.client.submit_completion(&id, &s.terms());
    assert_eq!(contract_error(s.client.try_resolve(&id, &1)), Error::InvalidState);
    s.client.open_dispute(&id, &s.customer);
    assert_eq!(contract_error(s.client.try_resolve(&id, &-1)), Error::InvalidSplit);
    assert_eq!(contract_error(s.client.try_resolve(&id, &(AMOUNT + 1))), Error::InvalidSplit);
    for signer in [&s.admin, &s.operator, &s.customer, &s.professional] {
        s.only(signer, "resolve", (id.clone(), 1_i128));
        assert!(is_auth_failure(s.client.try_resolve(&id, &1)));
    }
}

// --- finalize_expired --------------------------------------------------------------------------

#[test]
fn finalize_expired_refunds_after_refund_after() {
    let s = Setup::new();
    let start = s.balance(&s.customer);
    let id = s.fund(1);
    s.advance(7 * DAY - 1);
    assert_eq!(contract_error(s.client.try_finalize_expired(&id)), Error::NotExpired);
    s.advance(1);
    s.env.set_auths(&[]); // permissionless: no authorization at all
    s.client.finalize_expired(&id);
    let event = s.last_event();
    let escrow = s.escrow(&id);
    assert_eq!(escrow.status, EscrowStatus::Refunded);
    assert_eq!(escrow.settled_by, SettledBy::Timeout);
    assert_eq!(s.balance(&s.customer), start);
    assert_eq!(
        event,
        Expired {
            escrow_id: id,
            status: EscrowStatus::Refunded,
            professional_payout: 0,
            customer_refund: AMOUNT,
            settled_by: SettledBy::Timeout
        }
        .to_xdr(&s.env, &s.client.address)
    );
}

#[test]
fn finalize_expired_auto_releases_after_review_deadline() {
    let s = Setup::new();
    let id = s.fund(1);
    s.client.submit_completion(&id, &s.terms());
    s.advance(REVIEW - 1);
    assert_eq!(contract_error(s.client.try_finalize_expired(&id)), Error::NotExpired);
    s.advance(1);
    s.client.finalize_expired(&id);
    let escrow = s.escrow(&id);
    assert_eq!((escrow.status, escrow.settled_by), (EscrowStatus::Released, SettledBy::Timeout));
    assert_eq!(s.balance(&s.professional), AMOUNT);
}

#[test]
fn finalize_expired_never_settles_a_dispute() {
    let s = Setup::new();
    let id = s.fund(1);
    s.client.open_dispute(&id, &s.customer);
    for jump in [0, 7 * DAY, 400 * DAY] {
        s.advance(jump);
        assert_eq!(contract_error(s.client.try_finalize_expired(&id)), Error::InvalidState);
        assert_eq!(s.escrow(&id).status, EscrowStatus::Disputed);
    }
    assert_eq!(s.balance(&s.client.address), AMOUNT);
}

#[test]
fn unknown_escrow_is_not_found() {
    let s = Setup::new();
    let id = s.id(42);
    assert_eq!(contract_error(s.client.try_get_escrow(&id)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_release(&id)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_refund(&id)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_finalize_expired(&id)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_open_dispute(&id, &s.customer)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_resolve(&id, &0)), Error::NotFound);
    assert_eq!(contract_error(s.client.try_extend(&id, &START)), Error::NotFound);
}

// --- invariants under randomised operation sequences (I1–I6) ------------------------------------

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        // xorshift64*: deterministic, so failures are reproducible from the seed.
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

#[test]
fn invariants_hold_under_random_operations() {
    let settled: usize = (1..=40_u64).map(run_random_sequence).sum();
    assert!(settled > 100, "the random walk must actually settle escrows ({settled})");
}

fn run_random_sequence(seed: u64) -> usize {
    let mut settled = 0;
    let s = Setup::new();
    let mut rng = Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15));
    let ids: std::vec::Vec<BytesN<32>> = (1..=6).map(|n| s.id(n)).collect();
    for _ in 0..120 {
        let id = &ids[rng.below(ids.len() as u64) as usize];
        let before = s.client.try_get_escrow(id).ok().map(|r| r.unwrap());
        let (pro_before, customer_before) = (s.balance(&s.professional), s.balance(&s.customer));
        let op = rng.below(9);
        let ok = match op {
            0 => {
                let amount = 1 + rng.below(1_000_000) as i128;
                let refund_after = s.now() + DAY + rng.below(30 * DAY);
                s.client.try_fund(id, &s.customer, &s.professional, &amount, &s.terms(), &refund_after).is_ok()
            }
            1 => s.client.try_submit_completion(id, &s.terms()).is_ok(),
            2 => s.client.try_release(id).is_ok(),
            3 => s.client.try_refund(id).is_ok(),
            4 => s.client.try_extend(id, &(s.now() + DAY + rng.below(60 * DAY))).is_ok(),
            5 => {
                let caller = if rng.below(2) == 0 { &s.customer } else { &s.professional };
                s.client.try_open_dispute(id, caller).is_ok()
            }
            6 => {
                let max = before.as_ref().map_or(1, |e| e.amount);
                s.client.try_resolve(id, &(rng.below(max as u64 + 1) as i128)).is_ok()
            }
            7 => s.client.try_finalize_expired(id).is_ok(),
            _ => {
                s.advance(rng.below(10 * DAY));
                false
            }
        };
        let after = s.client.try_get_escrow(id).ok().map(|r| r.unwrap());
        if let (Some(before), Some(after)) = (&before, &after) {
            // I3: terminal states are final.
            if before.status.is_terminal() {
                assert_eq!(before, after, "seed {seed}: terminal escrow changed");
            }
            // I4: resolve succeeds only on a disputed escrow.
            if op == 6 && ok {
                assert_eq!(before.status, EscrowStatus::Disputed, "seed {seed}");
            }
            // I5/I6: a disputed escrow settles only via arbiter or a concession toward the other party.
            if before.status == EscrowStatus::Disputed && after.status.is_terminal() {
                match after.settled_by {
                    SettledBy::Customer => assert_eq!(after.professional_payout, after.amount),
                    SettledBy::Professional => assert_eq!(after.customer_refund, after.amount),
                    SettledBy::Arbiter => {}
                    other => panic!("seed {seed}: disputed escrow settled by {other:?}"),
                }
            }
            if !before.status.is_terminal() && after.status.is_terminal() {
                settled += 1;
                // Payments go only to the stored parties, exactly as recorded.
                assert_eq!(s.balance(&s.professional) - pro_before, after.professional_payout, "seed {seed}");
                assert_eq!(s.balance(&s.customer) - customer_before, after.customer_refund, "seed {seed}");
            }
        }
        check_global_invariants(&s, &ids, seed);
    }
    // I6: every undisputed open escrow can be finalized after its deadline; disputed ones cannot.
    s.advance(400 * DAY);
    for id in &ids {
        if let Ok(Ok(escrow)) = s.client.try_get_escrow(id) {
            let result = s.client.try_finalize_expired(id);
            match escrow.status {
                EscrowStatus::Funded | EscrowStatus::CompletionSubmitted => {
                    assert!(result.is_ok(), "seed {seed}");
                    assert!(s.escrow(id).status.is_terminal());
                }
                _ => {
                    assert_eq!(contract_error(result), Error::InvalidState, "seed {seed}");
                    assert_eq!(s.escrow(id), escrow);
                }
            }
        }
    }
    check_global_invariants(&s, &ids, seed);
    settled
}

fn check_global_invariants(s: &Setup, ids: &[BytesN<32>], seed: u64) {
    let mut locked = 0_i128;
    for id in ids {
        if let Ok(Ok(escrow)) = s.client.try_get_escrow(id) {
            if escrow.status.is_terminal() {
                // I2: terminal escrows are fully paid out.
                assert_eq!(escrow.professional_payout + escrow.customer_refund, escrow.amount, "seed {seed}");
                assert_ne!(escrow.settled_by, SettledBy::Unsettled);
            } else {
                locked += escrow.amount;
            }
        }
    }
    // I1: the contract holds exactly the open escrows' amounts.
    assert_eq!(s.balance(&s.client.address), locked, "seed {seed}");
}
