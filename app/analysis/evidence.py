"""Presentation metadata that preserves the meaning of deterministic measurements."""

if __package__:
    from .models import AnalysisResult
else:
    from models import AnalysisResult


DEFINITIONS = {
    "mean_positive_arrival_delay_minutes": {
        "label": "Nonnegative arrival delay per observed completed arrival",
        "numerator": "positive_arrival_delay_minutes",
        "denominator": "arrival_delay_observed_flights",
        "unit": "minutes per observed completed arrival",
        "population": "Completed, nondiverted destination arrivals with observed delay, including on-time and early arrivals",
    },
    "arrival_delay_rate_pct": {
        "numerator": "arrival_delayed_15_flights", "denominator": "arrival_delay_observed_flights",
        "unit": "%", "population": "Observed completed destination arrivals; late means at least 15 minutes",
    },
    "arrival_disruption_pct": {
        "numerator": "disrupted_flights", "denominator": "classifiable_flights", "unit": "%",
        "population": "Destination arrivals with known outcomes; cancelled, diverted or at least 15 minutes late, counted once",
    },
    "cancellation_rate_pct": {
        "numerator": "cancelled_flights", "denominator": "scheduled_flights", "unit": "%",
        "population": "Reported scheduled destination arrivals",
    },
    "long_haul_share_pct": {
        "numerator": "long_haul_departures", "denominator": "distance_eligible_departures", "unit": "%",
        "population": "Outbound scheduled passenger service class F with valid distance; long-haul >=2,000 miles; excludes cargo-only service",
    },
    "baseline_ratio_pct": {
        "numerator": "baseline_passengers", "denominator": "baseline_seats", "unit": "%",
        "population": "Paired valid passenger/seat records for outbound scheduled passenger service in baseline calendar year",
    },
    "end_ratio_pct": {
        "numerator": "end_passengers", "denominator": "end_seats", "unit": "%",
        "population": "Paired valid passenger/seat records for outbound scheduled passenger service in endpoint calendar year",
    },
    "passenger_growth_pct": {
        "formula": "100 * (end_passengers / baseline_passengers - 1)", "unit": "%",
        "population": "Paired valid passenger/seat records for outbound scheduled passenger service",
    },
    "seat_growth_pct": {
        "formula": "100 * (end_seats / baseline_seats - 1)", "unit": "%",
        "population": "Same paired records as passenger growth",
    },
    "passenger_seat_growth_gap_pp": {
        "formula": "passenger_growth_pct - seat_growth_pct", "unit": "percentage points",
        "interpretation": "Positive gap alone can include declining passengers; require positive passenger growth when describing growing airports",
    },
    "ratio_change_pp": {"formula": "end_ratio_pct - baseline_ratio_pct", "unit": "percentage points"},
    "score": {"unit": "screening points (0–100), not a percentile", "formula": "0.4 * historical_percentile + 0.4 * forecast_percentile + 0.2 * operational_percentile"},
    "forecast_boarding_additions": {
        "unit": "additional annual boardings at fiscal endpoint", "formula": "endpoint annual boardings - baseline annual boardings",
        "interpretation": "Endpoint annual difference, not cumulative passengers",
    },
    "reported_delay_causes": {
        "unit": "attributed minutes", "population": "Eligible arrivals delayed >=15 minutes with complete reported cause attribution",
        "interpretation": "Reported attribution does not establish infrastructure causation",
    },
}
ORIGINAL_DATASETS = {
    "activity": "BTS T-100 Segment (All Carriers)",
    "performance": "BTS Reporting Carrier On-Time Performance",
    "outlook": "FAA Terminal Area Forecast (TAF)",
}


def describe_evidence(result: AnalysisResult) -> None:
    """Attach definitions and a compact answer contract without changing metric values."""
    fields = set(result.units)
    if result.metric in ("airport_operational_pressure", "demand_capacity_pressure"):
        fields.add("reported_delay_causes")
    result.metric_definitions = {key: value.copy() for key, value in DEFINITIONS.items() if key in fields}
    for definition in result.metric_definitions.values():
        definition["periods"] = [p for p in result.periods if p["kind"] == "calendar"]
    for source in result.sources:
        source["original_dataset"] = ORIGINAL_DATASETS.get(source.get("dataset"))
        source["processing_layer"] = "Gold aggregates derived from Silver"
        source["coverage_scope"] = "Configured source partitions; completeness does not establish coverage of every airline or flight"
    fiscal = [p for p in result.periods if p["kind"] == "fiscal"]
    if fiscal:
        baseline = next(p for p in fiscal if p["period_type"] == "historical")
        endpoint = next(p for p in fiscal if p["period_type"] == "forecast")
        result.forecast_metadata = {
            "edition": baseline["edition"], "baseline_label": f"FY{baseline['year']}",
            "endpoint_label": f"FY{endpoint['year']}", "baseline_year": baseline["year"],
            "endpoint_year": endpoint["year"], "endpoint_difference_unit": "additional annual boardings at endpoint",
            "edition_authority": "Returned edition metadata, separate from source URL and baseline year",
        }
        if "forecast_boarding_additions" in result.metric_definitions:
            result.metric_definitions["forecast_boarding_additions"]["periods"] = fiscal
    airports = [{
        "airport_id": item.airport_id, "airport_code": item.airport_code, "airport_name": item.airport_name,
        "status": item.status, "ranking_eligible": item.ranking_eligible, "evidence_status": item.evidence_status,
        "exclusions": item.exclusions, "measurement_coverage": item.coverage,
    } for item in result.results]
    leader = next((item for item in result.results if item.ranking_eligible and item.rank is not None), None)
    result.answer_summary = {
        "leading_candidate": ({"airport_id": leader.airport_id, "airport_code": leader.airport_code,
                               "score_points": leader.values.get("score"), "national_rank": leader.rank}
                              if leader else None),
        "airports": airports,
        "selection": {"state_code": result.settings.state_code, "region": result.settings.region,
                      "airport_count": len(result.airports)},
        "period_selection_policy": (
            "State/region searches use latest verified source periods with observed selected airports; missing airports remain individually classified. "
            "Named-airport comparisons require common observed periods. Explicit periods are preserved."
        ),
    }
    if result.metric == "demand_capacity_pressure":
        result.answer_summary["growing_faster_than_seats"] = [
            {"airport_id": item.airport_id, "airport_code": item.airport_code, **item.values}
            for item in sorted(result.results, key=lambda r: -(r.values.get("passenger_seat_growth_gap_pp") or 0))
            if item.ranking_eligible and (item.values.get("passenger_growth_pct") or 0) > 0
            and (item.values.get("passenger_seat_growth_gap_pp") or 0) > 0
        ]
        result.answer_summary["growth_filter"] = "Our screening model: positive passenger growth and positive passenger-seat growth gap; complete paired measurements, verified activity source, at least 10,000 baseline passengers."
