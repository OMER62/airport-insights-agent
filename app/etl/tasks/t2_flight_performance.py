import argparse
import logging
from pathlib import Path

import pandas as pd

from .. import log_
from ..errors import EtlValidationError
from ..initializer import initialize_partitions
from .t1_flight_activity import _parse_number

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/raw/BTS-Carrier-On-Time-Performance"
DEFAULT_OUTPUT = ROOT / "data/silver/flight_performance"
COLUMNS = dict(zip(
    ["FlightDate", "DOT_ID_Reporting_Airline", "Flight_Number_Reporting_Airline", "OriginAirportID",
     "DestAirportID", "CRSDepTime", "CRSArrTime", "DepDelay", "ArrDelay", "Cancelled", "CancellationCode",
     "Diverted", "CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay"],
    ["flight_date", "airline_id", "flight_number", "origin_id", "destination_id", "scheduled_departure_time",
     "scheduled_arrival_time", "departure_delay_minutes", "arrival_delay_minutes", "cancelled", "cancellation_code",
     "diverted", "carrier_delay_minutes", "weather_delay_minutes", "nas_delay_minutes", "security_delay_minutes",
     "late_aircraft_delay_minutes"],
))
KEY = ["flight_date", "airline_id", "flight_number", "origin_id", "destination_id", "scheduled_departure_time"]
INTEGERS = ["airline_id", "origin_id", "destination_id", "departure_delay_minutes", "arrival_delay_minutes"]
CAUSES = list(COLUMNS.values())[-5:]


def require(valid, message):
    if not valid.fillna(False).all():
        raise EtlValidationError(f"{message}: {int((~valid.fillna(False)).sum()):,} rows")


def transform(frame, partition):
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise EtlValidationError(f"Missing source columns: {sorted(missing)}")
    result = frame[list(COLUMNS)].rename(columns=COLUMNS).copy()
    for name in result:
        result[name] = result[name].str.strip().replace("", pd.NA)
    require(result.flight_date.str.fullmatch(r"\d{4}-\d{2}-\d{2}"), "Invalid flight_date format")
    dates = pd.to_datetime(result.flight_date, format="%Y-%m-%d", errors="coerce")
    require(dates.notna(), "Invalid flight_date")
    month = partition.removeprefix("flight_performance_").replace("_", "-")
    require(dates.dt.strftime("%Y-%m").eq(month), f"Flight dates outside expected month {month}")
    result.insert(1, "reporting_month", dates.dt.strftime("%Y-%m"))
    for name in INTEGERS + CAUSES:
        numbers = _parse_number(result[name], name)
        if name in INTEGERS:
            require(numbers.isna() | numbers.mod(1).eq(0), f"Fractional integer in {name}")
            try:
                numbers = numbers.astype("Int64")
            except (ValueError, TypeError, OverflowError) as error:
                raise EtlValidationError(f"Invalid integer in {name}: {error}") from error
        result[name] = numbers
    for name in KEY:
        require(result[name].notna(), f"Missing key field {name}")
    require(result.origin_id.ne(result.destination_id), "Origin and destination must differ")
    for name in ["scheduled_departure_time", "scheduled_arrival_time"]:
        require(result[name].str.fullmatch(r"(?:[01][0-9]|2[0-3])[0-5][0-9]|2400"), f"Invalid {name}")
    for name in ["cancelled", "diverted"]:
        values = _parse_number(result[name], name)
        require(values.isin([0, 1]), f"Invalid boolean {name}")
        result[name] = values.eq(1).astype(bool)
    require((result.cancelled & result.cancellation_code.isin(list("ABCD"))) |
            (~result.cancelled & result.cancellation_code.isna()), "Cancellation code/status mismatch")
    return result


def run(input_dir=DEFAULT_INPUT, output=DEFAULT_OUTPUT, overwrite=False, chunksize=50000):
    inputs = {f"flight_performance_2025_{month:02d}": Path(input_dir) /
              f"On_Time_Reporting_Carrier_On_Time_Performance_2025_{month:02d}.csv" for month in range(1, 13)}
    stats = {}

    def report(frame, partition):
        counts = stats.setdefault(partition, {"rows": 0, "cancelled": 0, "diverted": 0,
                                            "missing_departure_delay": 0, "missing_arrival_delay": 0})
        counts["rows"] += len(frame)
        for name in ["cancelled", "diverted"]:
            counts[name] += int(frame[name].sum())
        counts["missing_departure_delay"] += int(frame.departure_delay_minutes.isna().sum())
        counts["missing_arrival_delay"] += int(frame.arrival_delay_minutes.isna().sum())
        dates = frame.flight_date
        counts["first_date"] = min(counts.get("first_date", dates.min()), dates.min())
        counts["last_date"] = max(counts.get("last_date", dates.max()), dates.max())

    success = initialize_partitions(inputs=inputs, output=output, columns=COLUMNS, key=KEY,
                                    transform=transform, report=report, overwrite=overwrite, chunksize=chunksize)
    if success:
        for partition, counts in stats.items():
            log_.info(f"{partition}: {counts}")
        log_.info(f"Total published rows: {sum(counts['rows'] for counts in stats.values()):,}")
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean all 12 months of 2025 flight performance")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(0 if run(args.input_dir, args.output, args.overwrite) else 1)
