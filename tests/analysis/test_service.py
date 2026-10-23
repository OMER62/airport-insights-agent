import ast
import asyncio
import sqlite3
from contextlib import closing
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

dao = import_module("analysis.dao_get_gold_data")
gold = import_module("etl.tasks.t5_airport_gold")
service = import_module("analysis.service")


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "gold.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE airport_dimension(canonical_airport_id INTEGER, country_code TEXT, us_region TEXT);
            INSERT INTO airport_dimension VALUES (1,'US','West'),(2,'US','South'),(3,'CA',NULL);
            CREATE TABLE raw_activity(reporting_month TEXT);
            CREATE TABLE raw_performance(flight_date TEXT);
            CREATE TABLE raw_outlook(fiscal_year INTEGER,taf_edition INTEGER,scenario TEXT);
            CREATE TABLE route_activity_monthly(
                reporting_month TEXT,origin_airport_id INTEGER,service_class TEXT,distance_miles REAL,
                passengers REAL,seats REAL,departures REAL,freight_lbs REAL,
                ratio_eligible_passengers REAL,ratio_eligible_seats REAL,distance_eligible_departures REAL,
                source_record_count INTEGER,passenger_observation_count INTEGER,seat_observation_count INTEGER,
                departures_observation_count INTEGER,freight_lbs_observation_count INTEGER,
                paired_observation_count INTEGER);
            INSERT INTO route_activity_monthly VALUES
                ('2024-01',1,'F',2000,100000,125000,100,0,100000,125000,100,1,1,1,1,1,1),
                ('2025-01',1,'F',2000,110000,125000,100,0,110000,125000,100,1,1,1,1,1,1),
                ('2024-01',2,'F',1000,100000,125000,100,0,100000,125000,100,1,1,1,1,1,1),
                ('2025-01',2,'F',1000,120000,125000,100,0,120000,125000,100,1,1,1,1,1,1);
            CREATE TABLE airport_performance_daily(
                flight_date TEXT,airport_id INTEGER,airport_role TEXT,scheduled_flights INTEGER,
                arrival_disruption_flights INTEGER,arrival_disruption_classifiable_flights INTEGER);
            INSERT INTO airport_performance_daily VALUES
                ('2025-01-01',1,'destination',1000,100,1000),('2025-01-01',2,'destination',1000,200,1000);
            CREATE TABLE airport_outlook_annual(
                airport_id INTEGER,fiscal_year INTEGER,taf_edition INTEGER,scenario TEXT,
                total_boardings REAL,domestic_boardings REAL,international_boardings REAL,
                commercial_operations REAL,air_carrier_operations REAL,air_taxi_operations REAL);
            INSERT INTO airport_outlook_annual VALUES
                (1,2025,2025,'base',100000,80000,20000,1000,800,200),
                (1,2030,2025,'base',110000,90000,20000,1100,900,200),
                (2,2025,2025,'base',100000,80000,20000,1000,800,200),
                (2,2030,2025,'base',120000,100000,20000,1200,1000,200);
        """)
        for column in ["cancelled_flights", "diverted_flights", "arrival_delay_observed_flights",
                       "arrival_delayed_15_flights", "positive_arrival_delay_minutes", "attribution_eligible_flights",
                       "attribution_complete_flights", "carrier_delay_minutes", "weather_delay_minutes",
                       "nas_delay_minutes", "security_delay_minutes", "late_aircraft_delay_minutes"]:
            connection.execute(f"ALTER TABLE airport_performance_daily ADD COLUMN {column} REAL")
        connection.execute("""UPDATE airport_performance_daily SET cancelled_flights=20,diverted_flights=5,
            arrival_delay_observed_flights=975,arrival_delayed_15_flights=75,positive_arrival_delay_minutes=19500,
            attribution_eligible_flights=75,attribution_complete_flights=50,carrier_delay_minutes=1000,
            weather_delay_minutes=500,nas_delay_minutes=3000,security_delay_minutes=0,late_aircraft_delay_minutes=500""")
        gold.build_analysis_evidence(connection=connection, silver_dir=tmp_path)
        connection.executemany("INSERT INTO analysis_evidence VALUES (?,?,1,'verified inventory','test',?,?,?,?)", [
            ('activity',2024,0,'','calendar',''), ('activity',2025,0,'','calendar',''),
            ('performance',2025,0,'','calendar',''),
            ('outlook',2025,2025,'base','historical','gold-boardings-and-operations-v1'),
            ('outlook',2030,2025,'base','forecast','gold-boardings-and-operations-v1'),
        ])
        connection.commit()
    monkeypatch.setattr(target=dao, name="GOLD_DATABASE_PATH", value=path)
    return path


def calculate(payload: dict):
    """Keep the known-answer cases concise while supplying explicit test periods."""
    metric = payload["metric"]
    request = {**payload.get("selection", {"airport_ids": [1]}), "year": 2025}
    if metric in ("traffic_growth", "demand_capacity_pressure", "terminal_expansion_opportunity"):
        request["baseline_year"] = 2024
    if metric == "terminal_expansion_opportunity":
        request.update(forecast_baseline_year=2025, forecast_edition=2025, forecast_scenario="base")
    if "periods" in payload:
        request.update(baseline_year=payload["periods"]["baseline_year"], year=payload["periods"]["end_year"])
    if "forecast" in payload:
        forecast = payload["forecast"]
        request.update(forecast_baseline_year=forecast["baseline_year"], forecast_edition=forecast["edition"],
                       forecast_scenario=forecast["scenario"])
    return service.analyze({"metric": metric, **request})


@pytest.mark.parametrize("metric", [
    "traffic_growth", "airport_operational_pressure", "outbound_long_haul_share",
    "demand_capacity_pressure", "terminal_expansion_opportunity",
])
@pytest.mark.parametrize("explicit_years", [False, True])
def test_mcp_wrappers_preserve_analysis_evidence(database: Path, metric: str, explicit_years: bool) -> None:
    server = import_module("mcp_server")
    parameters = {"airport_ids": [1]}
    if explicit_years:
        parameters["year"] = 2025
        if metric in ("traffic_growth", "demand_capacity_pressure", "terminal_expansion_opportunity"):
            parameters["baseline_year"] = 2024
        if metric in ("demand_capacity_pressure", "terminal_expansion_opportunity"):
            parameters.update(forecast_baseline_year=2025, forecast_edition=2025, forecast_scenario="base")
    actual = getattr(server, metric)(**parameters)
    expected = service.analyze(request={"metric": metric, **parameters})
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert actual.results

    async def through_mcp() -> None:
        from fastmcp import Client

        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 6
            result = await client.call_tool(name=metric, arguments=parameters)
            assert result.structured_content == expected.model_dump(mode="json")

    asyncio.run(through_mcp())


@pytest.mark.parametrize("parameters", [
    {}, {"airport_ids": []}, {"airport_ids": [1], "region": "West"},
    {"airport_ids": [1], "year": 2024, "baseline_year": 2025},
])
def test_mcp_wrapper_preserves_service_validation(parameters: Dict[str, Any]) -> None:
    server = import_module("mcp_server")
    with pytest.raises(ValidationError):
        server.traffic_growth(**parameters)


@pytest.mark.parametrize("metric,expected,years", [
    ("traffic_growth", {"baseline": 100000, "end": 110000, "absolute_change": 10000, "growth_pct": 10, "cagr_pct": 10}, [2024, 2025]),
    ("airport_operational_pressure", {"arrival_disruption_pct": 10, "disrupted_flights": 100,
                                      "classifiable_flights": 1000, "scheduled_flights": 1000}, [2025]),
    ("outbound_long_haul_share", {"long_haul_share_pct": 100, "long_haul_departures": 100,
                                 "distance_eligible_departures": 100, "observed_departures": 100}, [2025]),
    ("demand_capacity_pressure", {"baseline_passengers": 100000, "end_passengers": 110000,
                                 "baseline_seats": 125000, "end_seats": 125000, "baseline_ratio_pct": 80,
                                 "end_ratio_pct": 88, "ratio_change_pp": 8, "passenger_growth_pct": 10,
                                 "seat_growth_pct": 0, "passenger_seat_growth_gap_pp": 10}, [2024, 2025]),
])
def test_analyze_known_values(database: Path, metric: str, expected: Dict[str, float], years: List[int]) -> None:
    result = calculate({"metric": metric, "selection": {"airport_ids": [1]}})
    assert result.status == "ok"
    assert {key: result.results[0].values[key] for key in expected} == pytest.approx(expected)
    assert [period.get("year") for period in result.periods if period.get("kind") == "calendar"] == years
    assert result.sources[0].get("build_id") == "test"
    assert result.results[0].coverage[0]["pct"] == 100


@pytest.mark.parametrize("metric,sql,status,field,expected", [
    ("traffic_growth", "DROP TABLE analysis_evidence", "partial", "growth_pct", 10),
    ("traffic_growth", "DELETE FROM analysis_evidence WHERE dataset='performance'", "ok", "growth_pct", 10),
    ("traffic_growth", "DELETE FROM route_activity_monthly WHERE reporting_month='2024-01'", "insufficient_evidence", None, None),
    ("traffic_growth", "UPDATE route_activity_monthly SET passengers=0 WHERE reporting_month='2024-01'", "undefined", "growth_pct", None),
    ("traffic_growth", "UPDATE route_activity_monthly SET passenger_observation_count=0 WHERE reporting_month='2025-01'", "partial", "growth_pct", 10),
    ("airport_operational_pressure", "UPDATE airport_performance_daily SET arrival_disruption_classifiable_flights=500", "partial", "arrival_disruption_pct", 20),
    ("airport_operational_pressure", "UPDATE airport_performance_daily SET arrival_disruption_classifiable_flights=0,arrival_disruption_flights=0", "undefined", "arrival_disruption_pct", None),
    ("airport_operational_pressure", "DELETE FROM airport_performance_daily", "insufficient_evidence", None, None),
    ("outbound_long_haul_share", "UPDATE route_activity_monthly SET distance_eligible_departures=50", "partial", "long_haul_share_pct", 100),
    ("outbound_long_haul_share", "UPDATE route_activity_monthly SET distance_miles=1999", "ok", "long_haul_share_pct", 0),
    ("outbound_long_haul_share", "UPDATE route_activity_monthly SET departures=0,distance_eligible_departures=0", "undefined", "long_haul_share_pct", None),
    ("demand_capacity_pressure", "UPDATE route_activity_monthly SET source_record_count=2,passengers=999999,seats=999999", "partial", "passenger_seat_growth_gap_pp", 10),
])
def test_missing_and_partial_evidence(database: Path, metric: str, sql: str, status: str,
                                     field: str | None, expected: float | None) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(sql)
        connection.commit()
    result = calculate({"metric": metric, "selection": {"airport_ids": [1]}})
    assert result.status == status
    airport = result.results[0]
    if field:
        assert airport.values.get(field) == pytest.approx(expected) if expected is not None else airport.values.get(field) is None
    if status != "ok":
        assert not airport.ranking_eligible
        assert airport.exclusions


@pytest.mark.parametrize("selection,ids,scores", [({"airport_ids": [1, 2]}, [2, 1], [100, 0]),
                                                ({"region": "West"}, [1], [0])])
def test_expansion_freezes_national_cohort(database: Path, selection: Dict[str, Any], ids: List[int], scores: List[int]) -> None:
    result = calculate({"metric": "terminal_expansion_opportunity", "selection": selection})
    assert result.status == "ok"
    assert result.cohort_airport_ids == [1, 2]
    assert [item.airport_id for item in result.results] == ids
    assert [item.values.get("score") for item in result.results] == scores
    assert result.results[0].components.get("historical").get("baseline") == 100000
    assert [period.get("kind") for period in result.periods] == ["calendar", "calendar", "fiscal", "fiscal"]


@pytest.mark.parametrize("sql,scores,ranks,cohort", [
    ("UPDATE route_activity_monthly SET passengers=110000 WHERE origin_airport_id=2 AND reporting_month='2025-01';"
     "UPDATE airport_outlook_annual SET total_boardings=110000 WHERE airport_id=2 AND fiscal_year=2030;"
     "UPDATE airport_performance_daily SET arrival_disruption_flights=100 WHERE airport_id=2", [50, 50], [1, 1], [1, 2]),
    ("DELETE FROM airport_performance_daily WHERE airport_id=2", [50], [1], [1]),
    ("UPDATE route_activity_monthly SET passenger_observation_count=0", [], [], []),
    ("UPDATE route_activity_monthly SET passengers=9000 WHERE reporting_month='2024-01'", [], [], []),
    ("UPDATE airport_performance_daily SET scheduled_flights=999,arrival_disruption_classifiable_flights=999", [], [], []),
    ("UPDATE airport_outlook_annual SET total_boardings=90000 WHERE fiscal_year=2030", [], [], []),
])
def test_expansion_ties_and_exclusions(database: Path, sql: str, scores: List[int], ranks: List[int], cohort: List[int]) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(sql)
        connection.commit()
    result = calculate({"metric": "terminal_expansion_opportunity", "selection": {"airport_ids": [2, 1]}})
    ranked = [item for item in result.results if item.ranking_eligible]
    assert result.cohort_airport_ids == cohort
    assert [item.values.get("score") for item in ranked] == scores
    assert [item.rank for item in ranked] == ranks
    assert all(item.exclusions for item in result.results if not item.ranking_eligible)


@pytest.mark.parametrize("sql,overrides,status", [
    ("SELECT 1", {"selection": {"airport_ids": [999]}}, "invalid_input"),
    ("UPDATE analysis_evidence SET complete=0 WHERE dataset='activity' AND year=2025",
     {"periods": {"baseline_year": 2024, "end_year": 2025}}, "partial"),
    ("UPDATE analysis_evidence SET period_type='unknown' WHERE dataset='outlook'",
     {"metric": "terminal_expansion_opportunity"}, "ok"),
    ("UPDATE analysis_evidence SET category='' WHERE dataset='outlook'",
     {"metric": "terminal_expansion_opportunity"}, "ok"),
    ("SELECT 1", {"metric": "terminal_expansion_opportunity", "forecast": {
        "baseline_year": 2025, "end_year": 2030, "edition": 2024, "scenario": "base"}}, "ok"),
])
def test_invalid_selections_and_periods(database: Path, sql: str, overrides: Dict[str, Any], status: str) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(sql)
        connection.commit()
    result = calculate({"metric": "traffic_growth", "selection": {"airport_ids": [1]}, **overrides})
    assert result.status == status


@pytest.mark.parametrize("overrides", [
    {"airport_ids": []}, {"airport_ids": [1], "region": "West"},
    {"airport_ids": [True]}, {"airport_ids": None, "region": "Mars"},
    {"baseline_year": 2026}, {"year": True}, {"year": "2025"},
    {"forecast_baseline_year": 9995},
    {"sql": "SELECT 1"}, {"source": "outlook"}, {"threshold_miles": 1000},
])
def test_request_validation(database: Path, overrides: dict) -> None:
    with pytest.raises(ValidationError):
        service.analyze({"metric": "traffic_growth", "airport_ids": [1], "baseline_year": 2024, "year": 2025, **overrides})


def test_module_size_stays_within_requested_limits() -> None:
    models = import_module("analysis.models")
    model_tree = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))
    service_tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
    assert sum(isinstance(node, ast.ClassDef) for node in model_tree.body) == 3
    assert sum(isinstance(node, ast.FunctionDef) for node in service_tree.body) == 6


@pytest.mark.parametrize("metric", ["traffic_growth", "airport_operational_pressure", "outbound_long_haul_share",
                                   "demand_capacity_pressure", "terminal_expansion_opportunity"])
def test_year_defaults_to_latest_common_period(database: Path, metric: str) -> None:
    result = service.analyze({"metric": metric, "airport_ids": [1]})
    assert result.settings.year == 2025
    assert result.results[0].values
    if metric not in ("airport_operational_pressure", "outbound_long_haul_share"):
        assert result.settings.baseline_year == 2024


def test_expansion_defaults_forecast_settings(database: Path) -> None:
    result = service.analyze({"metric": "terminal_expansion_opportunity", "region": "West"})
    assert result.settings.forecast_baseline_year == 2025
    assert result.settings.forecast_edition == 2025
    assert result.settings.forecast_scenario == "base"
    assert result.results[0].values["score"] == 0


def test_comparison_only_uses_endpoints(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE route_activity_monthly SET reporting_month='2023-01' WHERE reporting_month='2024-01'")
        connection.execute("UPDATE analysis_evidence SET year=2023 WHERE dataset='activity' AND year=2024")
        connection.execute("INSERT INTO route_activity_monthly SELECT '2024-01',origin_airport_id,service_class,distance_miles,"
                           "999999,seats,departures,freight_lbs,ratio_eligible_passengers,ratio_eligible_seats,"
                           "distance_eligible_departures,source_record_count,passenger_observation_count,seat_observation_count,"
                           "departures_observation_count,freight_lbs_observation_count,paired_observation_count "
                           "FROM route_activity_monthly WHERE reporting_month='2023-01'")
        connection.commit()
    result = service.analyze({"metric": "traffic_growth", "airport_ids": [1], "baseline_year": 2023, "year": 2025})
    assert result.results[0].values["baseline"] == 100000
    assert result.results[0].values["end"] == 110000
    assert result.results[0].values["cagr_pct"] == pytest.approx(100 * (1.1 ** 0.5 - 1))


def test_long_haul_is_departure_weighted_and_excludes_other_service(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO route_activity_monthly SELECT reporting_month,origin_airport_id,'F',1000,"
                           "passengers,seats,300,freight_lbs,ratio_eligible_passengers,ratio_eligible_seats,300,"
                           "source_record_count,passenger_observation_count,seat_observation_count,departures_observation_count,"
                           "freight_lbs_observation_count,paired_observation_count FROM route_activity_monthly "
                           "WHERE reporting_month='2025-01' AND origin_airport_id=1")
        connection.execute("INSERT INTO route_activity_monthly SELECT reporting_month,origin_airport_id,'G',distance_miles,"
                           "passengers,seats,departures,freight_lbs,ratio_eligible_passengers,ratio_eligible_seats,"
                           "distance_eligible_departures,source_record_count,passenger_observation_count,seat_observation_count,"
                           "departures_observation_count,freight_lbs_observation_count,paired_observation_count "
                           "FROM route_activity_monthly WHERE reporting_month='2025-01' AND origin_airport_id=1 AND distance_miles=2000")
        connection.commit()
    result = service.analyze({"metric": "outbound_long_haul_share", "airport_ids": [1], "year": 2025})
    assert result.results[0].values["long_haul_share_pct"] == 25


def test_unknown_departures_remain_partial(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE route_activity_monthly SET source_record_count=2 WHERE origin_airport_id=1")
        connection.commit()
    result = service.analyze({"metric": "outbound_long_haul_share", "airport_ids": [1], "year": 2025})
    assert result.status == "partial"
    assert result.results[0].coverage[0]["unknown_records"] == 1


def test_empty_region_is_valid(database: Path) -> None:
    result = service.analyze({"metric": "traffic_growth", "region": "New England", "baseline_year": 2024, "year": 2025})
    assert result.status == "ok"
    assert result.results == []


@pytest.mark.parametrize("metric", ["traffic_growth", "airport_operational_pressure", "outbound_long_haul_share"])
def test_forecast_settings_are_not_silently_ignored(database: Path, metric: str) -> None:
    request = {"airport_ids": [1], "year": 2025, "forecast_baseline_year": 2025,
               "forecast_edition": 2025, "forecast_scenario": "base"}
    if metric in ("traffic_growth", "demand_capacity_pressure"):
        request["baseline_year"] = 2024
    with pytest.raises(ValueError, match="only to expansion"):
        service.analyze({"metric": metric, **request})


@pytest.mark.parametrize("overrides", [{"metric": "unknown"}, {"metric": None}])
def test_unknown_metric_is_rejected(database: Path, overrides: dict) -> None:
    with pytest.raises(ValidationError):
        service.analyze({"airport_ids": [1], "baseline_year": 2024, "year": 2025, **overrides})


def test_model_request_uses_the_same_entry_point(database: Path) -> None:
    models = import_module("analysis.models")
    request = models.AnalysisRequest(metric="traffic_growth", airport_ids=[1], baseline_year=2024, year=2025)
    result = service.analyze(request)
    assert result.results[0].values["growth_pct"] == pytest.approx(10)


def test_operational_panels_and_traffic_context(database: Path) -> None:
    result = service.analyze({"metric": "airport_operational_pressure", "airport_ids": [1, 2]})
    values = result.results[0].values
    assert values["arrival_delay_rate_pct"] == pytest.approx(100 * 75 / 975)
    assert values["mean_positive_arrival_delay_minutes"] == 20
    assert values["cancellation_rate_pct"] == 2
    assert values["departing_passengers"] == 110000
    assert values["offered_seats"] == 125000
    assert result.results[0].components["reported_delay_causes"]["nas_delay_minutes"] == 3000
    coverage = {row.get("measurement"): row for row in result.results[0].coverage}
    assert coverage["delay_attribution"]["pct"] == pytest.approx(100 * 50 / 75)
    assert result.status == "ok"


def test_demand_includes_forecast_operations_and_causes(database: Path) -> None:
    result = service.analyze({"metric": "demand_capacity_pressure", "airport_ids": [1]})
    item = result.results[0]
    assert item.values["passenger_seat_growth_gap_pp"] == pytest.approx(10)
    assert item.components["forecast"]["absolute_change"] == 10000
    assert item.components["operational"]["arrival_delay_rate_pct"] == pytest.approx(100 * 75 / 975)
    assert item.components["reported_delay_causes"]["weather_delay_minutes"] == 500
    assert any("cannot quantify unmet demand" in text for text in result.limitations)


def test_optional_context_does_not_erase_pressure(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM analysis_evidence WHERE dataset IN ('outlook','performance')")
        connection.execute("DELETE FROM airport_performance_daily")
        connection.commit()
    result = service.analyze({"metric": "demand_capacity_pressure", "airport_ids": [1]})
    assert result.status == "ok"
    assert result.results[0].values["ratio_change_pp"] == 8
    assert result.results[0].components["forecast"] == {}
    assert "Optional forecast context unavailable" in result.results[0].exclusions


def test_forecast_crosses_historical_and_forecast_source_codes(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE analysis_evidence SET scenario=CASE WHEN period_type='historical' THEN '0' ELSE '1' END WHERE dataset='outlook'")
        connection.execute("UPDATE airport_outlook_annual SET scenario=CASE WHEN fiscal_year=2025 THEN '0' ELSE '1' END")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1, 2]})
    assert result.settings.forecast_baseline_scenario == "0"
    assert result.settings.forecast_scenario == "1"
    assert result.results[0].values["score"] == 100


def test_ambiguous_forecast_requires_override(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO analysis_evidence SELECT dataset,year,complete,source,build_id,edition,'high',period_type,category FROM analysis_evidence WHERE dataset='outlook' AND period_type='forecast'")
        connection.execute("INSERT INTO airport_outlook_annual SELECT airport_id,fiscal_year,taf_edition,'high',total_boardings,domestic_boardings,international_boardings,commercial_operations,air_carrier_operations,air_taxi_operations FROM airport_outlook_annual WHERE fiscal_year=2030")
        connection.commit()
    ambiguous = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1]})
    assert ambiguous.status == "ok"
    assert ambiguous.results[0].evidence_status == "missing"
    assert ambiguous.results[0].components["historical"]["growth_pct"] == pytest.approx(10)
    explicit = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1], "forecast_scenario": "base"})
    assert explicit.status == "ok"


def test_explicit_missing_year_is_not_replaced(database: Path) -> None:
    result = service.analyze({"metric": "outbound_long_haul_share", "airport_ids": [1], "year": 2022})
    assert result.settings.year == 2022
    assert result.status == "insufficient_evidence"


def test_unknown_forecast_never_blocks_historical_results(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE analysis_evidence SET period_type='unknown' WHERE dataset='outlook'")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1]})
    assert result.status == "ok"
    assert not result.results[0].ranking_eligible
    assert result.results[0].components["historical"]["end"] == 110000
    assert "score" not in result.results[0].values


def test_common_period_is_selected_for_comparison(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO airport_performance_daily SELECT * FROM airport_performance_daily WHERE airport_id=1")
        connection.execute("UPDATE airport_performance_daily SET flight_date='2024-01-01' WHERE rowid=(SELECT MAX(rowid) FROM airport_performance_daily)")
        connection.execute("INSERT INTO analysis_evidence SELECT dataset,2024,complete,source,build_id,edition,scenario,period_type,category FROM analysis_evidence WHERE dataset='performance'")
        connection.commit()
    result = service.analyze({"metric": "airport_operational_pressure", "airport_ids": [1, 2]})
    assert result.settings.year == 2025
    assert all(row.values["scheduled_flights"] == 1000 for row in result.results)


def test_auto_period_does_not_select_explicitly_incomplete_inventory(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE analysis_evidence SET complete=0 WHERE dataset='performance'")
        connection.commit()
    result = service.analyze({"metric": "airport_operational_pressure", "airport_ids": [1]})
    assert result.status == "insufficient_evidence"
    explicit = service.analyze({"metric": "airport_operational_pressure", "airport_ids": [1], "year": 2025})
    assert explicit.status == "partial"
    assert explicit.results[0].values["arrival_disruption_pct"] == 10


def test_expansion_separates_policy_exclusions_from_evidence(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE route_activity_monthly SET passengers=99000 WHERE origin_airport_id=2 AND reporting_month='2025-01'")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1, 2]})
    assert result.status == "ok"
    assert [item.ranking_eligible for item in result.results] == [True, False]
    assert result.evidence_summary["airport_counts"] == {"complete": 2, "partial": 0, "missing": 0, "unverified": 0}
    assert result.national_eligibility["total_airports"] == 2
    assert result.national_eligibility["eligible_airports"] == 1
    assert result.national_eligibility["excluded_airports"] == 1
    assert result.national_eligibility["exclusions_by_reason"] == {
        "Nonpositive historical growth": {"count": 1, "airport_ids": [2]}}
    regional = service.analyze({"metric": "terminal_expansion_opportunity", "region": "West"})
    assert regional.national_eligibility == result.national_eligibility
    assert regional.screening["name"] == "Growth-led expansion screening"
    assert regional.screening["reference_cohort_size"] == 1
    assert regional.screening["historical_period"] == {"kind": "calendar", "baseline_year": 2024, "end_year": 2025}
    assert regional.screening["forecast_period"] == {
        "kind": "fiscal", "baseline_year": 2025, "end_year": 2030, "taf_edition": 2025,
        "baseline_scenario": "base", "scenario": "base"}


def test_expansion_exclusion_counts_overlap_and_preserve_missing_evidence(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM airport_performance_daily WHERE airport_id=2")
        connection.execute("UPDATE route_activity_monthly SET passengers=9000 WHERE origin_airport_id=2 AND reporting_month='2024-01'")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1, 2]})
    assert result.status == "ok"
    assert result.evidence_summary["airport_counts"]["missing"] == 1
    summary = result.national_eligibility
    assert summary["excluded_airports"] == 1
    assert summary["exclusions_by_reason"] == {
        "historical: Below ranking volume minimum": {"count": 1, "airport_ids": [2]},
        "operational: Missing mandatory observations": {"count": 1, "airport_ids": [2]}}


def test_expansion_unverified_sources_are_separate_from_calculation(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE analysis_evidence SET complete=0 WHERE dataset='activity' AND year=2025")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1],
                              "baseline_year": 2024, "year": 2025})
    assert result.status == "ok"
    assert result.results[0].evidence_status == "unverified"
    assert not result.results[0].ranking_eligible
    assert result.national_eligibility["eligible_airports"] == 0
    assert result.national_eligibility["exclusions_by_reason"]["Source completeness unverified"]["count"] == 2
    assert not result.evidence_summary["source_inventory_verified"]


def test_zero_forecast_baseline_is_not_an_evidence_or_eligibility_failure(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE airport_outlook_annual SET total_boardings=0 WHERE fiscal_year=2025")
        connection.execute("UPDATE route_activity_monthly SET passengers=99000 WHERE origin_airport_id=2 AND reporting_month='2025-01'")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1, 2]})
    assert result.results[0].ranking_eligible
    assert result.results[0].evidence_status == "complete"
    assert result.national_eligibility["exclusions_by_reason"] == {
        "Nonpositive historical growth": {"count": 1, "airport_ids": [2]}}


def test_state_search_preserves_missing_airports_and_uses_shared_source_periods(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("ALTER TABLE airport_dimension ADD COLUMN state_code TEXT")
        connection.execute("UPDATE airport_dimension SET state_code='TX' WHERE canonical_airport_id IN (1,2)")
        connection.execute("INSERT INTO airport_dimension VALUES (4,'US','South','TX')")
        connection.commit()
    server = import_module("mcp_server")
    result = server.demand_capacity_pressure(state_code="tx")
    assert result.settings.state_code == "TX"
    assert (result.settings.baseline_year, result.settings.year) == (2024, 2025)
    assert result.airports == [1, 2, 4]
    assert result.status == "partial"
    assert [item.values.get("passenger_growth_pct") for item in result.results[:2]] == pytest.approx([10, 20])
    assert result.results[2].status == "insufficient_evidence"
    assert result.results[2].values == {}
    assert "Missing mandatory observations" in result.results[2].exclusions
    with pytest.raises(ValidationError):
        server.demand_capacity_pressure(state_code="TX", airport_ids=[1])
    with pytest.raises(ValidationError):
        server.demand_capacity_pressure(state_code="TX", region="South")


def test_region_search_does_not_let_inactive_airport_block_available_results(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO airport_dimension VALUES (4,'US','West')")
        connection.commit()
    result = service.analyze({"metric": "traffic_growth", "region": "West"})
    assert result.airports == [1, 4]
    assert result.settings.year == 2025
    assert result.results[0].values["growth_pct"] == pytest.approx(10)
    assert result.results[1].status == "insufficient_evidence"


def test_evidence_contract_preserves_denominators_periods_and_partial_coverage(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE route_activity_monthly SET source_record_count=2 WHERE origin_airport_id=1")
        connection.commit()
    result = service.analyze({"metric": "demand_capacity_pressure", "airport_ids": [1]})
    definition = result.metric_definitions["mean_positive_arrival_delay_minutes"]
    assert definition["numerator"] == "positive_arrival_delay_minutes"
    assert definition["denominator"] == "arrival_delay_observed_flights"
    assert definition["unit"] == "minutes per observed completed arrival"
    assert result.sources[0]["original_dataset"] == "BTS T-100 Segment (All Carriers)"
    assert result.forecast_metadata["edition"] == 2025
    assert result.forecast_metadata["baseline_label"] == "FY2025"
    assert result.forecast_metadata["endpoint_label"] == "FY2030"
    summary = result.answer_summary
    assert summary["airports"][0]["status"] == "partial"
    assert "Incomplete measurement coverage" in summary["airports"][0]["exclusions"]
    assert summary["airports"][0]["measurement_coverage"][0]["pct"] == 50


def test_ranking_summary_separates_score_rank_and_exact_exclusions(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE route_activity_monthly SET passengers=90000 WHERE origin_airport_id=1 AND reporting_month='2025-01'")
        connection.commit()
    result = service.analyze({"metric": "terminal_expansion_opportunity", "region": "West"})
    assert result.answer_summary["leading_candidate"] is None
    assert result.answer_summary["airports"][0]["exclusions"] == ["Positive historical growth and forecast additions are required"]
    national = service.analyze({"metric": "terminal_expansion_opportunity", "airport_ids": [1, 2]})
    leader = national.answer_summary["leading_candidate"]
    assert leader["airport_id"] == 2
    assert leader["score_points"] == 50
    assert leader["national_rank"] == 1
    assert national.metric_definitions["score"]["unit"] == "screening points (0–100), not a percentile"


def test_broad_search_requires_an_airport_observed_at_both_endpoints(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE airport_dimension SET us_region='West' WHERE canonical_airport_id=2")
        connection.execute("DELETE FROM route_activity_monthly WHERE (origin_airport_id=1 AND reporting_month='2025-01') OR (origin_airport_id=2 AND reporting_month='2024-01')")
        connection.commit()
    result = service.analyze({"metric": "demand_capacity_pressure", "region": "West"})
    assert result.status == "insufficient_evidence"
    assert result.settings.year is None
