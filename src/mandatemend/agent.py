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
)
from mandatemend.policy.engine import PolicyEngine
from mandatemend.policy.rules import NON_CHARGING_LOOP_ACTIONS, LoopState
from mandatemend.schemas import (
    ActionType,
    FailureEvent,
    MandateResolution,
)

_CHARGES = {ActionType.RETRY, ActionType.PARTIAL_CHARGE}
_MAX_ROUNDS = 6


@dataclass
class Agent:
    diagnoser: Diagnoser
    retry_advisor: RetryAdvisor
    intervention_advisor: InterventionAdvisor
    engine: PolicyEngine
    executor: Executor
    audit_enabled: bool = True

    @classmethod
    def default(cls, gateway: Gateway | None = None, *, audit_enabled: bool = True) -> Agent:
        gw = gateway or get_gateway()
        return cls(
            diagnoser=get_diagnoser(),
            retry_advisor=HeuristicRetryAdvisor(),
            intervention_advisor=HeuristicInterventionAdvisor(),
            engine=PolicyEngine(),
            executor=Executor(gw),
            audit_enabled=audit_enabled,
        )

    def _escalate(self, mandate_id: str, reason: str, round_no: int) -> None:
        if self.audit_enabled:
            ledger.append(mandate_id, "escalation", {"reason": reason, "round": round_no})

    def recover(self, event: FailureEvent) -> MandateResolution:  # noqa: C901 - one explicit loop
        diag = self.diagnoser.diagnose(event)
        if self.audit_enabled:
            ledger.append(event.mandate_id, "diagnosis", diag.model_dump())

        state = LoopState(
            now=event.occurred_at + timedelta(minutes=5),
            round_no=0,
            retries_used=0,
            contacts_this_week=event.history.contacts_this_week,
            consecutive_hard_declines=event.history.consecutive_failures,
            grace_used=event.history.grace_used,
        )
        timeline = []
        recovered = False
        recovered_amt = 0
        terminal = ActionType.NO_ACTION
        escalated = False
        last_noncharge_action: ActionType | None = None
        noncharge_repeat = 0

        for rnd in range(_MAX_ROUNDS):
            state.round_no = rnd
            retry_adv = self.retry_advisor.advise(event, diag)
            interv_adv = self.intervention_advisor.advise(event, diag)
            action = self.engine.decide(event, diag, retry_adv, interv_adv, state)
            if self.audit_enabled:
                ledger.append(
                    event.mandate_id, "policy.decision",
                    {"round": rnd, "action": action.action_type.value, "reason": action.reason,
                     "rule_trace": [rt.model_dump() for rt in action.rule_trace]},
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

            # 3. apply executed effects
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
                event.mandate_id, "resolution",
                {k: v for k, v in res.model_dump().items() if k != "timeline"},
            )
        return res
