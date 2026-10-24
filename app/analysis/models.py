"""Shared inputs and outputs for the five basic airport metrics."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal["traffic_growth", "airport_operational_pressure", "outbound_long_haul_share",
                 "demand_capacity_pressure", "terminal_expansion_opportunity"]
Status = Literal["ok", "partial", "undefined", "ineligible", "invalid_input", "insufficient_evidence"]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Metric
    airport_ids: list[Annotated[int, Field(strict=True, gt=0)]] | None = None
    region: Literal["New England", "Middle Atlantic", "Midwest", "South", "West"] | None = None
    state_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    year: int | None = Field(default=None, strict=True, ge=1900, le=9999)
    baseline_year: int | None = Field(default=None, strict=True, ge=1900, le=9999)
    forecast_baseline_year: int | None = Field(default=None, strict=True, ge=1900, le=9994)
    forecast_edition: int | None = Field(default=None, strict=True, ge=1900, le=9999)
    forecast_baseline_scenario: str | None = Field(default=None, min_length=1)
    forecast_scenario: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_selection_and_years(self) -> "AnalysisRequest":
        if sum(value is not None for value in (self.airport_ids, self.region, self.state_code)) != 1 or self.airport_ids == []:
            raise ValueError("Choose nonempty airport_ids, one region, or one state_code")
        if self.state_code is not None:
            self.state_code = self.state_code.upper()
        if self.baseline_year is not None and self.year is not None and self.baseline_year >= self.year:
            raise ValueError("baseline_year must precede year")
        single_year = self.metric in ("airport_operational_pressure", "outbound_long_haul_share")
        if single_year and self.baseline_year is not None:
            raise ValueError("Use year alone for this single-year metric")
        uses_forecast = self.metric in ("terminal_expansion_opportunity", "demand_capacity_pressure")
        forecast = [self.forecast_baseline_year, self.forecast_edition, self.forecast_scenario,
                    self.forecast_baseline_scenario]
        if not uses_forecast and any(value is not None for value in forecast):
            raise ValueError("Forecast settings apply only to expansion or demand context")
        return self


class AirportResult(BaseModel):
    airport_id: int
    airport_code: str | None = None
    airport_name: str | None = None
    status: Status = "insufficient_evidence"
    values: dict[str, float | None] = Field(default_factory=dict)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    components: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    ranking_eligible: bool = False
    evidence_status: Literal["complete", "partial", "missing", "unverified"] | None = None
    rank: int | None = None


class AnalysisResult(BaseModel):
    metric: str
    settings: AnalysisRequest
    status: Status = "ok"
    airports: list[int] = Field(default_factory=list)
    periods: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    results: list[AirportResult] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    cohort_airport_ids: list[int] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    screening: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    national_eligibility: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    metric_definitions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forecast_metadata: dict[str, Any] = Field(default_factory=dict)
    answer_summary: dict[str, Any] = Field(default_factory=dict)
