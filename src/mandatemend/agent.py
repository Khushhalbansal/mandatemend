"""The recovery agent: one bounded loop per mandate.

diagnose once -> each round: advisors -> policy.decide -> executor.execute -> update state.
Stops on recovery, terminal action, stall, or budget exhaustion. Returns a MandateResolution
whose timeline the independent invariant checker re-verifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from mandatemend.audit import ledger
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
from mandatemend.policy.rules import LoopState
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

    def recover(self, event: FailureEvent) -> MandateResolution:
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
        consecutive_noop = 0

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

            if action.action_type is ActionType.STOP_AND_ESCALATE or action.requires_human:
                terminal = action.action_type
                escalated = True
                break

            if action.action_type is ActionType.NO_ACTION:
                consecutive_noop += 1
                terminal = ActionType.NO_ACTION
                if consecutive_noop >= 2:
                    break
                # advance time a little and try again next round
                state.now = state.now + timedelta(hours=12)
                continue
            consecutive_noop = 0

            # ---- update loop state from what actually executed ----
            if result.executed and action.action_type in _CHARGES:
                state.retries_used += 1
                if result.gateway_success:
                    recovered = True
                    recovered_amt = result.recovered_amount_paise
                    state.consecutive_hard_declines = 0
                    terminal = action.action_type
                    break
                state.consecutive_hard_declines += 1
            elif result.executed and action.action_type is ActionType.SEND_NOTIFICATION:
                state.contacts_this_week += 1
                state.last_notice_at = action.scheduled_at
                if result.gateway_success:
                    recovered = True
                    recovered_amt = result.recovered_amount_paise
                    terminal = action.action_type
                    break
            elif result.executed and action.action_type is ActionType.GRACE_EXTEND:
                state.grace_used = True
                if result.gateway_success:
                    recovered = True
                    recovered_amt = result.recovered_amount_paise
                    terminal = action.action_type
                    break
            elif result.executed and action.action_type is ActionType.OFFER_ALTERNATE_METHOD:
                state.contacts_this_week += 1
                if result.gateway_success:
                    recovered = True
                    recovered_amt = result.recovered_amount_paise
                    terminal = action.action_type
                    break

            # advance simulated time to just past this action
            state.now = max(state.now, action.scheduled_at) + timedelta(minutes=30)

            if state.retries_used >= 3 and state.contacts_this_week >= 3:
                terminal = ActionType.STOP_AND_ESCALATE
                escalated = True
                if self.audit_enabled:
                    ledger.append(
                        event.mandate_id, "escalation",
                        {"reason": "retry + contact budgets both exhausted"},
                    )
                break

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
