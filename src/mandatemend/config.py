"""Runtime configuration. All knobs come from env / .env (CLAUDE.md §6: no secrets in code)."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Load .env into os.environ so code that reads os.environ directly (RazorpayTestGateway,
# the ANTHROPIC_API_KEY check) sees it — pydantic-settings only parses .env for its own
# MANDATEMEND_* fields. Never overrides a value already exported in the real environment.
load_dotenv(REPO_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANDATEMEND_", env_file=str(REPO_ROOT / ".env"), extra="ignore"
    )

    db_url: str = "postgresql+psycopg://mandatemend:mandatemend@localhost:5432/mandatemend"

    # Diagnoser selection: auto -> llm if ANTHROPIC_API_KEY present else heuristic.
    diagnoser: str = "auto"
    llm_model: str = "claude-sonnet-4-5"

    # Executor selection.
    executor: str = "simulated"

    heldout_batch: Path = REPO_ROOT / "data" / "heldout_batch.frozen.json"
    heldout_labels: Path = REPO_ROOT / "data" / "heldout_labels.frozen.json"
    # Supplementary 1 000-mandate cross-check batch (disjoint index range). The primary
    # 300-batch above stays THE headline metric; v2 is a robustness check.
    heldout_batch_v2: Path = REPO_ROOT / "data" / "heldout_batch_v2.frozen.json"
    heldout_labels_v2: Path = REPO_ROOT / "data" / "heldout_labels_v2.frozen.json"
    iter_log: Path = REPO_ROOT / "logs" / "iterations.jsonl"

    # --- Policy constants (NPCI + operational). Enforced in the policy engine only. ---
    npci_max_retries: int = 3  # 1 original attempt + up to 3 retries
    predebit_notice_hours: int = 24  # notice must precede a scheduled debit by >= this
    quiet_hours_start: int = 21  # 21:00 IST
    quiet_hours_end: int = 8  # 08:00 IST
    max_contacts_per_week: int = 3
    # Economic floor: skip a paid outreach if expected recovery < cost * this multiple.
    outreach_cost_paise: int = 150  # ~Rs 1.50 per WhatsApp/SMS touch (assumption; see CHANGELOG)
    min_expected_value_ratio: float = 1.0
    low_confidence_threshold: float = 0.55  # below this -> NO_ACTION + human queue

    @property
    def anthropic_api_key(self) -> str | None:
        import os

        return os.environ.get("ANTHROPIC_API_KEY") or None

    def resolved_diagnoser(self) -> str:
        if self.diagnoser != "auto":
            return self.diagnoser
        return "llm" if self.anthropic_api_key else "heuristic"


settings = Settings()
