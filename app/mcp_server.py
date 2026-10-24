"""Airport MCP tools backed by the deterministic analysis service."""

from typing import Any, Dict, List

from analysis import service
from analysis.models import AnalysisResult
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP("Airport analysis", mask_error_details=True)


def lookup_airports(state_code: str | None = None, name: str | None = None,
                    airport_code: str | None = None) -> List[Dict[str, Any]]:
    """Find airport IDs by state/code or name substring - supplied filters combine with AND."""
    request = {"state_code": state_code, "name": name, "airport_code": airport_code}
    try:
        return service.lookup_airports(request=request)
    except ValueError as error:
        raise ToolError(str(error)) from error




def traffic_growth(
    airport_ids: List[int] | None = None,
    region: str | None = None,
    year: int | None = None,
    baseline_year: int | None = None,
    state_code: str | None = None,
) -> AnalysisResult:
    """Compare outbound passenger growth - defaults select available years; coverage accompanies results."""
    request = {
        "metric": "traffic_growth",
        "state_code": state_code,
        "airport_ids": airport_ids,
        "region": region,
        "year": year,
        "baseline_year": baseline_year,
    }
    return service.analyze(request=request)



def airport_operational_pressure(
    airport_ids: List[int] | None = None,
    region: str | None = None,
    year: int | None = None,
    state_code: str | None = None,
) -> AnalysisResult:
    """Compare arrival disruption, per-observed-arrival delay, cancellations and traffic volumes.

    Includes traffic and reported cause minutes; sufficient for operational airport comparisons.
    Do not fetch demand/forecast context unless the question requires it.
    Observed arrivals do not establish terminal capacity.
    """
    request = {
        "metric": "airport_operational_pressure",
        "state_code": state_code,
        "airport_ids": airport_ids,
        "region": region,
        "year": year,
    }
    return service.analyze(request=request)



def outbound_long_haul_share(
    airport_ids: List[int] | None = None,
    region: str | None = None,
    year: int | None = None,
    state_code: str | None = None,
) -> AnalysisResult:
    """Measure departure-weighted share at least 2,000 miles - scheduled passenger services only."""
    request = {
        "metric": "outbound_long_haul_share",
        "state_code": state_code,
        "airport_ids": airport_ids,
        "region": region,
        "year": year,
    }
    return service.analyze(request=request)



def demand_capacity_pressure(
    airport_ids: List[int] | None = None,
    region: str | None = None,
    year: int | None = None,
    baseline_year: int | None = None,
    forecast_baseline_year: int | None = None,
    forecast_edition: int | None = None,
    forecast_baseline_scenario: str | None = None,
    forecast_scenario: str | None = None,
    state_code: str | None = None,
) -> AnalysisResult:
    """Compare passenger and seat growth, ratios and growth gaps; includes operational causes and fiscal forecasts.

    Use state_code for a whole-state search; growing_faster_than_seats lists eligible positive-growth candidates.
    Operational/forecast context is already included: avoid duplicate calls.
    Ratios indicate pressure indirectly, never unmet demand.
    """
    request = {
        "metric": "demand_capacity_pressure",
        "state_code": state_code,
        "airport_ids": airport_ids,
        "region": region,
        "year": year,
        "baseline_year": baseline_year,
        "forecast_baseline_year": forecast_baseline_year,
        "forecast_edition": forecast_edition,
        "forecast_baseline_scenario": forecast_baseline_scenario,
        "forecast_scenario": forecast_scenario,
    }
    return service.analyze(request=request)



def terminal_expansion_opportunity(
    airport_ids: List[int] | None = None,
    region: str | None = None,
    year: int | None = None,
    baseline_year: int | None = None,
    forecast_baseline_year: int | None = None,
    forecast_edition: int | None = None,
    forecast_baseline_scenario: str | None = None,
    forecast_scenario: str | None = None,
    state_code: str | None = None,
) -> AnalysisResult:
    """Screen expansion candidates against national peers - scores do not establish feasibility or returns."""
    request = {
        "metric": "terminal_expansion_opportunity",
        "state_code": state_code,
        "airport_ids": airport_ids,
        "region": region,
        "year": year,
        "baseline_year": baseline_year,
        "forecast_baseline_year": forecast_baseline_year,
        "forecast_edition": forecast_edition,
        "forecast_baseline_scenario": forecast_baseline_scenario,
        "forecast_scenario": forecast_scenario,
    }
    return service.analyze(request=request)



SELECTION_DESCRIPTION = (
    "Choose exactly one: canonical airport_ids, state_code (two-letter US state), or region "
    "(New England, Middle Atlantic, Midwest, South, West). "
    "For state or regional searches use state_code or region directly; no lookup or manual ID list is needed. "
    "Use lookup_airports to resolve named airports. Preserve the requested geography. "
    "Omit years for service defaults; returned periods identify actual years. "
    "Use metric_definitions, forecast_metadata and answer_summary to preserve metric meanings and exclusions. "
    "Report original_dataset sources, affected measurement coverage and material limitations."
)
FORECAST_DESCRIPTION = (
    "Forecast baseline is fiscal; endpoint is five years later. "
    "Edition and scenario settings preserve service validation and defaults."
)

mcp.tool(lookup_airports)
for metric_tool in (traffic_growth, airport_operational_pressure, outbound_long_haul_share,
                    demand_capacity_pressure, terminal_expansion_opportunity):
    description = f"{metric_tool.__doc__} {SELECTION_DESCRIPTION}"
    if metric_tool in (demand_capacity_pressure, terminal_expansion_opportunity):
        description = f"{description} {FORECAST_DESCRIPTION}"
    mcp.tool(name_or_fn=metric_tool, description=description)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
