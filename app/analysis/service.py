"""Basic airport analysis - automatic annual defaults and evidence for five airport metrics."""

from datetime import date
from pprint import pprint
from typing import Any, Dict, List

if __package__:
    from . import metrics
    from .dao_get_gold_data import get_gold_data
    from .evidence import describe_evidence
    from .models import AirportResult, AnalysisRequest, AnalysisResult
else:
    import metrics
    from dao_get_gold_data import get_gold_data
    from evidence import describe_evidence
    from models import AirportResult, AnalysisRequest, AnalysisResult

MIN_PASSENGERS = 10_000
MIN_FLIGHTS = 1_000
FORECAST_CATEGORY = "gold-boardings-and-operations-v1"
UNITS = {
    "traffic_growth": {"baseline": "passengers", "end": "passengers", "absolute_change": "passengers",
                       "growth_pct": "%", "cagr_pct": "%"},
    "airport_operational_pressure": {"disrupted_flights": "flights", "classifiable_flights": "flights",
                                     "scheduled_flights": "flights", "arrival_disruption_pct": "%"},
    "outbound_long_haul_share": {"long_haul_departures": "departures", "distance_eligible_departures": "departures",
                                "observed_departures": "departures", "long_haul_share_pct": "%"},
    "demand_capacity_pressure": {"baseline_passengers": "passengers", "end_passengers": "passengers",
                                 "baseline_seats": "seats", "end_seats": "seats", "baseline_ratio_pct": "%",
                                 "end_ratio_pct": "%", "ratio_change_pp": "pp", "passenger_growth_pct": "%",
                                 "seat_growth_pct": "%", "passenger_seat_growth_gap_pp": "pp"},
    "terminal_expansion_opportunity": {"historical_cagr_pct": "%", "forecast_boarding_additions": "boardings",
                                      "arrival_disruption_pct": "%", "historical_percentile": "%",
                                      "forecast_percentile": "%", "operational_percentile": "%",
                                      "historical_contribution": "points", "forecast_contribution": "points",
                                      "operational_contribution": "points", "score": "points"},
}

UNITS["airport_operational_pressure"].update({
    "arrival_delay_observed_flights": "flights", "arrival_delayed_15_flights": "flights",
    "positive_arrival_delay_minutes": "minutes", "arrival_delay_rate_pct": "%",
    "mean_positive_arrival_delay_minutes": "minutes", "cancelled_flights": "flights", "diverted_flights": "flights",
    "cancellation_rate_pct": "%", "departing_passengers": "passengers", "offered_seats": "seats", "departures": "departures",
})
UNITS["demand_capacity_pressure"].update(UNITS["airport_operational_pressure"])
UNITS["demand_capacity_pressure"].update(UNITS["traffic_growth"])
UNITS["demand_capacity_pressure"].update(baseline="boardings", end="boardings", absolute_change="boardings")
for cause in ["carrier", "weather", "nas", "security", "late_aircraft"]:
    UNITS["airport_operational_pressure"][f"{cause}_delay_minutes"] = "minutes"
    UNITS["demand_capacity_pressure"][f"{cause}_delay_minutes"] = "minutes"


def _prepare(request: AnalysisRequest) -> tuple[AnalysisResult, List[Dict[str, Any]]]:
    """Resolve annual defaults from data - explicit periods are never silently replaced."""
    dimension = get_gold_data(query="SELECT * FROM airport_dimension")
    airports = sorted(set(request.airport_ids or [row.get("canonical_airport_id") for row in dimension
                                                if (row.get("state_code") == request.state_code if request.state_code
                                                    else row.get("us_region") == request.region)]))
    result = AnalysisResult(metric=request.metric, settings=request, airports=airports)
    if not set(airports) <= {row.get("canonical_airport_id") for row in dimension}:
        result.status = "invalid_input"
        result.limitations.append("Unknown canonical airport ID")
        return result, dimension
    tables = get_gold_data(query="SELECT name FROM sqlite_master WHERE name='analysis_evidence'")
    evidence = get_gold_data(query="SELECT * FROM analysis_evidence") if tables else []
    inventory = get_gold_data(query="""
        SELECT 'activity' AS dataset, origin_airport_id AS airport_id,
               CAST(substr(reporting_month,1,4) AS INTEGER) AS year,
               COUNT(DISTINCT reporting_month) AS months
        FROM route_activity_monthly WHERE service_class='F' GROUP BY 2,3
        UNION ALL
        SELECT 'performance', airport_id, CAST(substr(flight_date,1,4) AS INTEGER),
               COUNT(DISTINCT substr(flight_date,1,7))
        FROM airport_performance_daily WHERE airport_role='destination' GROUP BY 2,3
    """)
    expansion = request.metric == "terminal_expansion_opportunity"
    comparison = request.metric in ("traffic_growth", "demand_capacity_pressure", "terminal_expansion_opportunity")
    dataset = "performance" if request.metric == "airport_operational_pressure" else "activity"
    verified = {(row.get("dataset"), row.get("year")) for row in evidence
                if row.get("complete") and row.get("period_type") == "calendar"}
    broad_search = request.state_code is not None or request.region is not None
    available = {}
    for source in ["activity", "performance"]:
        candidates = {row.get("year") for row in inventory if row.get("dataset") == source
                      and row.get("year") < date.today().year}
        available[source] = []
        for year in sorted(candidates):
            rows = [row for row in inventory if row.get("dataset") == source and row.get("year") == year]
            observed = {row.get("airport_id") for row in rows}
            attestations = [row for row in evidence if row.get("dataset") == source and row.get("year") == year]
            enough = (source, year) in verified or not attestations and any(row.get("months") == 12 for row in rows)
            population_available = bool(set(airports) & observed) if broad_search else set(airports) <= observed
            if enough and (expansion or not airports or population_available):
                available[source].append(year)
    end_years = available[dataset]
    if comparison:
        end_years = [year for year in end_years if any(prior < year for prior in available["activity"])]
    period_pairs = []
    if broad_search and comparison and not expansion and airports:
        observed_by_year = {year: {row.get("airport_id") for row in inventory
                                  if row.get("dataset") == "activity" and row.get("year") == year}
                            for year in available["activity"]}
        period_pairs = [(start, end) for end in end_years for start in available["activity"]
                        if start < end and (request.baseline_year is None or start == request.baseline_year)
                        and set(airports) & observed_by_year[start] & observed_by_year[end]]
        end_years = sorted({end for _, end in period_pairs})
    if expansion:
        end_years = [year for year in end_years if year in available["performance"]]
    year = request.year if request.year is not None else max(end_years, default=None)
    baseline = request.baseline_year
    if comparison and baseline is None and year is not None:
        priors = ([start for start, end in period_pairs if end == year]
                  if broad_search and not expansion and airports
                  else [prior for prior in available["activity"] if prior < year])
        baseline = max(priors, default=None)
    if year is None or comparison and (baseline is None or baseline >= year):
        result.status = "insufficient_evidence"
        result.limitations.append("No common annual periods available; specify years only to inspect a particular period")
        return result, dimension
    request = request.model_copy(update={"year": year, "baseline_year": baseline})
    years = [baseline, year] if comparison else [year]
    result.periods = [{"year": value, "kind": "calendar"} for value in years]
    required = [(dataset, value) for value in years]
    if expansion or request.metric == "demand_capacity_pressure":
        required.append(("performance", year))
    for source, value in required:
        matches = [row for row in evidence if row.get("dataset") == source and row.get("year") == value
                   and row.get("period_type") == "calendar"]
        if matches:
            result.sources += matches
        else:
            months = max((row.get("months") for row in inventory if row.get("dataset") == source
                          and row.get("year") == value), default=0)
            result.sources.append({"dataset": source, "year": value, "complete": False,
                                   "months_present": months, "source": "Observed Gold data; source inventory unverified"})
    if expansion or request.metric == "demand_capacity_pressure":
        historical = [row for row in evidence if row.get("dataset") == "outlook"
                      and row.get("period_type") == "historical" and row.get("category") == FORECAST_CATEGORY]
        windows = []
        for start in historical:
            for end in evidence:
                valid = (end.get("dataset") == "outlook" and end.get("period_type") == "forecast"
                         and end.get("year") == start.get("year") + 5 and end.get("edition") == start.get("edition")
                         and end.get("category") == FORECAST_CATEGORY)
                if not valid:
                    continue
                filters = [(request.forecast_baseline_year, start.get("year")),
                           (request.forecast_edition, start.get("edition")),
                           (request.forecast_baseline_scenario, str(start.get("scenario"))),
                           (request.forecast_scenario, str(end.get("scenario")))]
                if all(wanted is None or wanted == actual for wanted, actual in filters):
                    windows.append((start, end))
        windows.sort(key=lambda pair: (bool(pair[0].get("complete") and pair[1].get("complete")),
                                       pair[0].get("edition"), pair[0].get("year")), reverse=True)
        if windows:
            start, end = windows[0]
            ambiguous = any(pair[0].get("edition") == start.get("edition") and pair[0].get("year") == start.get("year")
                            and (pair[0].get("scenario"), pair[1].get("scenario")) != (start.get("scenario"), end.get("scenario"))
                            for pair in windows[1:])
            if not ambiguous:
                request = request.model_copy(update={"forecast_baseline_year": start.get("year"),
                    "forecast_edition": start.get("edition"), "forecast_baseline_scenario": str(start.get("scenario")),
                    "forecast_scenario": str(end.get("scenario"))})
                result.sources += [start, end]
                result.periods += [{"year": row.get("year"), "kind": "fiscal", "edition": row.get("edition"),
                                    "scenario": str(row.get("scenario")), "period_type": row.get("period_type")}
                                   for row in [start, end]]
        if not any(period.get("kind") == "fiscal" for period in result.periods):
            request = request.model_copy(update={"forecast_baseline_year": None})
            result.limitations.append("Forecast context unavailable: no unambiguous verified historical/forecast window")
    result.settings = request
    return result, dimension


def _measure(request: AnalysisRequest, airports: List[int]) -> List[AirportResult]:
    """Aggregate eligible Gold populations - comparisons use only the requested endpoints."""
    years = [request.baseline_year, request.year] if request.baseline_year is not None else [request.year]
    parameters = {"baseline": years[0], "year": request.year}
    if request.metric == "forecast":
        if request.forecast_baseline_year is None:
            return [AirportResult(airport_id=airport, exclusions=["Verified forecast window unavailable"]) for airport in airports]
        years = [request.forecast_baseline_year, request.forecast_baseline_year + 5]
        parameters = {"baseline": years[0], "year": years[1], "edition": request.forecast_edition,
                      "baseline_scenario": request.forecast_baseline_scenario, "scenario": request.forecast_scenario}
        query = """
            SELECT airport_id, fiscal_year AS year, total_boardings AS total, 1 AS observed,
                   CASE WHEN total_boardings>=0 THEN 1 ELSE 0 END AS eligible
            FROM airport_outlook_annual WHERE taf_edition=:edition AND (
                (fiscal_year=:baseline AND CAST(scenario AS TEXT)=:baseline_scenario) OR
                (fiscal_year=:year AND CAST(scenario AS TEXT)=:scenario))
        """
    elif request.metric == "airport_operational_pressure":
        query = """
            SELECT airport_id, CAST(substr(flight_date,1,4) AS INTEGER) AS year,
                   SUM(scheduled_flights) AS observed, SUM(arrival_disruption_flights) AS numerator,
                   SUM(arrival_disruption_classifiable_flights) AS eligible,
                   SUM(cancelled_flights) AS cancelled_flights, SUM(diverted_flights) AS diverted_flights,
                   SUM(arrival_delay_observed_flights) AS arrival_delay_observed_flights,
                   SUM(arrival_delayed_15_flights) AS arrival_delayed_15_flights,
                   SUM(positive_arrival_delay_minutes) AS positive_arrival_delay_minutes,
                   SUM(attribution_eligible_flights) AS attribution_eligible_flights,
                   SUM(attribution_complete_flights) AS attribution_complete_flights,
                   SUM(carrier_delay_minutes) AS carrier_delay_minutes, SUM(weather_delay_minutes) AS weather_delay_minutes,
                   SUM(nas_delay_minutes) AS nas_delay_minutes, SUM(security_delay_minutes) AS security_delay_minutes,
                   SUM(late_aircraft_delay_minutes) AS late_aircraft_delay_minutes
            FROM airport_performance_daily
            WHERE CAST(substr(flight_date,1,4) AS INTEGER)=:year AND airport_role='destination'
            GROUP BY airport_id, substr(flight_date,1,4)
        """
    else:
        if request.metric == "traffic_growth":
            fields = "SUM(passengers) AS total, SUM(passenger_observation_count) AS eligible"
            observed = "SUM(source_record_count) AS observed"
        elif request.metric == "demand_capacity_pressure":
            fields = ("SUM(ratio_eligible_passengers) AS passengers, SUM(ratio_eligible_seats) AS seats, "
                      "SUM(paired_observation_count) AS eligible")
            observed = "SUM(source_record_count) AS observed"
        else:
            fields = ("SUM(distance_eligible_departures) AS eligible, "
                      "SUM(source_record_count)-SUM(departures_observation_count) AS unknown, "
                      "SUM(CASE WHEN distance_miles>=2000 THEN distance_eligible_departures ELSE 0 END) AS numerator")
            observed = "SUM(departures) AS observed"
        query = f"""
            SELECT origin_airport_id AS airport_id, CAST(substr(reporting_month,1,4) AS INTEGER) AS year,
                   {fields}, {observed}
            FROM route_activity_monthly
            WHERE CAST(substr(reporting_month,1,4) AS INTEGER) IN (:baseline,:year) AND service_class='F'
            GROUP BY origin_airport_id, substr(reporting_month,1,4)
        """
    rows = get_gold_data(query=query, parameters=parameters)
    if request.metric == "airport_operational_pressure":
        traffic = get_gold_data(query="""
            SELECT origin_airport_id AS airport_id, SUM(passengers) AS departing_passengers,
                   SUM(seats) AS offered_seats, SUM(departures) AS departures,
                   SUM(source_record_count) AS traffic_records, SUM(passenger_observation_count) AS passenger_records,
                   SUM(seat_observation_count) AS seat_records
            FROM route_activity_monthly WHERE CAST(substr(reporting_month,1,4) AS INTEGER)=:year AND service_class='F'
            GROUP BY origin_airport_id
        """, parameters={"year": request.year})
        traffic_by_airport = {row.get("airport_id"): row for row in traffic}
        for row in rows:
            row.update(traffic_by_airport.get(row.get("airport_id"), {}))
    grouped = {(row.get("airport_id"), row.get("year")): row for row in rows}
    results = []
    for airport in airports:
        observations = [grouped.get((airport, year), {}) for year in years]
        results.append(_airport_result(request=request, airport=airport, rows=observations))
    return results


def _airport_result(request: AnalysisRequest, airport: int, rows: List[Dict[str, Any]]) -> AirportResult:
    """Calculate one airport - partial coverage stays descriptive and cannot enter rankings."""
    item = AirportResult(airport_id=airport)
    first, last = rows[0], rows[-1]
    minimum, unit = True, "records"
    if any(not row or row.get("eligible") is None or row.get("observed") is None for row in rows):
        item.exclusions.append("Missing mandatory observations")
        return item
    if request.metric in ("traffic_growth", "forecast"):
        totals = {"baseline": first.get("total"), "end": last.get("total")}
        if None not in totals.values():
            years = 5 if request.metric == "forecast" else request.year - request.baseline_year
            item.values = {**totals, **metrics.traffic_growth(**totals, years=years)}
            minimum = request.metric == "forecast" or first.get("total") >= MIN_PASSENGERS
    elif request.metric == "demand_capacity_pressure":
        totals = {"baseline_passengers": first.get("passengers"), "end_passengers": last.get("passengers"),
                  "baseline_seats": first.get("seats"), "end_seats": last.get("seats")}
        if None not in totals.values():
            item.values = {**totals, **metrics.demand_capacity_pressure(**totals)}
            minimum = first.get("passengers") >= MIN_PASSENGERS
    elif request.metric == "airport_operational_pressure":
        unit = "flights"
        totals = {"disrupted_flights": last.get("numerator"), "classifiable_flights": last.get("eligible")}
        if None not in totals.values():
            item.values = {**totals, "scheduled_flights": last.get("observed"),
                           **metrics.airport_operational_pressure(**totals)}
            minimum = last.get("observed") >= MIN_FLIGHTS
    else:
        unit = "departures"
        totals = {"long_haul_departures": last.get("numerator"), "distance_eligible_departures": last.get("eligible")}
        if None not in totals.values():
            item.values = {**totals, "observed_departures": last.get("observed"),
                           **metrics.outbound_long_haul_share(**totals)}
    if not item.values:
        item.exclusions.append("Missing mandatory measurement")
        return item
    for row in rows:
        eligible, observed = row.get("eligible"), row.get("observed")
        coverage = {"year": row.get("year"), "eligible": eligible, "observed": observed, "unit": unit,
                    "pct": 100 * eligible / observed if observed else None}
        if unit == "departures":
            coverage["unknown_records"] = row.get("unknown", 0)
        item.coverage.append(coverage)
    complete = all(row.get("observed") > 0 and row.get("eligible") == row.get("observed")
                   and not row.get("unknown", 0) for row in rows)
    item.status = "undefined" if None in item.values.values() else "ok" if complete else "partial"
    item.ranking_eligible = item.status == "ok" and minimum
    if not complete:
        item.exclusions.append("Incomplete measurement coverage")
    if item.status == "undefined":
        item.exclusions.append("Zero denominator")
    if not minimum:
        item.exclusions.append("Below ranking volume minimum")
    if request.metric == "airport_operational_pressure":
        observed_arrivals = last.get("arrival_delay_observed_flights")
        scheduled = last.get("observed")
        attributed = last.get("attribution_complete_flights")
        eligible_attribution = last.get("attribution_eligible_flights")
        positive_minutes = last.get("positive_arrival_delay_minutes")
        delayed = last.get("arrival_delayed_15_flights")
        cancelled = last.get("cancelled_flights")
        panel = {"arrival_delay_observed_flights": observed_arrivals, "arrival_delayed_15_flights": delayed,
                 "positive_arrival_delay_minutes": positive_minutes,
                 "arrival_delay_rate_pct": 100 * delayed / observed_arrivals if observed_arrivals and delayed is not None else None,
                 "mean_positive_arrival_delay_minutes": positive_minutes / observed_arrivals if observed_arrivals and positive_minutes is not None else None,
                 "cancelled_flights": cancelled, "diverted_flights": last.get("diverted_flights"),
                 "cancellation_rate_pct": 100 * cancelled / scheduled if scheduled and cancelled is not None else None,
                 "departing_passengers": last.get("departing_passengers"), "offered_seats": last.get("offered_seats"),
                 "departures": last.get("departures")}
        item.values.update(panel)
        causes = {f"{name}_delay_minutes": last.get(f"{name}_delay_minutes")
                  for name in ["carrier", "weather", "nas", "security", "late_aircraft"]}
        item.components["reported_delay_causes"] = causes
        item.coverage += [{"measurement": "arrival_delay", "eligible": observed_arrivals,
                           "observed": scheduled, "pct": 100 * observed_arrivals / scheduled if scheduled and observed_arrivals is not None else None},
                          {"measurement": "delay_attribution", "eligible": attributed, "observed": eligible_attribution,
                           "pct": 100 * attributed / eligible_attribution if eligible_attribution and attributed is not None else None},
                          {"measurement": "traffic_passengers", "eligible": last.get("passenger_records"),
                           "observed": last.get("traffic_records")},
                          {"measurement": "traffic_seats", "eligible": last.get("seat_records"),
                           "observed": last.get("traffic_records")}]
    return item


def _score(result: AnalysisResult, dimension: List[Dict[str, Any]]) -> None:
    """Score the eligible national cohort - regional filtering never changes normalization."""
    request, airports = result.settings, result.airports
    national = sorted(row.get("canonical_airport_id") for row in dimension if row.get("country_code") == "US")
    historical_request = request.model_copy(update={"metric": "traffic_growth"})
    operational_request = request.model_copy(update={"metric": "airport_operational_pressure", "baseline_year": None})
    historical = _measure(request=historical_request, airports=national)
    operational = _measure(request=operational_request, airports=national)
    forecast_request = request.model_copy(update={"metric": "forecast"})
    forecasts = _measure(request=forecast_request, airports=national)
    result.weights = {"historical": 0.4, "forecast": 0.4, "operational": 0.2}
    result.screening = {
        "name": "Growth-led expansion screening",
        "eligibility_policy": "Positive historical passenger growth and positive forecast boarding additions; "
                              "complete mandatory measurements and verified sources; at least "
                              f"{MIN_PASSENGERS:,} baseline passengers and {MIN_FLIGHTS:,} scheduled arrivals.",
        "reference_population": "Eligible US airports; percentiles and ranks are national, before regional filtering.",
        "historical_period": {"kind": "calendar", "baseline_year": request.baseline_year, "end_year": request.year},
        "operational_period": {"kind": "calendar", "year": request.year},
        "forecast_period": {"kind": "fiscal", "baseline_year": request.forecast_baseline_year,
                            "end_year": request.forecast_baseline_year + 5 if request.forecast_baseline_year is not None else None,
                            "taf_edition": request.forecast_edition,
                            "baseline_scenario": request.forecast_baseline_scenario, "scenario": request.forecast_scenario},
        "score_explanation": "Weighted national percentiles: 40% historical passenger CAGR, "
                             "40% absolute forecast boarding additions, 20% arrival disruption. "
                             "Higher disruption increases the screening score; disruption does not establish terminal congestion.",
        "exclusion_interpretation": "Exclusion under these rules does not establish absence of expansion needs.",
    }
    candidates = []
    reasons = {}
    for h, o, f in zip(historical, operational, forecasts):
        item = AirportResult(airport_id=h.airport_id, status="ineligible", coverage=h.coverage + o.coverage,
                             components={"historical": h.values, "operational": o.values},
                             exclusions=h.exclusions + o.exclusions)
        baseline, endpoint = f.values.get("baseline"), f.values.get("end")
        forecast_ok = baseline is not None and endpoint is not None and baseline >= 0 and endpoint >= 0
        item.components["forecast"] = f.values
        item.coverage += f.coverage
        item.exclusions += f.exclusions
        positive = forecast_ok and endpoint > baseline and (h.values.get("cagr_pct") or 0) > 0
        if not positive:
            item.exclusions.append("Positive historical growth and forecast additions are required")
        verified = all(source.get("complete") for source in result.sources)
        measurements = [h, o, f]
        item.evidence_status = (
            "missing" if any(not component.values for component in measurements)
            else "unverified" if not verified
            else "partial" if any(component.status in ("partial", "undefined") for component in [h, o])
            else "complete"
        )
        for name, component in zip(["historical", "operational", "forecast"], measurements):
            for reason in set(component.exclusions):
                if name == "forecast" and reason == "Zero denominator":
                    continue  # Forecast eligibility uses absolute additions, not percentage growth.
                reasons.setdefault(f"{name}: {reason}", set()).add(item.airport_id)
        if h.values.get("cagr_pct") is not None and h.values["cagr_pct"] <= 0:
            reasons.setdefault("Nonpositive historical growth", set()).add(item.airport_id)
        if forecast_ok and endpoint <= baseline:
            reasons.setdefault("Nonpositive forecast boarding additions", set()).add(item.airport_id)
        if h.ranking_eligible and o.ranking_eligible and positive and verified:
            item.status, item.ranking_eligible = "ok", True
            item.values = {"historical_cagr_pct": h.values.get("cagr_pct"),
                           "forecast_boarding_additions": endpoint - baseline,
                           "arrival_disruption_pct": o.values.get("arrival_disruption_pct")}
        if not verified:
            item.exclusions.append("Source inventory or forecast semantics unverified; excluded from ranking")
            reasons.setdefault("Source completeness unverified", set()).add(item.airport_id)
        candidates.append(item)
    cohort = [item for item in candidates if item.ranking_eligible]
    result.cohort_airport_ids = sorted(item.airport_id for item in cohort)
    excluded_ids = {item.airport_id for item in candidates if not item.ranking_eligible}
    result.national_eligibility = {
        "total_airports": len(national), "eligible_airports": len(cohort),
        "excluded_airports": len(national) - len(cohort),
        "exclusions_by_reason": {reason: {"count": len(ids & excluded_ids), "airport_ids": sorted(ids & excluded_ids)}
                                 for reason, ids in sorted(reasons.items()) if ids & excluded_ids},
        "counting_note": "Each airport counts once per reason; reasons overlap and must not be summed.",
    }
    result.screening["reference_cohort_size"] = len(cohort)
    fields = {"historical": "historical_cagr_pct", "forecast": "forecast_boarding_additions",
              "operational": "arrival_disruption_pct"}
    for item in cohort:
        percentiles = {}
        for name, field in fields.items():
            lower = sum(peer.values.get(field) < item.values.get(field) for peer in cohort)
            equal = sum(peer.values.get(field) == item.values.get(field) for peer in cohort)
            percentiles[f"{name}_percentile"] = 100 * (lower + (equal - 1) / 2) / (len(cohort) - 1) if len(cohort) > 1 else 50
        item.values.update(**percentiles, **metrics.terminal_expansion_opportunity(**percentiles))
    cohort.sort(key=lambda item: (-item.values.get("score"), item.airport_id))
    for index, item in enumerate(cohort):
        item.rank = index + 1 if index == 0 or item.values.get("score") != cohort[index - 1].values.get("score") else cohort[index - 1].rank
    result.results = [item for item in cohort if item.airport_id in airports]
    result.results += [item for item in candidates if not item.ranking_eligible and item.airport_id in airports]
    result.results += [AirportResult(airport_id=airport, status="ineligible", exclusions=["Outside the US reference population"])
                       for airport in airports if airport not in national]
    result.evidence_summary = {
        "scope": "Mandatory scoring inputs for selected airports; supplementary panels retain their own coverage.",
        "airport_counts": {status: sum(item.evidence_status == status for item in result.results)
                           for status in ["complete", "partial", "missing", "unverified"]},
        "outside_reference_population": sum(item.airport_id not in national for item in result.results),
        "source_inventory_verified": all(source.get("complete") for source in result.sources),
        "coverage_note": "Source inventory completeness covers configured sources, not all-airline coverage.",
    }
    if not cohort:
        result.limitations.append("No eligible national reference cohort; no ranking produced.")
    if len(cohort) == 1:
        result.limitations.append("Singleton reference cohort; every percentile is 50")


def lookup_airports(request: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find airport IDs by state/code or name substring - supplied filters combine with AND."""
    filters = []
    parameters = {}
    query = "SELECT canonical_airport_id, airport_code, name FROM airport_dimension"
    for field in ("state_code", "name", "airport_code"):
        value = request.get(field)
        if value is None:
            continue
        if not value.strip():
            raise ValueError("Airport lookup filters must not be blank")
        parameters[field] = value.strip()
        filters.append(f"instr(lower({field}), lower(:{field})) > 0" if field == "name"
                       else f"{field} = :{field} COLLATE NOCASE")
    if not filters:
        raise ValueError("Supply state_code, name, or airport_code")
    query += " WHERE " + " AND ".join(filters) + " ORDER BY canonical_airport_id"
    return get_gold_data(query=query, parameters=parameters)


def analyze(request: AnalysisRequest | Dict[str, Any]) -> AnalysisResult:
    """Analyze an airport question - periods default automatically and limitations travel with measurements."""
    request = AnalysisRequest.model_validate(request)
    result, dimension = _prepare(request)
    if result.status != "ok":
        return result
    request = result.settings
    if request.metric == "terminal_expansion_opportunity":
        _score(result=result, dimension=dimension)
    else:
        result.results = _measure(request=request, airports=result.airports)
        dataset = "performance" if request.metric == "airport_operational_pressure" else "activity"
        verified = all(source.get("complete") for source in result.sources if source.get("dataset") == dataset)
        if not verified:
            result.limitations.append("Descriptive results use observed records; source completeness is unverified")
            for item in result.results:
                item.ranking_eligible = False
                if item.status == "ok":
                    item.status = "partial"
                item.exclusions.append("Source completeness unverified; excluded from ranking")
        if request.metric == "demand_capacity_pressure":
            operational = request.model_copy(update={"metric": "airport_operational_pressure", "baseline_year": None})
            forecast = request.model_copy(update={"metric": "forecast"})
            operational_results = _measure(request=operational, airports=result.airports)
            forecast_results = _measure(request=forecast, airports=result.airports)
            for item, o, f in zip(result.results, operational_results, forecast_results):
                item.components.update(operational=o.values, forecast=f.values, **o.components)
                item.coverage += o.coverage + f.coverage
                if not f.values:
                    item.exclusions.append("Optional forecast context unavailable")
                if not o.values:
                    item.exclusions.append("Optional operational context unavailable")
    identities = {row.get("canonical_airport_id"): row for row in dimension}
    for item in result.results:
        identity = identities.get(item.airport_id, {})
        item.airport_code, item.airport_name = identity.get("airport_code"), identity.get("name")
    result.units = UNITS.get(request.metric, {}).copy()
    result.limitations += ["Traffic: outbound scheduled passenger service. Disruption: destination arrivals.",
                          "Delay severity is mean nonnegative arrival delay across observed completed arrivals.",
                          "Cause minutes cover eligible delayed flights with complete reported attribution; they do not establish causation.",
                          "Traffic, forecasts and passenger/seat ratios are indirect indicators; they cannot quantify unmet demand.",
                          "Expansion scores are screening evidence; feasibility, capacity and financial returns require investigation."]
    if request.metric == "outbound_long_haul_share":
        result.limitations.append("Long-haul: distance >=2,000 miles; service class F (scheduled passenger)")
    statuses = {item.status for item in result.results}
    result.status = ("ok" if request.metric == "terminal_expansion_opportunity"
                     else next(iter(statuses)) if len(statuses) == 1 else "partial" if statuses else "ok")
    describe_evidence(result)
    return result


if __name__ == "__main__":
    # Which airports in New England are strong terminal-expansion candidates?
    pprint(analyze({"metric": "terminal_expansion_opportunity", "region": "New England"}).model_dump(mode="json"))

    # How does congestion at Los Angeles International compare with Santa Ana?
    pprint(analyze({"metric": "airport_operational_pressure", "airport_ids": [12892, 14908]}).model_dump(mode="json"))

    # What percentage of Anchorage departures are long-haul?
    pprint(analyze({"metric": "outbound_long_haul_share", "airport_ids": [10299]}).model_dump(mode="json"))

    # What indirect demand-pressure indicators and context are available for San Francisco?
    pprint(analyze({"metric": "demand_capacity_pressure", "airport_ids": [14771]}).model_dump(mode="json"))

    # How has San Francisco's departing passenger traffic grown?
    pprint(analyze({"metric": "traffic_growth", "airport_ids": [14771]}).model_dump(mode="json"))

    # Test-set Q5: Which Texas airports are seeing passenger traffic grow faster than seat capacity?
    # Compare passenger_seat_growth_gap_pp > 0 for ranking-eligible airports.
    texas_airports = [row["canonical_airport_id"] for row in get_gold_data(
        query="SELECT canonical_airport_id FROM airport_dimension WHERE state_code='TX'")]
    pprint(analyze({"metric": "demand_capacity_pressure", "airport_ids": texas_airports}).model_dump(mode="json"))

    # Test-set Q6: At San Francisco, are delays mainly attributed to weather, airlines or the NAS?
    # Compare components.reported_delay_causes, including security and late aircraft, with attribution coverage.
    pprint(analyze({"metric": "airport_operational_pressure", "airport_ids": [14771]}).model_dump(mode="json"))

    # Test-set Q9: Which busy California airports expect strong growth and already have frequent arrival delays?
    # This returns screening inputs; a busy threshold and a combined ranking rule still need to be applied.
    california_airports = [row["canonical_airport_id"] for row in get_gold_data(
        query="SELECT canonical_airport_id FROM airport_dimension WHERE state_code='CA'")]
    pprint(analyze({"metric": "demand_capacity_pressure", "airport_ids": california_airports}).model_dump(mode="json"))

    # Test-set Q24: Which mid-sized airports expect the most additional boardings over five forecast years?
    # Forecast components provide baseline/end/absolute_change; define a size band before filtering and ranking.
    # Midwest is an example search scope; repeat for other regions for a national search.
    pprint(analyze({"metric": "demand_capacity_pressure", "region": "Midwest"}).model_dump(mode="json"))

    # Test-set Q26: How does Tampa's passenger growth compare with similar-sized Florida airports?
    # Includes Tampa (15304); select peers using a baseline-passenger size band before comparing growth.
    florida_airports = [row["canonical_airport_id"] for row in get_gold_data(
        query="SELECT canonical_airport_id FROM airport_dimension WHERE state_code='FL'")]
    pprint(analyze({"metric": "demand_capacity_pressure", "airport_ids": florida_airports}).model_dump(mode="json"))
