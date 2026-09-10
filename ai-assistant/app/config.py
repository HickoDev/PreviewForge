from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)
    ai_mode: Literal["mock", "nvidia"] = "mock"
    ai_live_requests_enabled: bool = False
    nvidia_base_url: Literal["https://integrate.api.nvidia.com/v1"] = (
        "https://integrate.api.nvidia.com/v1"
    )
    nvidia_model: str = Field(
        default="meta/llama-3.3-70b-instruct", pattern=r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$"
    )
    nvidia_api_key: SecretStr = SecretStr("")
    ai_access_token: SecretStr = SecretStr("")
    ai_connect_timeout_seconds: float = Field(default=5, ge=0.1, le=10)
    ai_request_budget_seconds: float = Field(default=90, ge=1, le=120)
    ai_max_attempts: int = Field(default=2, ge=1, le=2)
    ai_max_output_tokens: int = Field(default=1500, ge=256, le=2048)
    ai_max_evidence_chars: int = Field(default=20000, ge=1000, le=20000)
    # Conservative UTF-8 byte ceiling, including schema/instructions. It is an
    # upper bound for ordinary byte-fallback text tokenizers, not a token count.
    ai_max_prompt_bytes: int = Field(default=32000, ge=8000, le=48000)
    ai_max_concurrent_requests: int = Field(default=1, ge=1, le=2)
    ai_collector: Literal["fixtures", "kubernetes"] = "fixtures"
    ai_policy_file: Path = Path("/etc/previewforge/policy.json")
    ai_max_age_seconds: int = Field(default=600, ge=30, le=900)

    @model_validator(mode="after")
    def mode_boundary(self):
        if self.ai_mode == "mock" and self.ai_live_requests_enabled:
            raise ValueError("Live requests require NVIDIA mode")
        return self
