from importlib import import_module
from unittest.mock import patch

import pandas as pd
import pytest

task = import_module("etl.tasks.t2_flight_performance")
runner = import_module("etl.runner")
error = import_module("etl.errors").EtlValidationError


def row(month=1):
    return dict(zip(task.COLUMNS, [f"2025-{month:02d}-01", "19805", "0012", "10001", "10002",
                                  "0015", "2400", "-2", "", "1.00", "A", "0.00",
                                  "", "0", "", "", ""]))


def frame(values):
    return pd.DataFrame(values, dtype="string")


def inputs_at(path):
    path.mkdir()
    for month in range(1, 13):
        frame([row(month)]).to_csv(path / f"On_Time_Reporting_Carrier_On_Time_Performance_2025_{month:02d}.csv", index=False)


def test_transform_preserves_semantics():
    result = task.transform(frame([row()]), "flight_performance_2025_01")
    assert len(result.columns) == 18
    assert result.iloc[0].flight_number == "0012"
    assert result.iloc[0].scheduled_departure_time == "0015"
    assert result.iloc[0].scheduled_arrival_time == "2400"
    assert result.iloc[0].departure_delay_minutes == -2
    assert pd.isna(result.iloc[0].arrival_delay_minutes)
    assert pd.isna(result.iloc[0].carrier_delay_minutes)
    assert result.iloc[0].weather_delay_minutes == 0
    assert result.iloc[0].cancelled


@pytest.mark.parametrize("column,value", [("FlightDate", "2025-02-30"), ("FlightDate", "2025-02-01"),
    ("CRSDepTime", "2500"), ("CRSArrTime", "15"), ("DepDelay", "1.5"),
    ("Cancelled", "2"), ("CancellationCode", ""), ("OriginAirportID", ""),
    ("WeatherDelay", "inf"), ("DestAirportID", "10001")])
def test_invalid_records(column, value):
    values = row()
    values[column] = value
    with pytest.raises(error):
        task.transform(frame([values]), "flight_performance_2025_01")


def test_monthly_publication_and_overwrite(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    assert task.run(source, output, chunksize=1)
    assert len(list(output.glob("*.csv"))) == 12
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert not task.run(source, output)
    assert task.run(source, output, overwrite=True, chunksize=1)
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_duplicate_across_chunks_preserves_existing(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    output.mkdir()
    (output / "existing.csv").write_text("previous")
    frame([row(), row()]).to_csv(source / "On_Time_Reporting_Carrier_On_Time_Performance_2025_01.csv", index=False)
    assert not task.run(source, output, overwrite=True, chunksize=1)
    assert (output / "existing.csv").read_text() == "previous"
    assert len(list(output.iterdir())) == 1


def test_missing_month_publishes_nothing(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    (source / "On_Time_Reporting_Carrier_On_Time_Performance_2025_12.csv").unlink()
    assert not task.run(source, output)
    assert not output.exists()


def test_publication_failure_restores_previous_set(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    output.mkdir()
    (output / "previous.csv").write_text("old")
    replace = runner.os.replace

    def fail_stage(src, dst):
        if src.name == "data":
            raise OSError("injected publication failure")
        return replace(src, dst)

    with patch.object(runner.os, "replace", side_effect=fail_stage):
        assert not task.run(source, output, overwrite=True)
    assert (output / "previous.csv").read_text() == "old"
    assert len(list(output.iterdir())) == 1


def test_final_month_failure_publishes_nothing(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    invalid = row(12)
    invalid["Cancelled"] = "2"
    frame([invalid]).to_csv(source / "On_Time_Reporting_Carrier_On_Time_Performance_2025_12.csv", index=False)
    assert not task.run(source, output)
    assert not output.exists()


def test_existing_lock_is_preserved(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "silver"
    inputs_at(source)
    lock = tmp_path / "silver.lock"
    lock.write_text("another writer")
    assert not task.run(source, output)
    assert lock.read_text() == "another writer"
    assert not output.exists()
