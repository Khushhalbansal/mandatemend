"""The recovery agent: one bounded loop per mandate.

diagnose once -> each round: advisors -> policy.decide -> executor.execute -> update state.

Termination invariant (stated for the pitch / honest exception list): every mandate ends in
exactly one of two states — RECOVERED, or STOP_AND_ESCALATE (on a human's desk). The loop
never "silently gives up". Escalation happens on:
  * an explicit engine STOP_AND_ESCALATE / requires_human,
  * a stall: the same non-charging action_type chosen in two consecutive rounds (there is no
    legitimate case for repeating an identical notification / alternate-method offer / grace
    / no-action),
  * retry + contact budgets both exhausted,
  * the round budget running out without recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from mandatemend.audit import ledger
from mandatemend.config import settings
from mandatemend.diagnosis.base import Diagnoser, get_diagnoser
from mandatemend.executor.executor import Executor
from mandatemend.executor.gateway import Gateway, get_gateway
from mandatemend.models.advisors import (
    HeuristicInterventionAdvisor,
    HeuristicRetryAdvisor,
    InterventionAdvisor,
    RetryAdvisor,
    SurvivalRetryAdvisor,
    TLearnerUpliftAdvisor,
)
from mandatemend.models.retry_timing import ARTIFACT as _RETRY_ARTIFACT
from mandatemend.models.uplift import ARTIFACT as _UPLIFT_ARTIFACT
from mandatemend.policy.engine import PolicyEngine
from mandatemend.policy.rules import NON_CHARGING_LOOP_ACTIONS, LoopState
from mandatemend.schemas import (
    ActionType,
    FailureEvent,
    InterventionAdvice,
    InterventionType,
    MandateResolution,
    RetryTimingAdvice,
    TypedDiagnosis,
)
from mandatemend.simulation import snap_delay

_CHARGES = {ActionType.RETRY, ActionType.PARTIAL_CHARGE}
# Enough rounds to spend the full NPCI retry budget (3) with pre-debit notices interleaved.
_MAX_ROUNDS = 10


# Causes where the frozen-batch diagnosis (iteration 2) showed the agent losing to a plain
# fixed-schedule retry because the uplift advisor steered to a non-retry arm: patient
# multi-retry is the real answer (transient tech declines; riding out a bank-downtime window;
# non-churn accounts mislabelled SUSPECTED_CHURN that just need another attempt near payday).
_RETRY_FIRST_CAUSES = ("TECH_DECLINE", "BANK_DOWNTIME", "SUSPECTED_CHURN")


def _prefer_retry_when_competitive(
    retry_adv: RetryTimingAdvice,
    interv_adv: InterventionAdvice,
    diag: TypedDiagnosis,
    retries_used: int,
) -> InterventionAdvice:
    """Targeted override: on `_RETRY_FIRST_CAUSES`, spend the retry budget on a *full* retry
    before any other arm.

    Only `RETRY_ONLY` passes through. `PARTIAL_CHARGE` is deliberately *not* exempt here: a
    partial charge still consumes one of the 3 NPCI attempts AND marks its delay bucket as
    tried, so on a transient TECH_DECLINE / a bank-downtime window / a mis-labelled churn
    account it poisons the exact bucket a plain full retry would have won on (found in the
    iteration-9 ablation: the T-learner ranks PARTIAL_CHARGE top for TECH_DECLINE and lost
    high-value mandates that the heuristic recovered with a straight RETRY@24h)."""
    if retries_used >= settings.npci_max_retries:
        return interv_adv
    if diag.cause.value not in _RETRY_FIRST_CAUSES:
        return interv_adv
    if interv_adv.intervention is InterventionType.RETRY_ONLY:
        return interv_adv
    return InterventionAdvice(
        intervention=InterventionType.RETRY_ONLY,
        uplift=max(0.0, retry_adv.p_success - 0.06),
        p_recover=retry_adv.p_success,
        ranked=[(InterventionType.RETRY_ONLY, retry_adv.p_success), *interv_adv.ranked],
        model_source=f"{interv_adv.model_source}+retry-first",
    )


def _action_to_intervention(
    action_type: ActionType, channel: str | None
) -> InterventionType | None:
    if action_type is ActionType.PARTIAL_CHARGE:
        return InterventionType.PARTIAL_CHARGE
    if action_type is ActionType.GRACE_EXTEND:
        return InterventionType.GRACE_48H
    if action_type is ActionType.OFFER_ALTERNATE_METHOD:
        return InterventionType.METHOD_SWITCH
    if action_type is ActionType.REQUEST_REAUTH:
        return InterventionType.REAUTH_LINK
    if action_type is ActionType.SEND_NOTIFICATION:
        return (
            InterventionType.WHATSAPP_UPI_LINK
            if (channel or "whatsapp") == "whatsapp"
            else InterventionType.SMS_REMINDER
        )
    return None  # RETRY is timing-driven, not an "arm" to exhaust


@dataclass
class Agent:
    diagnoser: Diagnoser
    retry_advisor: RetryAdvisor
    intervention_advisor: InterventionAdvisor
    engine: PolicyEngine
    executor: Executor
    audit_enabled: bool = True

    @classmethod
    def default(
        cls,
        gateway: Gateway | None = None,
        *,
        audit_enabled: bool = True,
        trained: bool | None = None,
    ) -> Agent:
        """`trained=None` -> use trained advisors iff both model artifacts exist."""
        gw = gateway or get_gateway()
        use_trained = (
            trained
            if trained is not None
            else (_RETRY_ARTIFACT.exists() and _UPLIFT_ARTIFACT.exists())
        )
        if use_trained:
            retry_adv: RetryAdvisor = SurvivalRetryAdvisor()
            interv_adv: InterventionAdvisor = TLearnerUpliftAdvisor()
        else:
            retry_adv = HeuristicRetryAdvisor()
            interv_adv = HeuristicInterventionAdvisor()
        return cls(
            diagnoser=get_diagnoser(),
            retry_advisor=retry_adv,
            intervention_advisor=interv_adv,
            engine=PolicyEngine(),
            executor=Executor(gw),
            audit_enabled=audit_enabled,
        )

    def _escalate(self, mandate_id: str, reason: str, round_no: int) -> None:
        if self.audit_enabled:
            ledger.append(mandate_id, "escalation", {"reason": reason, "round": round_no})

    def warm(self, events: list[FailureEvent]) -> None:
        """Batch-precompute model inference for a whole batch (trained advisors only).

        Cuts a 300-mandate scored run from ~50s to ~10s: HistGBM's per-call Python overhead
        makes N*|arms| single-row predicts far slower than |arms| predicts over an (N, F)
        matrix. Diagnosis here is the offline heuristic and is re-run (deterministically) in
        `recover()` for the audit trail.
        """
        rows = [(ev, self.diagnoser.diagnose(ev)) for ev in events]
        for advisor in (self.retry_advisor, self.intervention_advisor):
            warm = getattr(advisor, "warm", None)
            if callable(warm):
                warm(rows)

    def recover(self, event: FailureEvent) -> MandateResolution:  # noqa: C901 - one explicit loop
        diag = self.diagnoser.diagnose(event)
        if self.audit_enabled:
            ledger.append(event.mandate_id, "diagnosis", diag.model_dump())

        state = LoopState(
            now=event.occurred_at + timedelta(minutes=5),
            round_no=0,
            retries_used=0,
            contacts_this_week=event.history.contacts_this_week,
            consecutive_hard_declines=0,  # in-session only; history feeds the models, not the stop
            grace_used=event.history.grace_used,
        )
        timeline = []
        recovered = False
        recovered_amt = 0
        terminal = ActionType.NO_ACTION
        escalated = False
        last_noncharge_action: ActionType | None = None
        noncharge_repeat = 0
        tried_delays: set[float] = set()
        tried_interventions: set[InterventionType] = set()

        for rnd in range(_MAX_ROUNDS):
            state.round_no = rnd
            retry_adv = self.retry_advisor.advise(event, diag, tried_delays=frozenset(tried_delays))
            # The first retry always needs a 24h pre-debit notice first, so a sub-25h delay
            # only makes the engine bounce to "send notice" and can trip the stall-breaker.
            # Align the ask with that constraint; the model's true timing applies to retries
            # 2 and 3, once a notice is on file.
            if state.last_notice_at is None and retry_adv.delay_hours < 25.0:
                retry_adv = retry_adv.model_copy(update={"delay_hours": 25.0})
            interv_adv = self.intervention_advisor.advise(
                event, diag, tried=frozenset(tried_interventions)
            )
            interv_adv = _prefer_retry_when_competitive(
                retry_adv, interv_adv, diag, state.retries_used
            )
            action = self.engine.decide(event, diag, retry_adv, interv_adv, state)
            if self.audit_enabled:
                ledger.append(
                    event.mandate_id,
                    "policy.decision",
                    {
                        "round": rnd,
                        "action": action.action_type.value,
                        "reason": action.reason,
                        "rule_trace": [rt.model_dump() for rt in action.rule_trace],
                    },
                )

            result = self.executor.execute(action, event)
            timeline.append(result)
            at = action.action_type

            # 1. explicit engine terminal
            if at is ActionType.STOP_AND_ESCALATE or action.requires_human:
                terminal = ActionType.STOP_AND_ESCALATE
                escalated = True
                break

            # 2. stall-breaker: identical non-charging action two rounds running -> escalate
            if at in NON_CHARGING_LOOP_ACTIONS:
                noncharge_repeat = noncharge_repeat + 1 if at == last_noncharge_action else 1
                last_noncharge_action = at
                if noncharge_repeat >= 2:
                    terminal = ActionType.STOP_AND_ESCALATE
                    escalated = True
                    self._escalate(
                        event.mandate_id,
                        f"stall: {at.value} repeated with no state progress",
                        rnd,
                    )
                    break
            else:
                last_noncharge_action = None
                noncharge_repeat = 0

            # 3. apply executed effects + record what has been tried (round-awareness)
            if result.executed:
                if at in _CHARGES and action.retry_delay_bucket is not None:
                    tried_delays.add(snap_delay(action.retry_delay_bucket))
                arm = _action_to_intervention(at, action.channel)
                if arm is not None:
                    tried_interventions.add(arm)

            if result.executed and at in _CHARGES:
                state.retries_used += 1
                if result.gateway_success:
                    recovered, recovered_amt, terminal = True, result.recovered_amount_paise, at
                    state.consecutive_hard_declines = 0
                    break
                state.consecutive_hard_declines += 1
            elif result.executed and at is ActionType.SEND_NOTIFICATION:
                state.contacts_this_week += 1
                state.last_notice_at = action.scheduled_at
                if result.gateway_success:
                    recovered, recovered_amt, terminal = True, result.recovered_amount_paise, at
                    break
            elif result.executed and at is ActionType.GRACE_EXTEND:
                state.grace_used = True
                if result.gateway_success:
                    recovered, recovered_amt, terminal = True, result.recovered_amount_paise, at
                    break
            elif result.executed and at is ActionType.OFFER_ALTERNATE_METHOD:
                state.contacts_this_week += 1
                if result.gateway_success:
                    recovered, recovered_amt, terminal = True, result.recovered_amount_paise, at
                    break
            elif result.executed and at is ActionType.REQUEST_REAUTH:
                # An outbound contact, never a charge — counts against the weekly cap only.
                state.contacts_this_week += 1
                state.reauth_done = True  # AFA (I13) satisfied for any later high-value retry
                if result.gateway_success:
                    recovered, recovered_amt, terminal = True, result.recovered_amount_paise, at
                    break

            state.now = max(state.now, action.scheduled_at) + timedelta(minutes=30)

            if (
                state.retries_used >= settings.npci_max_retries
                and state.contacts_this_week >= settings.max_contacts_per_week
            ):
                terminal = ActionType.STOP_AND_ESCALATE
                escalated = True
                self._escalate(event.mandate_id, "retry + contact budgets both exhausted", rnd)
                break

        # termination invariant: never leave a mandate un-recovered and un-escalated
        if not recovered and not escalated:
            terminal = ActionType.STOP_AND_ESCALATE
            escalated = True
            self._escalate(event.mandate_id, "round budget exhausted without recovery", _MAX_ROUNDS)

        res = MandateResolution(
            mandate_id=event.mandate_id,
            amount_at_risk_paise=event.amount_paise,
            recovered=recovered,
            recovered_amount_paise=recovered_amt if recovered else 0,
            retries_used=state.retries_used,
            contacts_made=state.contacts_this_week,
            terminal_action=terminal,
            escalated_to_human=escalated,
            timeline=timeline,
        )
        if self.audit_enabled:
            ledger.append(
                event.mandate_id,
                "resolution",
                {k: v for k, v in res.model_dump().items() if k != "timeline"},
            )
        return res
