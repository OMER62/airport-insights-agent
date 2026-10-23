"""Public signatures and calculation summaries for metrics.py.

The ellipsis bodies declare the interface; implementations live in metrics.py.
Inputs must be finite and nonnegative; invalid inputs raise ValueError.
The caller prepares comparable populations, units, and periods.
Results are unrounded. Percentage values use percent units: 10 means 10%.
pp means percentage points.
Undefined calculations return None, including dependent differences.
"""

from typing import Dict

PERCENT: int
HISTORICAL_WEIGHT: float
FORECAST_WEIGHT: float
OPERATIONAL_WEIGHT: float


def traffic_growth(
    baseline: float, end: float, years: float = 1,
) -> Dict[str, float | None]:
    """Calculate absolute change, percentage growth, and annualized growth.

    Returns absolute_change = end - baseline,
    growth_pct = 100 * (end / baseline - 1), and
    cagr_pct = 100 * ((end / baseline) ** (1 / years) - 1).
    Zero baseline makes both percentages None. years must be positive.
    """
    ...


def airport_operational_pressure(
    disrupted_flights: float, classifiable_flights: float,
) -> Dict[str, float | None]:
    """Calculate arrival_disruption_pct = 100 * disrupted / classifiable flights.

    A disrupted flight is cancelled, diverted, or completed and arriving at
    least 15 minutes late. Count each flight once. Disrupted flights cannot exceed
    classifiable flights. A zero denominator returns None.
    """
    ...


def outbound_long_haul_share(
    long_haul_departures: float, distance_eligible_departures: float,
) -> Dict[str, float | None]:
    """Calculate long_haul_share_pct = 100 * long-haul / eligible departures.

    The caller applies the distance threshold (spec default: >= 2,000 miles).
    Long-haul departures cannot exceed eligible departures.
    A zero denominator returns None.
    """
    ...


def demand_capacity_pressure(
    baseline_passengers: float, end_passengers: float,
    baseline_seats: float, end_seats: float,
) -> Dict[str, float | None]:
    """Compare passenger growth with seat growth and passenger-to-seat ratios.

    Passengers and seats must come from the same eligible records within each
    period, using comparable periods and the same service population.

    Returns baseline_ratio_pct and end_ratio_pct (100 * passengers / seats),
    ratio_change_pp (end ratio minus baseline ratio), passenger_growth_pct,
    seat_growth_pct, and passenger_seat_growth_gap_pp (passenger growth minus
    seat growth). Each zero denominator affects only its calculation and
    dependent differences.
    """
    ...


def terminal_expansion_opportunity(
    historical_percentile: float, forecast_percentile: float,
    operational_percentile: float,
) -> Dict[str, float]:
    """Calculate a screening score from caller-prepared percentiles in [0, 100].

    Returns historical_contribution = 0.40 * historical_percentile,
    forecast_contribution = 0.40 * forecast_percentile,
    operational_contribution = 0.20 * operational_percentile,
    and score = the sum of those contributions.
    Inputs represent historical passenger CAGR, absolute five-year forecast
    boarding additions, and arrival disruption rate, respectively.
    """
    ...
