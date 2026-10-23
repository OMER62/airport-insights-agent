from pathlib import Path
from typing import List

import pandas as pd

from .. import log_
from ..errors import EtlValidationError
from ..initializer import initialize

COLUMNS = {
    "YEAR": "year",
    "MONTH": "month",
    "ORIGIN_AIRPORT_ID": "origin_id",
    "DEST_AIRPORT_ID": "destination_id",
    "AIRLINE_ID": "airline_id",
    "UNIQUE_CARRIER_ENTITY": "carrier_entity",
    "AIRCRAFT_TYPE": "aircraft_type",
    "AIRCRAFT_CONFIG": "aircraft_config",
    "CLASS": "service_class",
    "DATA_SOURCE": "source",
    "DEPARTURES_PERFORMED": "departures",
    "PASSENGERS": "passengers",
    "SEATS": "seats",
    "DISTANCE": "distance_miles",
    "FREIGHT": "freight_lbs",
}
KEY = ["reporting_month", *list(COLUMNS.values())[2:10]]
AIRPORT_IDS = ["origin_id", "destination_id"]
INTEGER_COLUMNS = [
    "year",
    "month",
    "origin_id",
    "destination_id",
    "airline_id",
    "departures",
    "passengers",
    "seats",
]
MEASURES = ["departures", "passengers", "seats", "distance_miles", "freight_lbs"]
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "data/silver/flight_activity.csv"
)


def run(inputs: List[Path], output: Path = DEFAULT_OUTPUT, overwrite: bool = False) -> bool:
    """Run flight-activity cleaning - the initializer prepares and submits the task."""
    return initialize(
        inputs=inputs,
        output=output,
        transform=transform,
        validate=validate_activity,
        report=report_activity,
        overwrite=overwrite,
    )


def report_activity(frame: pd.DataFrame) -> None:
    for name in frame.columns:
        if name.startswith("flag_"):
            log_.info(f"{name}: {int(frame[name].sum()):,}")


def validate_activity(frame: pd.DataFrame) -> None:
    duplicates = frame.duplicated(subset=KEY, keep=False)
    if duplicates.any():
        raise EtlValidationError(
            f"Duplicate flight_activity business keys in {int(duplicates.sum()):,} rows; "
            f"key columns: {', '.join(KEY)}; correct duplicates across inputs before retrying"
        )


def _parse_number(values: pd.Series, name: str) -> pd.Series:
    try:
        numbers = pd.to_numeric(arg=values, errors="raise")
        if numbers.isin([float("inf"), float("-inf")]).any():
            raise EtlValidationError(f"Invalid numeric values in {name}: expected finite numbers, found infinity")
        if name in INTEGER_COLUMNS and numbers.dropna().mod(1).ne(0).any():
            raise EtlValidationError(f"Invalid numeric values in {name}: expected whole numbers, found fractions")
        return numbers.astype("Int64" if name in INTEGER_COLUMNS else "Float64")
    except (ValueError, TypeError, OverflowError) as error:
        raise EtlValidationError(f"Invalid numeric values in {name}: {error}") from error


def _add_flags(frame: pd.DataFrame) -> pd.DataFrame:
    flags = {
        "missing_airport_id": frame[AIRPORT_IDS].isna().any(axis=1),
        "passengers_exceed_seats": frame.passengers.gt(frame.seats),
        "invalid_distance": frame.distance_miles.isna() | frame.distance_miles.le(0),
        "same_airport": frame.origin_id.eq(frame.destination_id),
        "negative_measurement": frame[MEASURES].lt(0).any(axis=1),
    }
    for name, values in flags.items():
        frame[f"flag_{name}"] = values.fillna(False).astype(bool)
    return frame


def transform(frame: pd.DataFrame) -> pd.DataFrame:
    """Emit reporting_month (YYYY-MM) and activity measures, preserving questionable values with flags."""
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise EtlValidationError(f"Missing required columns: {', '.join(sorted(missing))}; check the CSV schema")
    result = frame[list(COLUMNS)].rename(columns=COLUMNS).copy()
    for name in result:
        result[name] = result[name].str.strip().replace(to_replace="", value=pd.NA)
    for name in INTEGER_COLUMNS + ["distance_miles", "freight_lbs"]:
        result[name] = _parse_number(values=result[name], name=name)
    for name in set(["year", "month", *KEY[1:]]) - set(AIRPORT_IDS):
        if result[name].isna().any():
            raise EtlValidationError(
                f"Missing required key values in {name}: {int(result[name].isna().sum()):,} rows; "
                "populate this field before retrying"
            )
    if not result.month.between(left=1, right=12).all():
        raise EtlValidationError("Month must be between 1 and 12; correct missing or out-of-range month values")
    result.insert(
        loc=0,
        column="reporting_month",
        value=result.year.astype("string").str.zfill(4) + "-" + result.month.astype("string").str.zfill(2),
    )
    result = result.drop(columns=["year", "month"])
    return _add_flags(result)
