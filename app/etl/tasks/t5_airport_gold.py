import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List
from uuid import uuid4

import pandas as pd

from ..errors import EtlInputError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SILVER = ROOT / "data/silver"
DEFAULT_OUTPUT = ROOT / "data/gold/airport_gold.db"
DEFAULT_CHUNKSIZE = 50_000
CAUSES = ["carrier", "weather", "nas", "security", "late_aircraft"]
TEXT_COLUMNS = {
    "airport_code", "faa_locid", "name", "city", "state_code", "country_code", "us_region",
    "faa_mapping_status", "source_airport_code", "reporting_month", "service_class",
    "source_classification", "flight_date", "airport_role", "period_type",
}
REGIONS = {
    "New England": "CT ME MA NH RI VT",
    "Middle Atlantic": "NJ NY PA",
    "Midwest": "IN IL MI OH WI IA KS MN MO NE ND SD",
    "South": "DE DC FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX",
    "West": "AZ CO ID MT NV NM UT WY AK CA HI OR WA",
}


def _load_csv(connection: sqlite3.Connection, paths: List[Path], table: str, chunksize: int) -> None:
    """Load CSV partitions in chunks - SQLite handles aggregation across file boundaries."""
    for path in paths:
        for frame in pd.read_csv(filepath_or_buffer=path, chunksize=chunksize):
            frame.to_sql(name=table, con=connection, if_exists="append", index=False)


def _save_table(connection: sqlite3.Connection, name: str, query: str, keys: List[str]) -> None:
    columns = [column[0] for column in connection.execute(f"SELECT * FROM ({query}) LIMIT 0").description]
    declarations = []
    unique_keys = [f"COALESCE({key}, '')" for key in keys]
    for column in columns:
        kind = "TEXT" if column in TEXT_COLUMNS else "INTEGER"
        if column == "distance_miles" or column == "freight_lbs" or column.endswith("delay_minutes"):
            kind = "REAL"
        declarations.append(f"{column} {kind}")
    connection.execute(f"CREATE TABLE {name} ({', '.join(declarations)})")
    connection.execute(f"CREATE UNIQUE INDEX {name}_key ON {name} ({', '.join(unique_keys)})")
    connection.execute(f"INSERT INTO {name} {query}")


def build_identity(connection: sqlite3.Connection) -> None:
    region_cases = []
    for region, states in REGIONS.items():
        values = ",".join(f"'{state}'" for state in states.split())
        region_cases.append(f"WHEN a.country_code='US' AND a.state_code IN ({values}) THEN '{region}'")
    region_sql = "CASE " + " ".join(region_cases) + " END"
    connection.execute("CREATE UNIQUE INDEX audit_airport_key ON raw_audit(airport_id)")
    connection.execute("CREATE UNIQUE INDEX airports_key ON raw_airports(airport_id)")
    bridge = """
        SELECT a.airport_id, COALESCE(m.canonical_airport_id, a.airport_id) AS canonical_airport_id,
               a.airport_code AS source_airport_code
        FROM raw_airports a LEFT JOIN raw_audit m ON a.airport_id=m.airport_id
    """
    _save_table(connection=connection, name="airport_identity_bridge", query=bridge, keys=["airport_id"])
    dimension = f"""
        SELECT b.canonical_airport_id, a.airport_code, a.faa_locid, a.name, a.city,
               a.state_code, a.country_code, {region_sql} AS us_region,
               COALESCE(m.status, 'unmapped') AS faa_mapping_status
        FROM airport_identity_bridge b JOIN raw_airports a ON a.airport_id=b.canonical_airport_id
        LEFT JOIN raw_audit m ON m.airport_id=a.airport_id
        GROUP BY b.canonical_airport_id
    """
    _save_table(connection=connection, name="airport_dimension", query=dimension, keys=["canonical_airport_id"])


def build_activity(connection: sqlite3.Connection) -> None:
    columns = [column[1] for column in connection.execute("PRAGMA table_info(raw_activity)")]
    flags = [f"a.{column}=1" for column in columns if column.startswith("flag_")]
    flagged = " OR ".join(flags) or "0"
    paired = "a.service_class IN ('F','L') AND a.passengers>=0 AND a.seats>0 AND a.passengers<=a.seats"
    measures = [f"SUM(CASE WHEN a.{name}>=0 THEN a.{name} END) AS {name}"
                for name in ["departures", "passengers", "seats", "freight_lbs"]]
    observations = [f"SUM(CASE WHEN a.{name}>=0 THEN 1 ELSE 0 END) AS {name}_observation_count"
                    for name in ["departures", "freight_lbs"]]
    query = f"""
        SELECT a.reporting_month, o.canonical_airport_id AS origin_airport_id,
               d.canonical_airport_id AS destination_airport_id, a.airline_id, a.service_class,
               a.source AS source_classification, a.distance_miles, {', '.join(measures)},
               SUM(CASE WHEN {paired} THEN a.passengers END) AS ratio_eligible_passengers,
               SUM(CASE WHEN {paired} THEN a.seats END) AS ratio_eligible_seats,
               SUM(CASE WHEN a.distance_miles>0 AND a.departures>=0 THEN a.departures END)
                   AS distance_eligible_departures,
               COUNT(*) AS source_record_count,
               SUM(CASE WHEN {flagged} THEN 1 ELSE 0 END) AS flagged_source_record_count,
               SUM(CASE WHEN a.passengers>=0 THEN 1 ELSE 0 END) AS passenger_observation_count,
               SUM(CASE WHEN a.seats>=0 THEN 1 ELSE 0 END) AS seat_observation_count,
               SUM(CASE WHEN {paired} THEN 1 ELSE 0 END) AS paired_observation_count,
               {', '.join(observations)}
        FROM raw_activity a
        JOIN airport_identity_bridge o ON o.airport_id=a.origin_id
        JOIN airport_identity_bridge d ON d.airport_id=a.destination_id
        WHERE o.canonical_airport_id<>d.canonical_airport_id
        GROUP BY 1,2,3,4,5,6,7
    """
    keys = ["reporting_month", "origin_airport_id", "destination_airport_id", "airline_id",
            "service_class", "source_classification", "distance_miles"]
    _save_table(connection=connection, name="route_activity_monthly", query=query, keys=keys)


def _performance_view(connection: sqlite3.Connection) -> None:
    valid_causes = [f"CASE WHEN {cause}_delay_minutes>=0 THEN 1 ELSE 0 END" for cause in CAUSES]
    causes_observed = " + ".join(valid_causes)
    connection.execute(f"""
        CREATE TEMP VIEW performance AS
        SELECT p.*, o.canonical_airport_id AS origin_airport_id,
               d.canonical_airport_id AS destination_airport_id,
               CAST(scheduled_departure_time AS INTEGER)/100 AS scheduled_departure_hour,
               (cancelled=0 AND diverted=0 AND arrival_delay_minutes IS NOT NULL) AS arrival_observed,
               (cancelled=0 AND departure_delay_minutes IS NOT NULL) AS departure_observed,
               (cancelled=0 AND diverted=0 AND arrival_delay_minutes>=15) AS attribution_eligible,
               ({causes_observed}) AS causes_observed
        FROM raw_performance p
        LEFT JOIN airport_identity_bridge o ON o.airport_id=p.origin_id
        LEFT JOIN airport_identity_bridge d ON d.airport_id=p.destination_id
    """)


def build_performance(connection: sqlite3.Connection) -> None:
    _performance_view(connection=connection)
    cause_sums = [f"SUM(CASE WHEN attribution_eligible AND causes_observed=5 THEN {cause}_delay_minutes END) "
                  f"AS {cause}_delay_minutes" for cause in CAUSES]
    query = f"""
        WITH roles AS (
            SELECT *, origin_airport_id AS airport_id, 'origin' AS airport_role FROM performance
            UNION ALL
            SELECT *, destination_airport_id AS airport_id, 'destination' AS airport_role FROM performance
        )
        SELECT flight_date, airport_id, airport_role, COUNT(*) AS scheduled_flights,
               SUM(cancelled=1) AS cancelled_flights, SUM(diverted=1) AS diverted_flights,
               SUM(cancelled=1 OR diverted=1) AS cancelled_or_diverted_flights,
               SUM(arrival_observed) AS arrival_delay_observed_flights,
               SUM(departure_observed) AS departure_delay_observed_flights,
               SUM(CASE WHEN arrival_observed AND arrival_delay_minutes>=15 THEN 1 ELSE 0 END)
                   AS arrival_delayed_15_flights,
               SUM(CASE WHEN departure_observed AND departure_delay_minutes>=15 THEN 1 ELSE 0 END)
                   AS departure_delayed_15_flights,
               SUM(CASE WHEN arrival_observed THEN MAX(arrival_delay_minutes,0) END)
                   AS positive_arrival_delay_minutes,
               SUM(CASE WHEN departure_observed THEN MAX(departure_delay_minutes,0) END)
                   AS positive_departure_delay_minutes,
               SUM(CASE WHEN cancelled=1 OR diverted=1 OR (arrival_observed AND arrival_delay_minutes>=15)
                   THEN 1 ELSE 0 END) AS arrival_disruption_flights,
               SUM(cancelled=1 OR diverted=1 OR arrival_observed) AS arrival_disruption_classifiable_flights,
               {', '.join(cause_sums)},
               SUM(CASE WHEN attribution_eligible THEN 1 ELSE 0 END) AS attribution_eligible_flights,
               SUM(CASE WHEN attribution_eligible AND causes_observed=5 THEN 1 ELSE 0 END)
                   AS attribution_complete_flights,
               SUM(CASE WHEN attribution_eligible AND causes_observed BETWEEN 1 AND 4 THEN 1 ELSE 0 END)
                   AS attribution_partial_flights
        FROM roles WHERE airport_id IS NOT NULL GROUP BY 1,2,3
    """
    keys = ["flight_date", "airport_id", "airport_role"]
    _save_table(connection=connection, name="airport_performance_daily", query=query, keys=keys)
    mix = """
        SELECT reporting_month, origin_airport_id AS airport_id, airline_id, scheduled_departure_hour,
               COUNT(*) AS scheduled_flights, SUM(cancelled=1) AS cancelled_flights,
               SUM(departure_observed) AS departure_delay_observed_flights,
               SUM(CASE WHEN departure_observed AND departure_delay_minutes>=15 THEN 1 ELSE 0 END)
                   AS departure_delayed_15_flights,
               SUM(CASE WHEN departure_observed THEN MAX(departure_delay_minutes,0) END)
                   AS positive_departure_delay_minutes
        FROM performance WHERE origin_airport_id IS NOT NULL GROUP BY 1,2,3,4
    """
    keys = ["reporting_month", "airport_id", "airline_id", "scheduled_departure_hour"]
    _save_table(connection=connection, name="airport_departure_mix_monthly", query=mix, keys=keys)
    connection.execute("DROP VIEW performance")


def build_outlook(connection: sqlite3.Connection) -> None:
    query = """
        SELECT DISTINCT b.canonical_airport_id AS airport_id, a.fiscal_year, a.taf_edition, a.scenario,
               CASE CAST(a.scenario AS TEXT) WHEN '0' THEN 'historical' WHEN '1' THEN 'forecast'
                    ELSE 'unknown' END AS period_type, a.domestic_passengers AS domestic_boardings,
               a.air_taxi_passengers AS air_taxi_boardings, a.commuter_passengers AS commuter_boardings,
               a.international_us_passengers AS international_us_carrier_boardings,
               a.international_foreign_passengers AS international_foreign_carrier_boardings,
               a.international_us_passengers+a.international_foreign_passengers AS international_boardings,
               a.domestic_passengers+a.air_taxi_passengers+a.commuter_passengers+
                   a.international_us_passengers+a.international_foreign_passengers AS total_boardings,
               a.air_carrier_operations, a.air_taxi_operations,
               a.air_carrier_operations+a.air_taxi_operations AS commercial_operations
        FROM raw_outlook a JOIN airport_identity_bridge b ON b.airport_id=a.airport_id
    """
    keys = ["airport_id", "fiscal_year", "taf_edition", "scenario"]
    _save_table(connection=connection, name="airport_outlook_annual", query=query, keys=keys)


def build_analysis_evidence(connection: sqlite3.Connection, silver_dir: Path) -> None:
    """Persist explicit source attestations - observed rows alone never certify a complete year."""
    evidence_path = silver_dir / "analysis_evidence.csv"
    build_id = uuid4().hex
    connection.execute("""
        CREATE TABLE analysis_evidence (
            dataset TEXT NOT NULL CHECK(dataset IN ('activity','performance','outlook')),
            year INTEGER NOT NULL, complete INTEGER NOT NULL CHECK(complete IN (0,1)),
            source TEXT NOT NULL CHECK(length(source)>0), build_id TEXT NOT NULL,
            edition INTEGER NOT NULL DEFAULT 0, scenario TEXT NOT NULL DEFAULT '',
            period_type TEXT NOT NULL CHECK(period_type IN ('calendar','historical','forecast','unknown')),
            category TEXT NOT NULL DEFAULT '', PRIMARY KEY(dataset,year,edition,scenario)
        )
    """)
    if evidence_path.is_file():
        frame = pd.read_csv(filepath_or_buffer=evidence_path, keep_default_na=False)
        frame["build_id"] = build_id
        frame.to_sql(name="analysis_evidence", con=connection, if_exists="append", index=False)
    for dataset, table, column in [("activity", "raw_activity", "reporting_month"),
                                   ("performance", "raw_performance", "flight_date")]:
        inventory = connection.execute(
            f"SELECT substr({column},1,4), COUNT(DISTINCT substr({column},1,7)) FROM {table} GROUP BY 1"
        ).fetchall()
        for year, months in inventory:
            partitions = [silver_dir / "flight_performance" / f"flight_performance_{year}_{month:02d}.csv"
                          for month in range(1, 13)]
            files_present = all(path.is_file() for path in partitions) if dataset == "performance" else (silver_dir / "flight_activity.csv").is_file()
            complete = int(months == 12 and files_present)
            source = f"Silver {dataset}: {months}/12 calendar months; configured source inventory, not all-airline coverage"
            connection.execute("INSERT OR IGNORE INTO analysis_evidence VALUES (?,?,?,?,?,0,'','calendar','')",
                               (dataset, int(year), complete, source, build_id))
    # FAA's published detailed model marks SCENARIO=0 as observed and nonzero as forecast (F).
    source = "https://taf.faa.gov/taf2024/app.9e588b9c979e2174964a.js; source codes 0=historical, 1=forecast"
    connection.execute("""
        INSERT OR IGNORE INTO analysis_evidence
        SELECT DISTINCT 'outlook', fiscal_year, 1, ?, ?, taf_edition, CAST(scenario AS TEXT),
               CASE CAST(scenario AS TEXT) WHEN '0' THEN 'historical' WHEN '1' THEN 'forecast' END,
               'gold-boardings-and-operations-v1'
        FROM raw_outlook WHERE CAST(scenario AS TEXT) IN ('0','1')
    """, (source, build_id))


def run(silver_dir: Path = DEFAULT_SILVER, output: Path = DEFAULT_OUTPUT,
        chunksize: int = DEFAULT_CHUNKSIZE) -> None:
    """Build Gold once from Silver - an existing output is never overwritten."""
    audit = silver_dir.parent / "metadata/airports_mapping_audit.csv"
    audit = audit if audit.is_file() else silver_dir / "airports_mapping_audit.csv"
    performance = sorted((silver_dir / "flight_performance").glob("flight_performance_????_??.csv"))
    inputs = {"raw_airports": [silver_dir / "airports.csv"], "raw_audit": [audit],
              "raw_activity": [silver_dir / "flight_activity.csv"], "raw_performance": performance,
              "raw_outlook": [silver_dir / "airport_outlook.csv"]}
    if chunksize <= 0:
        raise EtlInputError("Chunksize must be positive")
    if not performance:
        raise EtlInputError(f"No monthly performance CSVs in {silver_dir / 'flight_performance'}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open(mode="xb"):
        pass
    try:
        with closing(sqlite3.connect(database=output)) as connection:
            connection.execute("PRAGMA temp_store=FILE")
            for table, paths in inputs.items():
                _load_csv(connection=connection, paths=paths, table=table, chunksize=chunksize)
            build_identity(connection=connection)
            build_activity(connection=connection)
            build_performance(connection=connection)
            build_outlook(connection=connection)
            build_analysis_evidence(connection=connection, silver_dir=silver_dir)
            connection.execute("DROP TABLE airport_identity_bridge")
            for table in inputs:
                connection.execute(f"DROP TABLE {table}")
            connection.commit()
            connection.execute("VACUUM")
    except BaseException:
        output.unlink()  # Remove only this run's incomplete output.
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Build airport Gold SQLite tables from Silver CSVs once")
    parser.add_argument("--silver-dir", type=Path, default=DEFAULT_SILVER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunksize", type=int, default=DEFAULT_CHUNKSIZE)
    arguments = vars(parser.parse_args())
    run(**arguments)


if __name__ == "__main__":
    main()
