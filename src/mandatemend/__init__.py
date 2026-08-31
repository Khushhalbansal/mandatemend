"""MandateMend — UPI AutoPay / e-mandate failure-recovery agent.

Architecture (trust boundary, CLAUDE.md §2):

    ingest  ->  diagnosis (LLM, sandboxed, no authority)
                     |
                     v
        retry-timing model  +  intervention uplift model   (advisory only)
                     |
                     v
        POLICY ENGINE  (deterministic, sole authority to emit an Action)
                     |
                     v
             EXECUTOR  (idempotent, DB-unique-constrained)
                     |
                     v
        APPEND-ONLY, HASH-CHAINED AUDIT LEDGER
"""

__version__ = "0.1.0"
POLICY_VERSION = "policy-2026-09-01"
