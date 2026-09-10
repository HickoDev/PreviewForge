from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Environment = Annotated[str, Field(pattern=r"^(staging|preview-[1-9][0-9]{0,8})$")]
Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Short = Annotated[str, Field(min_length=1, max_length=700)]
References = Annotated[
    list[Annotated[str, Field(pattern=r"^[a-z]+-[0-9]{1,3}$")]], Field(min_length=1, max_length=8)
]
Cause = Literal[
    "Database port mismatch",
    "Missing required configuration",
    "Image pull failure",
    "Container exceeded memory limit",
    "Floci endpoint mismatch",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosisRequest(Strict):
    environment: Environment
    source_sha: Sha
    fixture: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,60}$")] | None = None
    allow_live: bool = False


class Evidence(Strict):
    id: Annotated[str, Field(pattern=r"^[a-z]+-[0-9]{1,3}$")]
    source: Literal["deployment", "pod", "service", "event", "log", "diff", "argocd"]
    timestamp: datetime
    environment: Environment
    source_sha: Sha
    revision: Sha | None = None
    excerpt: Annotated[str, Field(max_length=3000)]


class Bundle(Strict):
    environment: Environment
    source_sha: Sha
    image: Annotated[str, Field(max_length=250)]
    config_revision: Sha | None = None
    evidence: Annotated[list[Evidence], Field(max_length=40)]
    missing_evidence: Annotated[list[Short], Field(max_length=30)] = []


class Fact(Strict):
    statement: Short
    evidence_ids: References
    quote: Annotated[str, Field(min_length=1, max_length=500)]


class Hypothesis(Strict):
    cause: Cause
    evidence_ids: References
    limitations: Annotated[list[Short], Field(min_length=1, max_length=5)]


class Diagnosis(Strict):
    status: Literal["diagnosed", "healthy", "insufficient_evidence"]
    environment: Environment
    source_sha: Sha
    summary: Short
    observed_facts: Annotated[list[Fact], Field(max_length=8)]
    hypotheses: Annotated[list[Hypothesis], Field(max_length=5)]
    suggested_checks: Annotated[list[Short], Field(max_length=5)]
    missing_evidence: Annotated[list[Short], Field(max_length=30)]
