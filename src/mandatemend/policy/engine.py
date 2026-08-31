"""The deterministic policy engine.

Contract (CLAUDE.md §2):
  * `decide(...)` is the ONLY place an `Action` is constructed.
  * Model / LLM outputs are advisory. Any hard rule can veto or downgrade them.
  * The returned `Action` always carries a non-empty `rule_trace` explaining every step.
  * On any unexpected internal error the engine fails closed: NO_ACTION + human queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mandatemend import POLICY_VERSION
from mandatemend.policy.rules import (
    CHARGING_ACTIONS,
    LoopState,
    clamp_out_of_quiet,
    rule_amount_within_cap,
    rule_confidence_gate,
    rule_contact_frequency,
    rule_mandate_live_for_charge,
    rule_npci_retry_cap,
    rule_outreach_economics,
    rule_predebit_notice,
    rule_quiet_hours,
    rule_stopping,
)
from mandatemend.schemas import (
    Action,
    ActionType,
    FailureEvent,
    InterventionAdvice,
    InterventionType,
    PaymentMethod,
    RetryTimingAdvice,
    RuleEvaluation,
    TypedDiagnosis,
)
from mandatemend.simulation import INTERVENTION_TO_ACTION, PARTIAL_RATIO, snap_delay

_NOTICE_LEAD_H = 6  # how far ahead a notification itself is scheduled (out of quiet hours)


def _idem_key(mandate_id: str, round_no: int, action_type: ActionType, scheduled_at: datetime) -> str:
    return f"{mandate_id}|r{round_no}|{action_type.value}|{scheduled_at:%Y%m%dT%H}"


class PolicyEngine:
    policy_version = POLICY_VERSION

    def decide(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        retry_advice: RetryTimingAdvice,
        intervention_advice: InterventionAdvice,
        state: LoopState,
    ) -> Action:
        try:
            return self._decide(event, diag, retry_advice, intervention_advice, state)
        except Exception as exc:  # noqa: BLE001 - fail closed (CLAUDE.md §6 "fail closed")
            trace = [
                RuleEvaluation(
                    rule="engine_fail_closed",
                    passed=False,
                    detail=f"unexpected error {type(exc).__name__}: {exc}",
                )
            ]
            return self._terminal(
                event, diag, trace, ActionType.NO_ACTION,
                reason="policy engine error -> fail closed, escalate to human", human=True,
            )

    # ------------------------------------------------------------------ core
    def _decide(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        retry_advice: RetryTimingAdvice,
        intervention_advice: InterventionAdvice,
        state: LoopState,
    ) -> Action:
        trace: list[RuleEvaluation] = []

        r = rule_confidence_gate(diag)
        trace.append(r)
        if not r.passed:
            return self._terminal(
                event, diag, trace, ActionType.NO_ACTION,
                reason="diagnosis confidence below threshold -> human queue", human=True,
            )

        r = rule_stopping(state)
        trace.append(r)
        if not r.passed:
            return self._terminal(
                event, diag, trace, ActionType.STOP_AND_ESCALATE,
                reason="stopping rule: 2 consecutive hard declines", human=True,
            )

        desired = intervention_advice.intervention
        action_type = INTERVENTION_TO_ACTION.get(desired, ActionType.NO_ACTION)

        live = rule_mandate_live_for_charge(event, diag)
        trace.append(live)
        if not live.passed and action_type in CHARGING_ACTIONS:
            action_type = ActionType.SEND_NOTIFICATION
            desired = InterventionType.WHATSAPP_UPI_LINK
            trace.append(
                RuleEvaluation(
                    rule="dead_mandate_substitution", passed=False,
                    detail="mandate not chargeable -> WhatsApp UPI collect link instead",
                )
            )

        # ---- charging branch ------------------------------------------------
        if action_type in CHARGING_ACTIONS:
            cap = rule_npci_retry_cap(state)
            trace.append(cap)
            if not cap.passed:
                action_type = ActionType.SEND_NOTIFICATION
                desired = InterventionType.WHATSAPP_UPI_LINK
                trace.append(
                    RuleEvaluation(
                        rule="retry_cap_substitution", passed=False,
                        detail="NPCI retry cap reached -> final notification only",
                    )
                )
            else:
                amount = (
                    event.amount_paise
                    if action_type is ActionType.RETRY
                    else int(round(PARTIAL_RATIO * event.amount_paise))
                )
                amt_ok = rule_amount_within_cap(amount, event)
                trace.append(amt_ok)
                if not amt_ok.passed:
                    partial = int(round(PARTIAL_RATIO * event.amount_paise))
                    if partial <= event.mandate_max_amount_paise:
                        action_type = ActionType.PARTIAL_CHARGE
                        amount = partial
                        trace.append(
                            RuleEvaluation(
                                rule="amount_substitution", passed=False,
                                detail=f"full amount over cap -> partial charge {amount}p",
                            )
                        )
                    else:
                        action_type = ActionType.OFFER_ALTERNATE_METHOD
                        desired = InterventionType.METHOD_SWITCH
                        trace.append(
                            RuleEvaluation(
                                rule="amount_substitution", passed=False,
                                detail="even partial charge over cap -> offer alternate method",
                            )
                        )

        # recompute scheduled time for a (possibly still) charging action
        if action_type in CHARGING_ACTIONS:
            delay = snap_delay(max(0.0, retry_advice.delay_hours))
            scheduled = state.now + timedelta(hours=max(delay, 1.0))
            pdn = rule_predebit_notice(state, scheduled)
            trace.append(pdn)
            if not pdn.passed:
                action_type = ActionType.SEND_NOTIFICATION
                desired = InterventionType.WHATSAPP_UPI_LINK
                trace.append(
                    RuleEvaluation(
                        rule="predebit_notice_substitution", passed=False,
                        detail="must send a 24h pre-debit notice before this retry",
                    )
                )
            else:
                return self._build(
                    event, diag, trace, action_type, scheduled_at=scheduled,
                    amount_paise=amount, round_no=state.round_no,
                    reason=f"{diag.cause}: charge {action_type.value} at +{delay:g}h "
                    f"(model p_success={retry_advice.p_success:.2f})",
                )

        # ---- notification branch -----------------------------------------
        if action_type is ActionType.SEND_NOTIFICATION:
            cf = rule_contact_frequency(state)
            trace.append(cf)
            econ = rule_outreach_economics(intervention_advice.p_recover, event.amount_paise)
            trace.append(econ)

            if not cf.passed:
                if state.retries_used < 3 and state.last_notice_at is not None:
                    return self._terminal(
                        event, diag, trace, ActionType.NO_ACTION,
                        reason="contact cap hit; hold for the already-scheduled retry window",
                        human=False,
                    )
                return self._terminal(
                    event, diag, trace, ActionType.STOP_AND_ESCALATE,
                    reason="contact frequency cap hit with no retry path left", human=True,
                )

            if not econ.passed:
                notice_ok = (
                    state.last_notice_at is not None
                    and state.retries_used < 3
                    and (state.now + timedelta(hours=25) - state.last_notice_at)
                    >= timedelta(hours=24)
                )
                if notice_ok:
                    scheduled = state.now + timedelta(hours=25)
                    trace.append(
                        RuleEvaluation(
                            rule="economics_substitution", passed=False,
                            detail="paid outreach fails economic floor -> plain retry instead",
                        )
                    )
                    return self._build(
                        event, diag, trace, ActionType.RETRY, scheduled_at=scheduled,
                        amount_paise=event.amount_paise, round_no=state.round_no,
                        reason=f"{diag.cause}: outreach not economic; plain retry at +25h",
                    )
                return self._terminal(
                    event, diag, trace, ActionType.NO_ACTION,
                    reason="paid outreach fails economic floor and no cheap path this round",
                    human=False,
                )

            channel = "whatsapp" if desired is InterventionType.WHATSAPP_UPI_LINK else "sms"
            scheduled = clamp_out_of_quiet(state.now + timedelta(hours=_NOTICE_LEAD_H))
            q = rule_quiet_hours(scheduled)
            trace.append(q)
            return self._build(
                event, diag, trace, ActionType.SEND_NOTIFICATION, scheduled_at=scheduled,
                channel=channel, round_no=state.round_no,
                reason=f"{diag.cause}: {channel} outreach / pre-debit notice "
                f"(p_recover={intervention_advice.p_recover:.2f})",
            )

        # ---- grace ------------------------------------------------------
        if action_type is ActionType.GRACE_EXTEND:
            if state.grace_used:
                trace.append(
                    RuleEvaluation(rule="grace_once", passed=False, detail="grace already used")
                )
                return self._terminal(
                    event, diag, trace, ActionType.NO_ACTION,
                    reason="grace already extended once; hold", human=False,
                )
            trace.append(RuleEvaluation(rule="grace_once", passed=True, detail="first grace use"))
            return self._build(
                event, diag, trace, ActionType.GRACE_EXTEND,
                scheduled_at=state.now + timedelta(hours=48), round_no=state.round_no,
                reason=f"{diag.cause}: 48h grace extension before next debit",
            )

        # ---- method switch -------------------------------------------
        if action_type is ActionType.OFFER_ALTERNATE_METHOD:
            alt = (
                PaymentMethod.CARD_EMANDATE
                if event.method is PaymentMethod.UPI_AUTOPAY
                else PaymentMethod.UPI_AUTOPAY
            )
            scheduled = clamp_out_of_quiet(state.now + timedelta(hours=_NOTICE_LEAD_H))
            trace.append(rule_quiet_hours(scheduled))
            return self._build(
                event, diag, trace, ActionType.OFFER_ALTERNATE_METHOD, scheduled_at=scheduled,
                alt_method=alt, round_no=state.round_no,
                reason=f"{diag.cause}: offer alternate method ({alt.value})",
            )

        # ---- default: nothing to do ---------------------------------
        trace.append(
            RuleEvaluation(rule="no_applicable_action", passed=True, detail=f"desired={desired}")
        )
        return self._terminal(
            event, diag, trace, ActionType.NO_ACTION,
            reason="no applicable recovery action this round", human=False,
        )

    # ------------------------------------------------------------------ builders
    def _build(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        trace: list[RuleEvaluation],
        action_type: ActionType,
        *,
        scheduled_at: datetime,
        round_no: int,
        amount_paise: int | None = None,
        channel: str | None = None,
        alt_method: PaymentMethod | None = None,
        reason: str,
    ) -> Action:
        return Action(
            action_type=action_type,
            mandate_id=event.mandate_id,
            idempotency_key=_idem_key(event.mandate_id, round_no, action_type, scheduled_at),
            scheduled_at=scheduled_at,
            amount_paise=amount_paise,
            channel=channel,
            alt_method=alt_method,
            reason=reason,
            rule_trace=trace,
            policy_version=self.policy_version,
            diagnosis=diag,
            requires_human=action_type is ActionType.STOP_AND_ESCALATE,
        )

    def _terminal(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        trace: list[RuleEvaluation],
        action_type: ActionType,
        *,
        reason: str,
        human: bool,
    ) -> Action:
        return Action(
            action_type=action_type,
            mandate_id=event.mandate_id,
            idempotency_key=_idem_key(event.mandate_id, 999, action_type, event.occurred_at),
            scheduled_at=event.occurred_at,
            reason=reason,
            rule_trace=trace,
            policy_version=self.policy_version,
            diagnosis=diag,
            requires_human=human,
        )
