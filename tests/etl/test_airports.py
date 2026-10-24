from importlib import import_module

import pandas as pd
import pytest

task = import_module("etl.tasks.t3_airports")
runner = import_module("etl.runner")
error = import_module("etl.errors").EtlValidationError


def test_latest_details_rejects_same_month_conflict():
    records = [
        ["10001", "OLD", "Town", "CA", "US", 202401],
        ["10001", "NEW", "Town", "CA", "US", 202501],
    ]
    frame = pd.DataFrame(records, columns=[*task.DETAILS, "period"])
    assert task.latest_details(frame).iloc[0].airport_code == "NEW"
    frame.loc[1, "period"] = 202401
    with pytest.raises(error, match="Conflicting"):
        task.latest_details(frame)


def test_extract_both_route_sides_preserves_codes(tmp_path):
    path = tmp_path / "routes.csv"
    columns = ["YEAR", "MONTH", *task.T100["ORIGIN"], *task.T100["DEST"]]
    pd.DataFrame([[2025, 1, 10001, "00F", "Broadus", "MT", "US",
                   10002, "XYZ", "Town", "CA", "US"]], columns=columns).to_csv(path, index=False)
    result = task.extract([path], chunksize=1)
    assert set(result.airport_id) == {"10001", "10002"}
    assert "00F" in set(result.airport_code)


def test_enrichment_uses_crosswalk_and_rejects_wrong_location(tmp_path):
    airports = pd.DataFrame([
        ["10001", "AAA", "Town", "CA", "US"],
        ["10002", "BBB", "Other", "CA", "US"],
    ], columns=task.DETAILS)
    names, oa, taf = (tmp_path / filename for filename in ["names.csv", "oa.csv", "taf.csv"])
    pd.DataFrame([["10001", "Town, CA: Example Internationál"],
                  ["10002", "Other, CA: Other Municipal"]],
                 columns=["Code", "Description"]).to_csv(names, index=False, encoding="cp1252")
    pd.DataFrame([
        [1, "AAA", "01A", "Example International Airport", "US", "US-CA", 34, -118],
        [2, "BBB", "BBB", "Other Municipal Airport", "US", "US-CA", 36, -120],
    ], columns=["id", "iata_code", "local_code", "name", "iso_country", "iso_region",
                "latitude_deg", "longitude_deg"]).to_csv(oa, index=False)
    pd.DataFrame([
        ["01A", "Example International", "Town", "CA", "34-00-00N", "118-00-00W"],
        ["BBB", "Other Municipal", "Other", "CA", "39-00-00N", "118-00-00W"],
    ], columns=["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]).to_csv(taf, index=False)
    result = task.enrich(airports, names, oa, taf)
    assert result.faa_locid.tolist() == ["01A", ""]
    assert result.name.tolist() == ["Example Internationál", "Other Municipal"]


def test_missing_foreign_key_prevents_publication(tmp_path):
    source, output = tmp_path / "flight.csv", tmp_path / "airports.csv"
    pd.DataFrame({"origin_id": [10001], "destination_id": [10002]}).to_csv(source, index=False)
    output.write_text("previous output", encoding="utf-8")
    frame = pd.DataFrame({"airport_id": [10001]})
    success = runner.run_generated_csv(
        [source], output, lambda: frame,
        validate=lambda result: task.validate_coverage(result, [source]), overwrite=True,
    )
    assert not success
    assert output.read_text(encoding="utf-8") == "previous output"


@pytest.mark.parametrize("code,bts_name,oa_name,faa_name,bts_state,oa_state,faa_state,new_code", [
    ("BOS", "Logan International", "Boston Logan International Airport", "General Edward Lawrence Logan International", "MA", "MA", "MA", "BOS"),
    ("IAH", "George Bush Intercontinental/Houston", "George Bush Intercontinental Airport", "George Bush Intcntl/Houston", "TX", "TX", "TX", "IAH"),
    ("MSP", "Minneapolis-St Paul International", "Minneapolis-Saint Paul International / Wold-Chamberlain Field", "Minneapolis-St Paul Intl", "MN", "MN", "MN", "MSP"),
    ("IAD", "Washington Dulles International", "Washington Dulles International Airport", "Washington Dulles Intl", "VA", "VA", "DC", "IAD"),
    ("DCA", "Ronald Reagan Washington National", "Ronald Reagan Washington National Airport", "Ronald Reagan Washington National", "VA", "DC", "DC", "DCA"),
    ("PBI", "Donald J Trump International", "President Donald J. Trump International Airport", "Palm Beach International", "FL", "FL", "FL", "DJT"),
])
def test_major_airports_survive_name_state_and_identifier_changes(
        tmp_path, code, bts_name, oa_name, faa_name, bts_state, oa_state, faa_state, new_code):
    airports = pd.DataFrame([["10001", code, "City", bts_state, "US"]], columns=task.DETAILS)
    names, oa, taf = (tmp_path / filename for filename in ["names.csv", "oa.csv", "taf.csv"])
    pd.DataFrame([["10001", f"City: {bts_name}"]], columns=["Code", "Description"]).to_csv(names, index=False)
    pd.DataFrame([[1, f"K{code}", new_code, new_code, oa_name, "US", f"US-{oa_state}", 34, -118]],
                 columns=["id", "ident", "iata_code", "local_code", "name", "iso_country", "iso_region",
                          "latitude_deg", "longitude_deg"]).to_csv(oa, index=False)
    pd.DataFrame([[code, faa_name, "City", faa_state, "34-00-00N", "118-00-00W"]],
                 columns=["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]).to_csv(taf, index=False)
    result = task.enrich(airports, names, oa, taf)
    assert result.faa_locid.item() == code
    assert result.attrs["mapping_audit"][0]["status"] == "mapped"


def test_reassigned_local_code_does_not_map_unrelated_airport(tmp_path):
    airports = pd.DataFrame([["10001", "A63", "Coal Creek", "AK", "US"]], columns=task.DETAILS)
    names, oa, taf = (tmp_path / filename for filename in ["names.csv", "oa.csv", "taf.csv"])
    pd.DataFrame([["10001", "Coal Creek: Coal Creek"]], columns=["Code", "Description"]).to_csv(names, index=False)
    pd.DataFrame([[1, "A63", "TWA", "A63", "Twin Hills Airport", "US", "US-AK", 34, -118]],
                 columns=["id", "ident", "iata_code", "local_code", "name", "iso_country", "iso_region",
                          "latitude_deg", "longitude_deg"]).to_csv(oa, index=False)
    pd.DataFrame([["A63", "Twin Hills", "Twin Hills", "AK", "34-00-00N", "118-00-00W"]],
                 columns=["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]).to_csv(taf, index=False)
    result = task.enrich(airports, names, oa, taf)
    assert result.faa_locid.item() == ""
    assert "corroboration" in result.attrs["mapping_audit"][0]["reason"]


def test_reassigned_icao_code_recovers_original_airport_by_exact_name_and_city(tmp_path):
    airports = pd.DataFrame([["17054", "MO6", "Lees Summit, MO", "MO", "US"]], columns=task.DETAILS)
    names, oa, taf = (tmp_path / filename for filename in ["names.csv", "oa.csv", "taf.csv"])
    pd.DataFrame([["17054", "Lees Summit: Kansas City Lees Summit Regional"]], columns=["Code", "Description"]).to_csv(names, index=False)
    pd.DataFrame([
        [1, "KMO6", "", "FYG", "Washington Regional Airport", "US", "US-MO", 38, -90],
        [2, "KLXT", "", "LXT", "Lee's Summit Municipal Airport", "US", "US-MO", 39, -94],
    ], columns=["id", "ident", "iata_code", "local_code", "name", "iso_country", "iso_region",
                "latitude_deg", "longitude_deg"]).to_csv(oa, index=False)
    pd.DataFrame([
        ["FYG", "Washington Regional", "Washington", "MO", "38-00-00N", "90-00-00W"],
        ["LXT", "Kansas City/Lee's Summit Regional", "Lee's Summit", "MO", "39-00-00N", "94-00-00W"],
    ], columns=["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]).to_csv(taf, index=False)
    result = task.enrich(airports, names, oa, taf)
    assert result.faa_locid.item() == "LXT"
    assert "historical_identifier_change" in result.attrs["mapping_audit"][0]["mapping_method"]


@pytest.mark.parametrize("code,bts_name,reference_code,reference_name,city", [
    ("NPA", "Pensacola NAS", "PNS", "Pensacola International", "Pensacola"),
    ("NCO", "Quonset State Air Reserve National Guard Helipad", "OQU", "Quonset State", "North Kingstown"),
])
def test_distinct_military_or_heliport_identity_is_not_fuzzy_matched_to_city_airport(
        tmp_path, code, bts_name, reference_code, reference_name, city):
    airports = pd.DataFrame([["10001", code, city, "RI", "US"]], columns=task.DETAILS)
    names, oa, taf = (tmp_path / filename for filename in ["names.csv", "oa.csv", "taf.csv"])
    pd.DataFrame([["10001", f"{city}: {bts_name}"]], columns=["Code", "Description"]).to_csv(names, index=False)
    pd.DataFrame([[1, f"K{reference_code}", code if code == "NCO" else reference_code, reference_code,
                   reference_name, "US", "US-RI", 34, -118, "medium_airport"]],
                 columns=["id", "ident", "iata_code", "local_code", "name", "iso_country", "iso_region",
                          "latitude_deg", "longitude_deg", "type"]).to_csv(oa, index=False)
    pd.DataFrame([[reference_code, reference_name, city, "RI", "34-00-00N", "118-00-00W"]],
                 columns=["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]).to_csv(taf, index=False)
    result = task.enrich(airports, names, oa, taf)
    assert result.faa_locid.item() == ""
