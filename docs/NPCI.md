# NPCI / UPI AutoPay rules MandateMend encodes

This is the regulatory surface the policy engine enforces. Sources: NPCI UPI AutoPay
circulars (OC 60 "Recurring payments via UPI", OC 82 on the AFA-exemption limit), the RBI
e-mandate framework (RBI/2019-20/47 and the subsequent limit revisions), and the NPCI UPI
Linking / Mandate API specs. Where a number could drift, it lives in `config.py`, not in
code.

## 1. UMN — the Unified Mandate Number

Every UPI AutoPay mandate has a **UMN**, issued when the customer approves the mandate in
their UPI app. Lifecycle states MandateMend cares about (`schemas.MandateState`):

| state | meaning | chargeable? |
|---|---|---|
| `ACTIVE` | approved, within validity, not paused | yes |
| `PAUSED` | customer paused it in their app; can be resumed | **no** — needs the customer to resume or re-authorize |
| `EXPIRED` | past `mandate_valid_until` | **no** — needs a fresh mandate / re-authorization |
| `REVOKED` | customer cancelled it | **no** — terminal; a new mandate is required |

The engine treats `PAUSED / EXPIRED / REVOKED` as **dead** (`rules.DEAD_MANDATE_STATES`): no
`RETRY` / `PARTIAL_CHARGE` is ever emitted against them (invariant **I3**). The recovery
path for a dead mandate is an outbound contact — a re-authorization request
(`REQUEST_REAUTH`) or a one-off UPI collect link — never an AutoPay debit.

## 2. AFA exemption ceiling — ₹15,000

UPI AutoPay recurring debits are **exempt from per-transaction Additional Factor of
Authentication (AFA)** up to a ceiling. The ceiling was ₹5,000, raised to **₹15,000** (NPCI
OC 82 / RBI, effective 2021, still current as of this build). At or below the ceiling the
merchant may debit on the standing mandate with only the 24-hour pre-debit notice. **Above
the ceiling, each debit requires a fresh AFA** — in practice, the customer re-authorizing
the specific transaction (a re-auth / re-approval step), not just a notice.

MandateMend encodes this as `rules.rule_afa_exemption(amount_paise, reauth_done)` and
invariant **I13**: a charge for more than `settings.afa_exemption_ceiling_paise` is only
allowed if a `REQUEST_REAUTH` was executed earlier in the same recovery session. Otherwise
the engine substitutes `REQUEST_REAUTH` for the retry (`afa_substitution` in the rule
trace). *Note:* the synthetic batches top out at ₹4,999, so no batch mandate exercises this
path — I13 is proven by a crafted unit test, the same way the injected-violation case
proves the NPCI cap.

## 3. Per-transaction category cap — ₹1,00,000

Some merchant categories (insurance, mutual-fund SIPs, etc.) have a higher AutoPay
per-transaction cap of **₹1,00,000**, still with AFA required above ₹15,000. MandateMend
does not model merchant categories; the mandate's own `mandate_max_amount_paise` (invariant
**I6**) is the per-transaction cap it enforces, and the AFA ceiling (I13) sits below it.

## 4. Pre-debit notification — 24 hours / T-1

The customer must be notified **at least 24 hours before** each AutoPay debit (RBI e-mandate
framework). The notification can be sent by NPCI (for mandates registered through the UPI
app) or by the merchant; MandateMend models the merchant-sent case. Invariant **I2**: every
executed `RETRY` / `PARTIAL_CHARGE` is preceded by an executed `SEND_NOTIFICATION` at least
`settings.predebit_notice_hours` (= 24) earlier. The notice also may not land in quiet hours
(**I4**, 21:00–08:00 IST).

## 5. Retry cap — 1 + 3

NPCI allows the original debit attempt plus **up to 3 retries** for a failed recurring
payment. Invariant **I1**: at most `settings.npci_max_retries` (= 3) executed charge
attempts per mandate per recovery session. `REQUEST_REAUTH` and `SEND_NOTIFICATION` are
**contacts, not charges** — they never consume a retry.

## 6. Contact frequency

Not an NPCI rule but an operational / anti-nuisance one: MandateMend caps outbound customer
contacts at `settings.max_contacts_per_week` (= 3) — counting `SEND_NOTIFICATION`,
`OFFER_ALTERNATE_METHOD`, and `REQUEST_REAUTH` together (invariant **I5**).

## 7. Pause / revoke mid-flight

A mandate can be paused or revoked by the customer at any time, including between a
recovery-session's rounds. The agent re-reads `mandate_state` each round; a mid-flight
transition to a dead state stops any further charge attempt (I3) and routes to a contact.
The executor's idempotency key (I11) also guarantees that a webhook replayed after a
revoke cannot re-charge.
