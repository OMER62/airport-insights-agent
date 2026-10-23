from importlib import import_module
from typing import Any, Dict

import pytest

metrics = import_module("analysis.metrics")


@pytest.mark.parametrize("inputs,expected", [
    ({"baseline": 100_000, "end": 110_000},
     {"absolute_change": 10_000, "growth_pct": 10, "cagr_pct": 10}),
    ({"baseline": 100, "end": 121, "years": 2},
     {"absolute_change": 21, "growth_pct": 21, "cagr_pct": 10}),
    ({"baseline": 100, "end": 0},
     {"absolute_change": -100, "growth_pct": -100, "cagr_pct": -100}),
    ({"baseline": 0, "end": 50},
     {"absolute_change": 50, "growth_pct": None, "cagr_pct": None}),
    ({"baseline": 0, "end": 0},
     {"absolute_change": 0, "growth_pct": None, "cagr_pct": None}),
    ({"baseline": -1, "end": 10}, None),
    ({"baseline": 10, "end": -1}, None),
    ({"baseline": float("nan"), "end": 10}, None),
    ({"baseline": 10, "end": float("inf")}, None),
    ({"baseline": 10, "end": 20, "years": 0}, None),
    ({"baseline": 10, "end": 20, "years": -1}, None),
    ({"baseline": 10, "end": 20, "years": float("inf")}, None),
    ({"baseline": None, "end": 10}, None),
    ({"baseline": True, "end": 10}, None),
])
def test_traffic_growth(inputs: Dict[str, Any], expected: Dict[str, float | None] | None) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            metrics.traffic_growth(**inputs)
        return
    assert metrics.traffic_growth(**inputs) == pytest.approx(expected)


@pytest.mark.parametrize("disrupted,classifiable,expected", [
    (25, 100, 25), (0, 100, 0), (100, 100, 100), (0, 0, None),
    (120, 100, "invalid"), (1, 0, "invalid"),
    (-1, 100, "invalid"), (1, -1, "invalid"),
    (float("inf"), 100, "invalid"), (1, float("nan"), "invalid"),
])
def test_airport_operational_pressure(
    disrupted: float, classifiable: float, expected: float | str | None,
) -> None:
    inputs = {"disrupted_flights": disrupted, "classifiable_flights": classifiable}
    if expected == "invalid":
        with pytest.raises(ValueError):
            metrics.airport_operational_pressure(**inputs)
        return
    assert metrics.airport_operational_pressure(**inputs) == {"arrival_disruption_pct": expected}


@pytest.mark.parametrize("long_haul,total,expected", [
    (30, 100, 30), (1, 3, 100 / 3), (0, 100, 0), (100, 100, 100), (0, 0, None),
    (120, 100, "invalid"), (10, 0, "invalid"),
    (-1, 100, "invalid"), (1, -1, "invalid"),
    (float("nan"), 100, "invalid"), (1, float("inf"), "invalid"),
])
def test_outbound_long_haul_share(long_haul: float, total: float, expected: float | str | None) -> None:
    inputs = {"long_haul_departures": long_haul, "distance_eligible_departures": total}
    if expected == "invalid":
        with pytest.raises(ValueError):
            metrics.outbound_long_haul_share(**inputs)
        return
    assert metrics.outbound_long_haul_share(**inputs) == pytest.approx({"long_haul_share_pct": expected})


@pytest.mark.parametrize("inputs,expected", [
    ((90, 99, 100, 105), (90, 660 / 7, 30 / 7, 10, 5, 5)),
    ((90, 90, 100, 100), (90, 90, 0, 0, 0, 0)),
    ((90, 0, 100, 100), (90, 0, -90, -100, 0, -100)),
    ((0, 10, 100, 100), (0, 10, 10, None, 0, None)),
    ((90, 99, 0, 105), (None, 660 / 7, None, 10, None, None)),
    ((90, 99, 100, 0), (90, None, None, 10, -100, 110)),
    ((0, 0, 0, 0), (None, None, None, None, None, None)),
    ((-1, 99, 100, 105), None), ((90, -1, 100, 105), None),
    ((90, 99, -1, 105), None), ((90, 99, 100, -1), None),
    ((float("nan"), 99, 100, 105), None), ((90, 99, 100, float("inf")), None),
])
def test_demand_capacity_pressure(
    inputs: tuple[float, float, float, float], expected: tuple[float | None, ...] | None,
) -> None:
    baseline_passengers, end_passengers, baseline_seats, end_seats = inputs
    kwargs = {
        "baseline_passengers": baseline_passengers, "end_passengers": end_passengers,
        "baseline_seats": baseline_seats, "end_seats": end_seats,
    }
    keys = (
        "baseline_ratio_pct", "end_ratio_pct", "ratio_change_pp",
        "passenger_growth_pct", "seat_growth_pct", "passenger_seat_growth_gap_pp",
    )
    if expected is None:
        with pytest.raises(ValueError):
            metrics.demand_capacity_pressure(**kwargs)
        return
    expected_result = dict(zip(keys, expected))
    assert metrics.demand_capacity_pressure(**kwargs) == pytest.approx(expected_result)


@pytest.mark.parametrize("historical,forecast,operational,expected", [
    (80, 60, 50, (32, 24, 10, 66)),
    (0, 0, 0, (0, 0, 0, 0)),
    (100, 100, 100, (40, 40, 20, 100)),
    (50, 50, 50, (20, 20, 10, 50)),
    (-1, 60, 50, None), (80, -1, 50, None), (80, 60, -1, None),
    (101, 60, 50, None), (80, 101, 50, None), (80, 60, 101, None),
    (float("nan"), 60, 50, None), (80, float("inf"), 50, None),
    (80, 60, None, None),
])
def test_terminal_expansion_opportunity(
    historical: float, forecast: float, operational: float, expected: tuple[float, ...] | None,
) -> None:
    inputs = {
        "historical_percentile": historical, "forecast_percentile": forecast,
        "operational_percentile": operational,
    }
    keys = ("historical_contribution", "forecast_contribution", "operational_contribution", "score")
    if expected is None:
        with pytest.raises(ValueError):
            metrics.terminal_expansion_opportunity(**inputs)
        return
    expected_result = dict(zip(keys, expected))
    assert metrics.terminal_expansion_opportunity(**inputs) == pytest.approx(expected_result)
