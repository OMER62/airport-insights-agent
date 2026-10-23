import sqlite3
from contextlib import closing
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest


def _write_inputs(path: Path, missing: bool) -> None:
    airports = [[1, "AAA", "AAA", "Airport A", "City A", "CA", "US"],
                [2, "BBB", "BBB", "Airport B", "City B", "TX", "US"],
                [3, "OLD", "AAA", "Old A", "City A", "CA", "US"]]
    columns = ["airport_id", "airport_code", "faa_locid", "name", "city", "state_code", "country_code"]
    audit = {"airport_id": [1, 2, 3], "canonical_airport_id": [1, 2, 1], "status": ["mapped"] * 3}
    activity = {
        "reporting_month": "2025-01", "origin_id": 3, "destination_id": 2, "airline_id": 10,
        "service_class": "F", "source": "DU", "distance_miles": None if missing else 2000,
        "departures": 2, "passengers": None if missing else 8, "seats": 10, "freight_lbs": 4,
        "flag_invalid_distance": missing,
    }
    performance = {
        "flight_date": "2025-01-01", "reporting_month": "2025-01", "origin_id": 3,
        "destination_id": 2, "airline_id": 10, "scheduled_departure_time": "2400",
        "cancelled": False, "diverted": False, "arrival_delay_minutes": 20,
        "departure_delay_minutes": 15, "carrier_delay_minutes": 0,
        "weather_delay_minutes": None if missing else 20, "nas_delay_minutes": 0,
        "security_delay_minutes": 0, "late_aircraft_delay_minutes": 0,
    }
    outlook = {
        "airport_id": 3, "fiscal_year": 2025, "taf_edition": 2025, "scenario": 1,
        "domestic_passengers": None if missing else 1, "air_taxi_passengers": 1,
        "commuter_passengers": 1, "international_us_passengers": 1,
        "international_foreign_passengers": 1, "air_carrier_operations": 2, "air_taxi_operations": 3,
    }
    path.mkdir()
    (path / "flight_performance").mkdir()
    pd.DataFrame(data=airports, columns=columns).to_csv(path_or_buf=path / "airports.csv", index=False)
    pd.DataFrame(audit).to_csv(path_or_buf=path / "airports_mapping_audit.csv", index=False)
    pd.DataFrame([activity, activity]).to_csv(path_or_buf=path / "flight_activity.csv", index=False)
    for month in ["01", "02"]:
        target = path / f"flight_performance/flight_performance_2025_{month}.csv"
        pd.DataFrame([performance]).to_csv(path_or_buf=target, index=False)
    pd.DataFrame([outlook, {**outlook, "airport_id": 1}]).to_csv(
        path_or_buf=path / "airport_outlook.csv", index=False,
    )


@pytest.mark.parametrize("chunksize", [1, 100])
@pytest.mark.parametrize("missing", [False, True])
def test_run_combines_silver_files_and_preserves_missing_values(
    tmp_path: Path, chunksize: int, missing: bool, capsys: pytest.CaptureFixture,
) -> None:
    source = tmp_path / "silver"
    output = tmp_path / "gold.db"
    task = import_module("etl.tasks.t5_airport_gold")
    _write_inputs(path=source, missing=missing)
    task.run(silver_dir=source, output=output, chunksize=chunksize)
    with closing(sqlite3.connect(database=output)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert {name for (name,) in tables} == {
            "airport_dimension", "route_activity_monthly", "airport_performance_daily",
            "airport_departure_mix_monthly", "airport_outlook_annual",
            "analysis_evidence",
        }
        assert connection.execute("SELECT COUNT(*) FROM airport_dimension").fetchone() == (2,)
        activity = connection.execute(
            "SELECT passengers,seats,source_record_count,distance_eligible_departures FROM route_activity_monthly"
        ).fetchone()
        assert activity == (None if missing else 16, 20, 2, None if missing else 4)
        daily = connection.execute(
            "SELECT airport_id,airport_role,scheduled_flights,weather_delay_minutes,attribution_partial_flights "
            "FROM airport_performance_daily ORDER BY airport_id"
        ).fetchall()
        cause = None if missing else 40
        assert daily == [(1, "origin", 2, cause, 2 if missing else 0),
                         (2, "destination", 2, cause, 2 if missing else 0)]
        mix = connection.execute(
            "SELECT scheduled_departure_hour,scheduled_flights FROM airport_departure_mix_monthly"
        ).fetchone()
        assert mix == (24, 2)
        outlook = connection.execute(
            "SELECT total_boardings,commercial_operations,period_type FROM airport_outlook_annual"
        ).fetchall()
        assert outlook == [(None if missing else 5, 5, "forecast")]
        evidence = connection.execute("SELECT dataset,year,complete FROM analysis_evidence ORDER BY dataset").fetchall()
        assert evidence == [("activity", 2025, 0), ("outlook", 2025, 1), ("performance", 2025, 0)]
        assert connection.execute("SELECT COUNT(DISTINCT build_id) FROM analysis_evidence").fetchone() == (1,)
        paired = connection.execute("SELECT paired_observation_count FROM route_activity_monthly").fetchone()
        assert paired == (0 if missing else 2,)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("failure", ["mapping", "outlook", "missing_file", "existing_output"])
def test_run_rejects_conflicts_without_leaving_a_partial_database(tmp_path: Path, failure: str) -> None:
    source = tmp_path / "silver"
    output = tmp_path / "gold.db"
    task = import_module("etl.tasks.t5_airport_gold")
    _write_inputs(path=source, missing=False)
    if failure == "mapping":
        path = source / "airports_mapping_audit.csv"
        frame = pd.read_csv(path)
        frame.loc[len(frame)] = [1, 2, "mapped"]
        frame.to_csv(path_or_buf=path, index=False)
    if failure == "outlook":
        path = source / "airport_outlook.csv"
        frame = pd.read_csv(path)
        frame.loc[1, "domestic_passengers"] = 10
        frame.to_csv(path_or_buf=path, index=False)
    if failure == "missing_file":
        (source / "flight_activity.csv").unlink()
    if failure == "existing_output":
        output.write_bytes(b"existing database")
    with pytest.raises((sqlite3.IntegrityError, FileNotFoundError, FileExistsError)):
        task.run(silver_dir=source, output=output)
    if failure == "existing_output":
        assert output.read_bytes() == b"existing database"
    else:
        assert not output.exists()


def test_run_keeps_cancellation_and_diversion_populations_separate(tmp_path: Path) -> None:
    source = tmp_path / "silver"
    output = tmp_path / "gold.db"
    task = import_module("etl.tasks.t5_airport_gold")
    _write_inputs(path=source, missing=False)
    for path in (source / "flight_performance").glob("*.csv"):
        frame = pd.read_csv(path)
        row = frame.iloc[0].to_dict()
        rows = [row, {**row, "cancelled": True, "diverted": True}, {**row, "diverted": True}]
        pd.DataFrame(rows).to_csv(path_or_buf=path, index=False)
    task.run(silver_dir=source, output=output, chunksize=1)
    with closing(sqlite3.connect(database=output)) as connection:
        daily = connection.execute(
            "SELECT scheduled_flights,cancelled_or_diverted_flights,arrival_delay_observed_flights,"
            "departure_delay_observed_flights,positive_departure_delay_minutes,arrival_disruption_flights "
            "FROM airport_performance_daily WHERE airport_role='origin'"
        ).fetchone()
        assert daily == (6, 4, 2, 4, 60, 6)
        mix = connection.execute(
            "SELECT scheduled_flights,cancelled_flights,departure_delay_observed_flights "
            "FROM airport_departure_mix_monthly"
        ).fetchone()
        assert mix == (6, 2, 4)


@pytest.mark.parametrize("complete", [0, 1, 2])
def test_run_imports_explicit_source_evidence(tmp_path: Path, complete: int) -> None:
    source = tmp_path / "silver"
    output = tmp_path / "gold.db"
    task = import_module("etl.tasks.t5_airport_gold")
    _write_inputs(path=source, missing=False)
    evidence = {"dataset": "activity", "year": 2025, "complete": complete,
                "source": "verified source inventory reference", "edition": 0, "scenario": "",
                "period_type": "calendar", "category": ""}
    pd.DataFrame([evidence]).to_csv(path_or_buf=source / "analysis_evidence.csv", index=False)
    if complete == 2:
        with pytest.raises(pd.errors.DatabaseError):
            task.run(silver_dir=source, output=output)
        assert not output.exists()
        return
    task.run(silver_dir=source, output=output)
    with closing(sqlite3.connect(output)) as connection:
        row = connection.execute("SELECT complete,source FROM analysis_evidence WHERE dataset='activity'").fetchone()
        assert row == (complete, "verified source inventory reference")


@pytest.mark.parametrize("missing_partition", [False, True])
def test_calendar_evidence_requires_full_source_inventory(tmp_path: Path, missing_partition: bool) -> None:
    task = import_module("etl.tasks.t5_airport_gold")
    partitions = tmp_path / "flight_performance"
    partitions.mkdir()
    (tmp_path / "flight_activity.csv").touch()
    for month in range(1, 13):
        if not missing_partition or month != 12:
            (partitions / f"flight_performance_2025_{month:02d}.csv").touch()
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript("CREATE TABLE raw_activity(reporting_month TEXT); CREATE TABLE raw_performance(flight_date TEXT); CREATE TABLE raw_outlook(fiscal_year INTEGER,taf_edition INTEGER,scenario TEXT);")
        connection.executemany("INSERT INTO raw_activity VALUES (?)", [(f"2025-{month:02d}",) for month in range(1, 13)])
        connection.executemany("INSERT INTO raw_performance VALUES (?)", [(f"2025-{month:02d}-01",) for month in range(1, 13)])
        task.build_analysis_evidence(connection=connection, silver_dir=tmp_path)
        rows = connection.execute("SELECT dataset,complete FROM analysis_evidence ORDER BY dataset").fetchall()
        assert rows == [("activity", 1), ("performance", int(not missing_partition))]


def test_unknown_forecast_code_is_not_attested(tmp_path: Path) -> None:
    task = import_module("etl.tasks.t5_airport_gold")
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript("CREATE TABLE raw_activity(reporting_month TEXT); CREATE TABLE raw_performance(flight_date TEXT); CREATE TABLE raw_outlook(fiscal_year INTEGER,taf_edition INTEGER,scenario TEXT); INSERT INTO raw_outlook VALUES(2030,2025,'experimental');")
        task.build_analysis_evidence(connection=connection, silver_dir=tmp_path)
        assert connection.execute("SELECT COUNT(*) FROM analysis_evidence WHERE complete=1").fetchone() == (0,)
