"""Idempotent executor.

Exactly-once is enforced by the DB UNIQUE constraint on `executed_action.idempotency_key`
(CLAUDE.md §2/§6), not by application logic. Sequence per action:

  1. Non-money actions (NO_ACTION / STOP_AND_ESCALATE): audit only, nothing to execute.
  2. RESERVE: INSERT the idempotency key and COMMIT. A concurrent duplicate hits the UNIQUE
     constraint -> IntegrityError -> we return the existing outcome, `dedup_hit=True`.
     The reserve commits *before* the gateway call, so a crash mid-flight leaves the action
     marked attempted and it will not be retried (fail closed: never risk a double charge).
  3. EXECUTE: call the gateway.
  4. FINALIZE: write the gateway outcome back onto the row; append an audit entry.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mandatemend.audit import ledger
from mandatemend.db.models import ExecutedAction
from mandatemend.db.session import session_scope
from mandatemend.executor.gateway import Gateway
from mandatemend.schemas import Action, ActionType, ExecutionResult, FailureEvent

_NON_MONEY = {ActionType.NO_ACTION, ActionType.STOP_AND_ESCALATE}


class Executor:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway

    def execute(self, action: Action, event: FailureEvent) -> ExecutionResult:
        if action.action_type in _NON_MONEY:
            ledger.append(
                action.mandate_id,
                "execution.noop",
                {"action": action.action_type.value, "reason": action.reason,
                 "idempotency_key": action.idempotency_key},
            )
            return ExecutionResult(
                action=action, executed=False, dedup_hit=False,
                detail=f"{action.action_type.value}: not a money move",
            )

        # 2. RESERVE
        try:
            with session_scope() as s:
                s.add(
                    ExecutedAction(
                        idempotency_key=action.idempotency_key,
                        mandate_id=action.mandate_id,
                        action_type=action.action_type.value,
                        amount_paise=action.amount_paise,
                        scheduled_at=action.scheduled_at,
                        created_at=datetime.now(UTC),
                        gateway_success=None,
                        recovered_amount_paise=0,
                        detail="reserved",
                    )
                )
        except IntegrityError:
            return self._dedup_result(action)

        # 3. EXECUTE
        try:
            success, recovered, detail = self.gateway.attempt(action, event)
        except Exception as exc:  # noqa: BLE001 - fail closed; row stays 'reserved', not retried
            ledger.append(
                action.mandate_id, "execution.error",
                {"idempotency_key": action.idempotency_key, "error": f"{type(exc).__name__}: {exc}"},
            )
            return ExecutionResult(
                action=action, executed=True, gateway_success=False,
                recovered_amount_paise=0, detail=f"gateway raised {type(exc).__name__}: {exc}",
            )

        # 4. FINALIZE
        with session_scope() as s:
            row = s.execute(
                select(ExecutedAction).where(
                    ExecutedAction.idempotency_key == action.idempotency_key
                )
            ).scalar_one()
            row.gateway_success = success
            row.recovered_amount_paise = int(recovered)
            row.detail = detail[:1000]

        ledger.append(
            action.mandate_id,
            "execution",
            {
                "idempotency_key": action.idempotency_key,
                "action": action.action_type.value,
                "amount_paise": action.amount_paise,
                "scheduled_at": action.scheduled_at.isoformat(),
                "gateway": self.gateway.name,
                "success": success,
                "recovered_amount_paise": int(recovered),
                "detail": detail[:300],
                "rule_trace": [rt.model_dump() for rt in action.rule_trace],
            },
        )
        return ExecutionResult(
            action=action, executed=True, dedup_hit=False, gateway_success=success,
            recovered_amount_paise=int(recovered) if success else 0, detail=detail,
        )

    def _dedup_result(self, action: Action) -> ExecutionResult:
        with session_scope() as s:
            row = s.execute(
                select(ExecutedAction).where(
                    ExecutedAction.idempotency_key == action.idempotency_key
                )
            ).scalar_one()
            success = row.gateway_success
            recovered = row.recovered_amount_paise
        ledger.append(
            action.mandate_id, "execution.dedup",
            {"idempotency_key": action.idempotency_key, "prior_success": success},
        )
        return ExecutionResult(
            action=action, executed=False, dedup_hit=True, gateway_success=success,
            recovered_amount_paise=int(recovered or 0),
            detail="idempotency-deduplicated: this action was already executed",
        )
