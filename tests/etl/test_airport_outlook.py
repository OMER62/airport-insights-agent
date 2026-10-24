from importlib import import_module

import pandas as pd
import pytest

task = import_module("etl.tasks.t4_airport_outlook")
error = import_module("etl.errors").EtlValidationError


def inputs_at(path):
    passengers, operations, metadata, airports = (path / name for name in
        ["Enplanements.csv", "AirportsOperations.csv", "Airports.csv", "lookup.csv"])
    pd.DataFrame([
        [" LAX ", "0", 2024, 0, "", "NULL", 1, 2],
        ["LAX", "1", 2030, 100, 2, 3, 4, 5],
        ["XXX", "1", 2030, 10, 0, 0, 0, 0],
    ], columns=["locid", "scenario", "ayear", *task.PASSENGERS]).to_csv(passengers, index=False)
    pd.DataFrame([
        ["LAX", "1", 2030, 50, 0],
        ["JFK", "1", 2030, 30, 0],
    ], columns=["locid", "scenario", "ayear", *task.OPERATIONS]).to_csv(operations, index=False)
    pd.DataFrame({"LOCID": ["LAX", "JFK", "XXX"]}).to_csv(metadata, index=False)
    pd.DataFrame({"airport_id": [12892, 12478], "airport_code": ["LAX", "JFK"],
                  "faa_locid": ["LAX", "JFK"]}).to_csv(airports, index=False)
    pd.DataFrame({"origin_id": [12892], "destination_id": [12478]}).to_csv(path / "flight_activity.csv", index=False)
    task.mapping_audit_path(airports).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"airport_id": [12892, 12478], "airport_code": ["LAX", "JFK"],
                  "faa_locid": ["LAX", "JFK"], "status": ["mapped", "mapped"],
                  "reason": ["verified", "verified"], "candidate_faa_locids": ["LAX", "JFK"],
                  "canonical_airport_id": [12892, 12478]}).to_csv(task.mapping_audit_path(airports), index=False)
    return airports


def test_full_outer_join_bts_ids_and_nulls(tmp_path):
    airports = inputs_at(tmp_path)
    output = tmp_path / "outlook.csv"
    assert task.run(tmp_path, airports, output)
    result = pd.read_csv(output, dtype={"scenario": "string"})
    assert list(result) == task.COLUMNS
    assert len(result) == 3
    assert set(result.airport_id) == {12892, 12478}
    assert result.taf_edition.eq(2025).all()
    lax_old = result.loc[result.fiscal_year.eq(2024)].iloc[0]
    assert lax_old.domestic_passengers == 0
    assert pd.isna(lax_old.air_taxi_passengers)
    assert pd.isna(lax_old.commuter_passengers)
    assert pd.isna(lax_old.air_carrier_operations)
    jfk = result.loc[result.airport_id.eq(12478)].iloc[0]
    assert pd.isna(jfk.domestic_passengers)
    assert jfk.air_taxi_operations == 0
    assert {path.name for path in tmp_path.glob("outlook*")} == {"outlook.csv"}


@pytest.mark.parametrize("kind", ["duplicate_source", "ambiguous_mapping", "invalid_number", "no_resolved"])
def test_invalid_input_preserves_output(tmp_path, kind):
    airports = inputs_at(tmp_path)
    output = tmp_path / "outlook.csv"
    output.write_text("previous output", encoding="utf-8")
    if kind == "duplicate_source":
        source = tmp_path / "Enplanements.csv"
        frame = pd.read_csv(source)
        pd.concat([frame, frame.iloc[[0]]]).to_csv(source, index=False)
    elif kind == "ambiguous_mapping":
        pd.DataFrame({"airport_id": [12892, 12478], "faa_locid": ["LAX", "LAX"]}).to_csv(airports, index=False)
    elif kind == "invalid_number":
        source = tmp_path / "AirportsOperations.csv"
        frame = pd.read_csv(source, dtype="string")
        frame.loc[0, "itn_Ac"] = "-1"
        frame.to_csv(source, index=False)
    else:
        pd.DataFrame({"airport_id": [12892], "faa_locid": [""]}).to_csv(airports, index=False)
    assert not task.run(tmp_path, airports, output, overwrite=True)
    assert output.read_text(encoding="utf-8") == "previous output"


def test_final_key_collision_rejected(tmp_path):
    airports = inputs_at(tmp_path)
    frame = task.build(tmp_path, airports)
    with pytest.raises(error, match="Duplicate final key"):
        task.validate(pd.concat([frame, frame.iloc[[0]]]), airports)


def test_unresolved_relevant_airport_blocks_publication_with_logged_reason(tmp_path, caplog):
    airports = inputs_at(tmp_path)
    lookup = pd.read_csv(airports, keep_default_na=False)
    lookup.loc[lookup.airport_code.eq("JFK"), "faa_locid"] = ""
    lookup.to_csv(airports, index=False)
    path = task.mapping_audit_path(airports)
    audit = pd.read_csv(path, keep_default_na=False)
    audit.loc[audit.airport_code.eq("JFK"), ["faa_locid", "status", "reason"]] = ["", "unmapped", "ambiguous_identity"]
    audit.to_csv(path, index=False)
    output = tmp_path / "outlook.csv"
    output.write_text("previous output", encoding="utf-8")
    assert not task.run(tmp_path, airports, output, overwrite=True)
    assert output.read_text(encoding="utf-8") == "previous output"
    assert "ambiguous_identity" in caplog.text
    assert "12478" in caplog.text
    assert {path.name for path in tmp_path.glob("outlook*")} == {"outlook.csv"}


def test_stale_mapping_audit_is_rejected(tmp_path):
    airports = inputs_at(tmp_path)
    path = task.mapping_audit_path(airports)
    audit = pd.read_csv(path)
    audit.loc[0, "faa_locid"] = "WRONG"
    audit.to_csv(path, index=False)
    assert not task.run(tmp_path, airports, tmp_path / "outlook.csv")


def test_verified_bts_aliases_retain_both_identities(tmp_path):
    airports = inputs_at(tmp_path)
    lookup = pd.read_csv(airports)
    alias = lookup.iloc[[1]].copy()
    alias["airport_id"] = 99999
    alias["airport_code"] = "ALIAS"
    pd.concat([lookup, alias]).to_csv(airports, index=False)
    path = task.mapping_audit_path(airports)
    audit = pd.read_csv(path)
    alias_audit = audit.iloc[[1]].copy()
    alias_audit["airport_id"] = 99999
    alias_audit["airport_code"] = "ALIAS"
    audit = pd.concat([audit, alias_audit], ignore_index=True)
    audit.loc[audit.faa_locid.eq("JFK"), "reason"] = "verified_bts_aliases_share_one_faa_series"
    audit.to_csv(path, index=False)
    output = tmp_path / "outlook.csv"
    assert task.run(tmp_path, airports, output)
    result = pd.read_csv(output)
    assert set(result.airport_id) == {12892, 12478, 99999}
    assert result.loc[result.airport_id.isin([12478, 99999]), "air_carrier_operations"].tolist() == [30, 30]
