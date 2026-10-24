"""Pure airport metric formulas over caller-prepared, comparable numeric inputs."""

from math import isfinite
from typing import Dict

PERCENT = 100
HISTORICAL_WEIGHT = 0.40
FORECAST_WEIGHT = 0.40
OPERATIONAL_WEIGHT = 0.20


def _validate_numbers(**values: float) -> None:
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite, nonnegative number")
        if not isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite, nonnegative number")


def traffic_growth(baseline: float, end: float, years: float = 1) -> Dict[str, float | None]:
    """Measure traffic or capacity change between two comparable periods.

    baseline and end are observed totals of the same measurement and unit;
    years is the positive elapsed time between comparable annual endpoints.
    The caller verifies matching populations and complete periods.

    Returns absolute_change = end - baseline in the input unit,
    growth_pct = 100 * (end / baseline - 1), and
    cagr_pct = 100 * ((end / baseline) ** (1 / years) - 1).
    Percentages use percent units (10 means 10%) and are not rounded. A zero baseline
    makes both percentage outputs None while preserving absolute_change.
    A zero end with a positive baseline gives -100% growth and CAGR.
    Invalid numbers or nonpositive years raise ValueError.
    """
    _validate_numbers(baseline=baseline, end=end, years=years)
    if years == 0:
        raise ValueError("years must be greater than zero")
    return {
        "absolute_change": end - baseline,
        "growth_pct": PERCENT * (end / baseline - 1) if baseline > 0 else None,
        "cagr_pct": PERCENT * ((end / baseline) ** (1 / years) - 1) if baseline > 0 else None,
    }


def airport_operational_pressure(
    disrupted_flights: float, classifiable_flights: float,
) -> Dict[str, float | None]:
    """Measure observed arrival disruption as an operational-pressure proxy.

    disrupted_flights counts flights that are cancelled, diverted, or completed
    and arriving at least 15 minutes late, counting each flight only once.
    classifiable_flights is the matching
    population with known arrival outcomes, not all scheduled flights.
    The caller supplies counts for the same airport, role, and period.

    Returns arrival_disruption_pct = 100 * disrupted_flights /
    classifiable_flights, without rounding. A zero denominator returns None.
    Negative or nonfinite inputs raise ValueError. This rate does not
    directly measure runway capacity, terminal capacity, or delay causes.
    """
    _validate_numbers(disrupted_flights=disrupted_flights, classifiable_flights=classifiable_flights)
    if disrupted_flights > classifiable_flights:
        raise ValueError("disrupted_flights cannot exceed classifiable_flights")
    return {
        "arrival_disruption_pct": (
            PERCENT * disrupted_flights / classifiable_flights if classifiable_flights > 0 else None
        ),
    }


def outbound_long_haul_share(
    long_haul_departures: float, distance_eligible_departures: float,
) -> Dict[str, float | None]:
    """Measure the departure-weighted share of outbound long-haul service.

    long_haul_departures is the eligible departure count meeting the caller's
    distance threshold (the spec default is distance >= 2,000 miles).
    distance_eligible_departures counts the same eligible population with valid distance,
    including both short- and long-haul departures. The caller prepares
    these counts using matching periods, service classes, and filters.

    Returns long_haul_share_pct = 100 * long_haul_departures /
    distance_eligible_departures, without rounding. A zero denominator returns None.
    Negative or nonfinite inputs raise ValueError. The result weights
    departures, rather than passengers or the number of source rows.
    """
    _validate_numbers(
        long_haul_departures=long_haul_departures,
        distance_eligible_departures=distance_eligible_departures,
    )
    if long_haul_departures > distance_eligible_departures:
        raise ValueError("long_haul_departures cannot exceed distance_eligible_departures")
    return {
        "long_haul_share_pct": (
            PERCENT * long_haul_departures / distance_eligible_departures
            if distance_eligible_departures > 0 else None
        ),
    }


def demand_capacity_pressure(
    baseline_passengers: float, end_passengers: float, baseline_seats: float, end_seats: float,
) -> Dict[str, float | None]:
    """Compare passenger growth with offered seats using paired traffic totals.

    The caller supplies passengers and seats from the same eligible records
    within each period, using comparable periods and the same service population. Let P0/P1
    be baseline/end passengers and S0/S1 be baseline/end seats.

    Returns baseline_ratio_pct = 100 * P0 / S0,
    end_ratio_pct = 100 * P1 / S1,
    ratio_change_pp = end_ratio_pct - baseline_ratio_pct,
    passenger_growth_pct = 100 * (P1 / P0 - 1),
    seat_growth_pct = 100 * (S1 / S0 - 1), and
    passenger_seat_growth_gap_pp = passenger_growth_pct - seat_growth_pct.
    Ratios/growth are percentages; differences are percentage points.
    Values remain unrounded. Each zero denominator produces None only for
    its affected calculation and dependent differences. Negative or nonfinite
    inputs raise ValueError. These measurements do not quantify lost demand,
    terminal occupancy, or distance-weighted industry load factor.
    """
    passenger_growth = traffic_growth(baseline=baseline_passengers, end=end_passengers)
    seat_growth = traffic_growth(baseline=baseline_seats, end=end_seats)
    baseline_ratio = PERCENT * baseline_passengers / baseline_seats if baseline_seats > 0 else None
    end_ratio = PERCENT * end_passengers / end_seats if end_seats > 0 else None
    passenger_growth_pct = passenger_growth["growth_pct"]
    seat_growth_pct = seat_growth["growth_pct"]
    return {
        "baseline_ratio_pct": baseline_ratio,
        "end_ratio_pct": end_ratio,
        "ratio_change_pp": (
            end_ratio - baseline_ratio if baseline_ratio is not None and end_ratio is not None else None
        ),
        "passenger_growth_pct": passenger_growth_pct,
        "seat_growth_pct": seat_growth_pct,
        "passenger_seat_growth_gap_pp": (
            passenger_growth_pct - seat_growth_pct
            if passenger_growth_pct is not None and seat_growth_pct is not None else None
        ),
    }


def terminal_expansion_opportunity(
    historical_percentile: float, forecast_percentile: float, operational_percentile: float,
) -> Dict[str, float]:
    """Calculate a terminal-expansion screening score from prepared percentiles.

    historical_percentile represents historical passenger CAGR;
    forecast_percentile represents absolute five-year forecast boarding
    additions; operational_percentile represents arrival disruption rate.
    Each input is a percentile on the inclusive 0-100 scale. The caller
    handles eligibility, cohort selection, and percentile calculation.

    Returns historical_contribution = 0.40 * historical_percentile,
    forecast_contribution = 0.40 * forecast_percentile,
    operational_contribution = 0.20 * operational_percentile, and
    score = historical_contribution + forecast_contribution +
    operational_contribution. All outputs remain unrounded.
    Invalid numbers or percentiles outside 0-100 raise ValueError.
    The score supports investigation; it does not estimate financial ROI
    or establish that terminal expansion would resolve disruption.
    """
    percentiles = {
        "historical_percentile": historical_percentile, "forecast_percentile": forecast_percentile,
        "operational_percentile": operational_percentile,
    }
    _validate_numbers(**percentiles)
    for name, value in percentiles.items():
        if value > PERCENT:
            raise ValueError(f"{name} must be between 0 and 100")
    historical_contribution = HISTORICAL_WEIGHT * historical_percentile
    forecast_contribution = FORECAST_WEIGHT * forecast_percentile
    operational_contribution = OPERATIONAL_WEIGHT * operational_percentile
    return {
        "historical_contribution": historical_contribution,
        "forecast_contribution": forecast_contribution,
        "operational_contribution": operational_contribution,
        "score": historical_contribution + forecast_contribution + operational_contribution,
    }
