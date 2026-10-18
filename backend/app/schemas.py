from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Detection(BaseModel):
    """The model team's contract. All timestamps are seconds from video start."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: str = Field(min_length=1, max_length=200)
    timecode_sec: float = Field(ge=0)
    start_sec: float | None = Field(default=None, ge=0)
    end_sec: float | None = Field(default=None, gt=0)
    description: str = Field(min_length=1, max_length=3000)
    rule_id: str = Field(min_length=1, max_length=30)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_timestamps: list[float] = Field(default_factory=list, max_length=3)
    alternative_explanation: str = Field(default="", max_length=2000)
    missing_data: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_range(self):
        if (self.start_sec is None) != (self.end_sec is None):
            raise ValueError("start_sec and end_sec must be provided together")
        if self.start_sec is not None and not self.start_sec <= self.timecode_sec < self.end_sec:
            raise ValueError("Range must satisfy start_sec <= timecode_sec < end_sec")
        return self


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    detections: list[Detection] = Field(max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class Rule(BaseModel):
    id: str
    title: str
    document: str
    section: str
    url: str
    applicability: str
    limitation: str
    verification_status: str


class EvidenceFrame(BaseModel):
    timestamp_sec: float
    image_base64: str


class Violation(BaseModel):
    type: str
    timecode_sec: float
    start_sec: float | None = None
    end_sec: float | None = None
    description: str
    evidence_frames: list[EvidenceFrame] = Field(min_length=1, max_length=3)
    rule: Rule
    confidence: float | None = None
    alternative_explanation: str
    missing_data: list[str]


class JobAccepted(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    job_id: str
    status: Literal["processing", "done", "failed"]
    verdict: Literal["no_violation", "violation"] | None = None
    violations: list[Violation] = Field(default_factory=list)
    stage: str
    progress: int = Field(ge=0, le=100)
    mode: Literal["plugin", "demo"]
    created_at: str
    updated_at: str
    duration_sec: float | None = None
    limitations: list[str] = Field(default_factory=list)
    error: dict[str, str] | None = None
