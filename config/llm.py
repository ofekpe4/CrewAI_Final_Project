"""Single source of truth for LLM configuration (PROJECT_PLAN.md §L, §I, §Q.4).

Design constraints for Phase 0:

- Importing this module must **never** make a network or LLM call.
- Importing it must **never** require ``OPENAI_API_KEY`` to be set. Phases 0–5
  import project modules freely without it; only Crew execution (Phase 6+) needs
  the key (§B.2).
- No secret is ever stored here or in ``settings.yaml`` — the key is read from the
  environment, by name, at execution time.
- No Agent/Crew is created here. This module only *describes* the configuration;
  Phase 6 wires it into CrewAI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from harbor_vale.io_paths import SETTINGS_YAML

# Plan defaults (PROJECT_PLAN.md §V.2 N2, §Q.4) — used when settings.yaml is absent
# or omits a field.
_DEFAULT_PROVIDER = "openai"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TEMPERATURE = 0.1
_DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


@dataclass(frozen=True)
class LLMConfig:
    """Resolved, non-secret LLM configuration."""

    provider: str = _DEFAULT_PROVIDER
    model: str = _DEFAULT_MODEL
    temperature: float = _DEFAULT_TEMPERATURE
    api_key_env: str = _DEFAULT_API_KEY_ENV

    @property
    def api_key_present(self) -> bool:
        """True iff the configured API-key environment variable is set and non-empty.

        Reads only the *presence* of the value, never logs or returns it.
        """
        return bool(os.environ.get(self.api_key_env))

    def as_metadata(self) -> dict[str, object]:
        """The non-secret LLM fields recorded in ``run_metadata.json`` (§Q.4)."""
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
        }

    def as_crewai_llm_kwargs(self) -> dict[str, object]:
        """Keyword arguments for constructing ``crewai.LLM`` in Phase 6.

        Returned as plain data so that nothing here instantiates a client or
        touches the network during Phase 0.
        """
        return {"model": self.model, "temperature": self.temperature}


def load_llm_config(settings_path: Path | None = None) -> LLMConfig:
    """Load the ``llm:`` block from ``config/settings.yaml``.

    Falls back to the Plan defaults for a missing file or missing keys. Performs
    no network access and does not read the API-key value.
    """
    path = settings_path or SETTINGS_YAML
    if not path.exists():
        return LLMConfig()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = data.get("llm") or {}
    return LLMConfig(
        provider=str(block.get("provider", _DEFAULT_PROVIDER)),
        model=str(block.get("model", _DEFAULT_MODEL)),
        temperature=float(block.get("temperature", _DEFAULT_TEMPERATURE)),
        api_key_env=str(block.get("api_key_env", _DEFAULT_API_KEY_ENV)),
    )


def require_api_key(config: LLMConfig | None = None) -> str:
    """Return the API key, or raise ``RuntimeError`` with a clear message.

    Call this **only at execution time** (Phase 6+), never at import. Phases 0–5
    must not call it.
    """
    config = config or load_llm_config()
    key = os.environ.get(config.api_key_env)
    if not key:
        raise RuntimeError(
            f"{config.api_key_env} is not set. Copy .env.example to .env and add "
            f"your OpenAI API key. Phases 0–5 do not need it; Crew execution "
            f"(Phase 6+) does."
        )
    return key
