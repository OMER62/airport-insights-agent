import argparse
import logging
from pathlib import Path

import pandas as pd

from .. import log_
from ..errors import EtlValidationError
from ..initializer import initialize_generated
from .t3_airports import mapping_audit_path, read_csv

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/raw/FAA-TAF"
DEFAULT_AIRPORTS = ROOT / "data/silver/airports.csv"
DEFAULT_OUTPUT = ROOT / "data/silver/airport_outlook.csv"
# The user identified this download as edition 2025; it is absent from the raw CSVs.
TAF_EDITION = 2025
SOURCE_KEY = ["locid", "fiscal_year", "scenario"]
KEY = ["airport_id", "fiscal_year", "taf_edition", "scenario"]
PASSENGERS = {
    "aac": "domestic_passengers",
    "aat": "air_taxi_passengers",
    "commuter": "commuter_passengers",
    "us_flag": "international_us_passengers",
    "frgn_flag": "international_foreign_passengers",
}
OPERATIONS = {"itn_Ac": "air_carrier_operations", "itn_at": "air_taxi_operations"}
MEASURES = [*PASSENGERS.values(), *OPERATIONS.values()]
COLUMNS = [*KEY, *MEASURES]


def integers(values, name, nullable=False):
    values = values.str.strip()
    if nullable:
        values = values.mask(values.str.upper().isin(["", "NULL"]))
    valid = values.str.fullmatch(r"[0-9]+")
    if not (valid.fillna(False) | (values.isna() & nullable)).all():
        raise EtlValidationError(f"{name}: expected {'nullable ' if nullable else ''}nonnegative integers")
    try:
        return values.astype("Int64")
    except (ValueError, TypeError, OverflowError) as error:
        raise EtlValidationError(f"{name}: invalid or out-of-range integer") from error


def activity(path, measures):
    frame = read_csv(path, ["locid", "ayear", "scenario", *measures])
    frame = frame.rename(columns={"ayear": "fiscal_year", **measures})
    for name in ["locid", "scenario"]:
        frame[name] = frame[name].str.strip()
        if frame[name].eq("").any():
            raise EtlValidationError(f"{path}: missing key field {name}")
    frame["fiscal_year"] = integers(frame.fiscal_year, "fiscal_year")
    if not frame.fiscal_year.between(1000, 9999).all():
        raise EtlValidationError(f"{path}: fiscal_year must be a four-digit year")
    for name in measures.values():
        frame[name] = integers(frame[name], name, nullable=True)
    if frame.duplicated(SOURCE_KEY).any():
        raise EtlValidationError(f"{path}: duplicate source key {SOURCE_KEY}")
    log_.info(f"Validated {len(frame):,} records from {path.name}")
    return frame


def airport_lookup(path, mapping_audit=None):
    frame = read_csv(path, ["airport_id", "faa_locid"])
    frame["airport_id"] = integers(frame.airport_id, "airport_id")
    if frame.airport_id.le(0).any() or frame.airport_id.duplicated().any():
        raise EtlValidationError("airports: airport_id must be positive and unique")
    frame["locid"] = frame.faa_locid.str.strip()
    resolved = frame.loc[frame.locid.ne(""), ["airport_id", "locid"]]
    if resolved.locid.duplicated().any():
        audit_path = Path(mapping_audit) if mapping_audit is not None else mapping_audit_path(path)
        if not audit_path.is_file():
            raise EtlValidationError("airports: ambiguous faa_locid mapping without verified alias audit")
        audit = read_csv(audit_path, ["airport_id", "faa_locid", "canonical_airport_id", "reason"])
        for locid, group in resolved.groupby("locid"):
            if len(group) == 1:
                continue
            aliases = audit.loc[audit.airport_id.isin(group.airport_id.astype(str))]
            if (len(aliases) != len(group) or not aliases.faa_locid.eq(locid).all()
                    or not aliases.reason.eq("verified_bts_aliases_share_one_faa_series").all()
                    or aliases.canonical_airport_id.nunique() != 1
                    or aliases.canonical_airport_id.iloc[0] not in set(aliases.airport_id)):
                raise EtlValidationError("airports: ambiguous faa_locid mapping")
    return frame, resolved


def build(input_dir, airports_path, mapping_audit=None):
    passengers = activity(input_dir / "Enplanements.csv", PASSENGERS)
    operations = activity(input_dir / "AirportsOperations.csv", OPERATIONS)
    metadata = read_csv(input_dir / "Airports.csv", ["LOCID"])
    known_locids = set(metadata.LOCID.str.strip())
    joined = passengers.merge(operations, on=SOURCE_KEY, how="outer", validate="one_to_one", indicator=True)
    if not set(joined.locid).issubset(known_locids):
        raise EtlValidationError("Activity locids absent from FAA airport metadata")
    log_.info(f"Full outer join: {len(joined):,} rows; source coverage: {joined['_merge'].value_counts().to_dict()}")
    _, mapping = airport_lookup(airports_path, mapping_audit)
    source_coverage = joined.groupby("locid").agg(source_rows=("fiscal_year", "size"),
                                                   first_fiscal_year=("fiscal_year", "min"),
                                                   last_fiscal_year=("fiscal_year", "max")).reset_index()
    joined = joined.merge(mapping, on="locid", how="left", validate="many_to_many")
    unresolved = joined.airport_id.isna()
    log_.info(f"FAA rows outside verified BTS mapping: {int(unresolved.sum()):,}; coverage audits required before publication")
    result = joined.loc[~unresolved].copy()
    result["airport_id"] = result.airport_id.astype("Int64")
    result["taf_edition"] = pd.Series(TAF_EDITION, index=result.index, dtype="Int64")
    for name in MEASURES:
        result[name] = result[name].astype("Int64")
    log_.info(f"Resolved source coverage: {result['_merge'].value_counts().to_dict()}")
    result = result[COLUMNS].sort_values(KEY).reset_index(drop=True)
    result.attrs["source_coverage"] = source_coverage.to_dict("records")
    return result


def coverage(frame, airports_path, mapping_audit, flight_activity):
    source_coverage = pd.DataFrame(frame.attrs["source_coverage"])
    airports = read_csv(airports_path)
    audit = read_csv(mapping_audit)
    required = {"airport_id", "airport_code", "faa_locid", "status", "reason", "candidate_faa_locids", "canonical_airport_id"}
    if not required.issubset(audit.columns):
        raise EtlValidationError(f"Mapping audit missing fields: {sorted(required - set(audit.columns))}")
    if audit.airport_id.duplicated().any() or set(audit.airport_id) != set(airports.airport_id):
        raise EtlValidationError("Mapping audit must cover every lookup airport exactly once; rebuild airports")
    comparison = airports.merge(audit, on="airport_id", suffixes=("_lookup", "_audit"), validate="one_to_one")
    for field in ["faa_locid", "airport_code"]:
        if not comparison[field + "_lookup"].eq(comparison[field + "_audit"]).all():
            raise EtlValidationError("Mapping audit is stale; rebuild airports")
    if (not audit.status.isin(["mapped", "unmapped", "intentionally_excluded"]).all()
            or audit.reason.eq("").any()
            or not audit.status.eq("mapped").eq(audit.faa_locid.ne("")).all()):
        raise EtlValidationError("Mapping audit has invalid status, reason or identifier")
    canonical = audit.set_index("airport_id").faa_locid
    if (not audit.canonical_airport_id.isin(audit.airport_id).all()
            or not audit.loc[audit.status.eq("mapped"), "canonical_airport_id"].map(canonical).eq(
                audit.loc[audit.status.eq("mapped"), "faa_locid"]).all()):
        raise EtlValidationError("Mapping audit canonical identities must reference the same FAA airport")
    relevant = set()
    for chunk in read_csv(flight_activity, ["origin_id", "destination_id"], chunksize=50000):
        relevant.update(chunk.origin_id.str.strip())
        relevant.update(chunk.destination_id.str.strip())
    if relevant - set(audit.airport_id):
        raise EtlValidationError(f"Flight airports absent from lookup/audit: {sorted(relevant - set(audit.airport_id))}")
    counts = frame.groupby("airport_id").size()
    audit["in_flight_activity"] = audit.airport_id.isin(relevant)
    audit["outlook_rows"] = audit.airport_id.map(counts.rename(index=str)).fillna(0).astype(int)
    audit["has_taf_activity"] = audit.faa_locid.isin(source_coverage.locid)
    audit["coverage_status"] = audit.status
    no_activity = audit.status.eq("mapped") & ~audit.has_taf_activity
    audit.loc[no_activity, "coverage_status"] = "intentionally_excluded"
    audit.loc[no_activity, "reason"] = "verified_faa_airport_has_no_activity_in_this_taf_edition"
    lost = audit.status.eq("mapped") & audit.has_taf_activity & audit.outlook_rows.eq(0)
    audit.loc[lost, "coverage_status"] = "unmapped"
    audit.loc[lost, "reason"] = "verified_mapping_with_source_activity_missing_from_output"
    return audit


def validate(frame, airports_path, mapping_audit=None):
    if frame.empty:
        raise EtlValidationError("No resolved outlook records; output would be empty")
    if frame[KEY].isna().any().any() or frame.scenario.str.strip().eq("").any():
        raise EtlValidationError("Missing required airport_outlook key")
    if frame.duplicated(KEY).any():
        raise EtlValidationError(f"Duplicate final key {KEY}")
    airports, _ = airport_lookup(airports_path, mapping_audit)
    if not frame.airport_id.isin(airports.airport_id).all():
        raise EtlValidationError("Outlook airport IDs absent from airports lookup")
    if not frame.taf_edition.eq(TAF_EDITION).all():
        raise EtlValidationError("Expected TAF edition 2025")
    log_.info(f"Validated final keys and airport foreign keys; fiscal years "
              f"{frame.fiscal_year.min()}–{frame.fiscal_year.max()}, airports {frame.airport_id.nunique():,}")
    log_.info(f"Missing measurements preserved: {frame[MEASURES].isna().sum().to_dict()}")


def run(input_dir=DEFAULT_INPUT, airports=DEFAULT_AIRPORTS, output=DEFAULT_OUTPUT, overwrite=False,
        flight_activity=None, mapping_audit=None):
    input_dir, airports, output = Path(input_dir), Path(airports), Path(output)
    inputs = [input_dir / name for name in ["Enplanements.csv", "AirportsOperations.csv", "Airports.csv"]]
    flight_activity = Path(flight_activity) if flight_activity is not None else airports.with_name("flight_activity.csv")
    mapping_audit = Path(mapping_audit) if mapping_audit is not None else mapping_audit_path(airports)

    def check(frame):
        validate(frame, airports, mapping_audit)
        audit = coverage(frame, airports, mapping_audit, flight_activity)
        log_.info(f"Airport coverage: {audit.coverage_status.value_counts().to_dict()}")
        blocked = audit.in_flight_activity & audit.coverage_status.eq("unmapped")
        if blocked.any():
            raise EtlValidationError(f"Unresolved relevant FAA mappings: {audit.loc[blocked, ['airport_id', 'airport_code', 'reason']].to_dict('records')}")

    return initialize_generated(inputs=[*inputs, airports, flight_activity, mapping_audit], output=output,
                                   build=lambda: build(input_dir, airports, mapping_audit), validate=check, overwrite=overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the 2025 FAA TAF airport outlook with BTS airport IDs")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--airports", type=Path, default=DEFAULT_AIRPORTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--flight-activity", type=Path)
    parser.add_argument("--mapping-audit", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(0 if run(**vars(parser.parse_args())) else 1)
