from importlib import import_module
from typing import Dict

import pandas as pd
import pytest

transform = import_module("etl.tasks.t1_flight_activity").transform
validate_activity = import_module("etl.tasks.t1_flight_activity").validate_activity
EtlError = import_module("etl.errors").EtlValidationError

ROW = {
    "YEAR": "2024",
    "MONTH": "1",
    "ORIGIN_AIRPORT_ID": "100",
    "DEST_AIRPORT_ID": "200",
    "AIRLINE_ID": "300",
    "UNIQUE_CARRIER_ENTITY": "01260",
    "AIRCRAFT_TYPE": "079",
    "AIRCRAFT_CONFIG": "2",
    "CLASS": "G",
    "DATA_SOURCE": "DU",
    "DEPARTURES_PERFORMED": "1.00",
    "PASSENGERS": "0",
    "SEATS": "0",
    "DISTANCE": "100",
    "FREIGHT": "500",
}


@pytest.mark.parametrize(
    "changes,flag",
    [
        ({"PASSENGERS": "5"}, "flag_passengers_exceed_seats"),
        ({"DISTANCE": ""}, "flag_invalid_distance"),
        ({"DISTANCE": "0"}, "flag_invalid_distance"),
        ({"DISTANCE": "-1"}, "flag_invalid_distance"),
        ({"DEST_AIRPORT_ID": "100"}, "flag_same_airport"),
        ({"ORIGIN_AIRPORT_ID": ""}, "flag_missing_airport_id"),
        ({"FREIGHT": "-1"}, "flag_negative_measurement"),
    ],
)
def test_transform_preserves_values_and_flags_quality(changes: Dict[str, str], flag: str) -> None:
    frame = pd.DataFrame(data=[{**ROW, **changes}], dtype="string")
    result = transform(frame)
    assert len(result) == 1
    assert result.carrier_entity.iloc[0] == "01260"
    assert result.aircraft_type.iloc[0] == "079"
    assert result.source.iloc[0] == "DU"
    assert result[flag].iloc[0]
    assert result.freight_lbs.iloc[0] == float(changes.get("FREIGHT", "500"))
    assert result.departures.dtype == "Int64"
    assert frame.equals(pd.DataFrame(data=[{**ROW, **changes}], dtype="string"))


def test_cargo_and_missing_measurements_survive_with_five_flags() -> None:
    frame = pd.DataFrame(data=[{**ROW, "DEPARTURES_PERFORMED": "0", "PASSENGERS": ""}], dtype="string")
    result = transform(frame)
    assert len(result) == 1
    assert result.departures.iloc[0] == 0
    assert result.seats.iloc[0] == 0
    assert pd.isna(result.passengers.iloc[0])
    assert result.filter(like="flag_").to_dict(orient="records") == [{
        "flag_missing_airport_id": False,
        "flag_passengers_exceed_seats": False,
        "flag_invalid_distance": False,
        "flag_same_airport": False,
        "flag_negative_measurement": False,
    }]


def test_reporting_month_combines_year_and_month() -> None:
    frame = pd.DataFrame(data=[ROW, {**ROW, "YEAR": "2025", "MONTH": "12"}], dtype="string")
    result = transform(frame)
    assert result.reporting_month.tolist() == ["2024-01", "2025-12"]
    assert "date" not in result.columns
    assert "year" not in result.columns
    assert "month" not in result.columns
    assert result.columns[0] == "reporting_month"
    validate_activity(result)


@pytest.mark.parametrize(
    "changes,drop,error",
    [
        ({}, "SEATS", "Missing required columns: SEATS; check the CSV schema"),
        ({"AIRLINE_ID": ""}, None, "Missing required key values in airline_id: 1 rows"),
        ({"UNIQUE_CARRIER_ENTITY": " "}, None, "Missing required key values in carrier_entity: 1 rows"),
        ({"MONTH": "13"}, None, "Month must be between 1 and 12"),
        ({"PASSENGERS": "1.5"}, None, "Invalid numeric values in passengers: expected whole numbers"),
        ({"PASSENGERS": "bad"}, None, "Invalid numeric values in passengers: .*bad"),
        ({"DISTANCE": "inf"}, None, "Invalid numeric values in distance_miles: expected finite numbers"),
    ],
)
def test_transform_rejects_invalid_input(changes: Dict[str, str], drop: str | None, error: str) -> None:
    frame = pd.DataFrame(data=[{**ROW, **changes}], dtype="string")
    if drop is not None:
        frame = frame.drop(columns=drop)
    with pytest.raises(expected_exception=EtlError, match=error):
        transform(frame)


@pytest.mark.parametrize("duplicate", [False, True])
def test_validate_activity_checks_combined_business_keys(duplicate: bool) -> None:
    second = ROW if duplicate else {**ROW, "MONTH": "2"}
    frame = transform(pd.DataFrame(data=[ROW, second], dtype="string"))
    if duplicate:
        with pytest.raises(expected_exception=EtlError, match="Duplicate flight_activity business keys in 2 rows"):
            validate_activity(frame)
    else:
        assert validate_activity(frame) is None
