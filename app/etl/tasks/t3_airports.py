import argparse
import logging
import math
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from .. import log_
from ..errors import EtlInputError, EtlValidationError
from ..initializer import initialize_generated
from ..runner import _write_csv

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw"
SILVER = ROOT / "data/silver"
COLUMNS = ["airport_id", "airport_code", "faa_locid", "name", "city", "state_code", "country_code"]
DETAILS = ["airport_id", "airport_code", "city", "state_code", "country_code"]
T100 = {
    "ORIGIN": ["ORIGIN_AIRPORT_ID", "ORIGIN", "ORIGIN_CITY_NAME", "ORIGIN_STATE_ABR", "ORIGIN_COUNTRY"],
    "DEST": ["DEST_AIRPORT_ID", "DEST", "DEST_CITY_NAME", "DEST_STATE_ABR", "DEST_COUNTRY"],
}
ONTIME = {
    "ORIGIN": ["OriginAirportID", "Origin", "OriginCityName", "OriginState"],
    "DEST": ["DestAirportID", "Dest", "DestCityName", "DestState"],
}


def read_csv(path, columns=None, encoding="utf-8-sig", **kwargs):
    if columns is not None:
        header = pd.read_csv(path, nrows=0, encoding=encoding)
        missing = set(columns) - set(header)
        if missing:
            raise EtlValidationError(f"{path}: missing columns {sorted(missing)}")
    return pd.read_csv(path, usecols=columns, dtype="string", keep_default_na=False,
                       encoding=encoding, **kwargs)


def extract(paths, ontime=False, chunksize=50000):
    """Reduce repeated route observations to distinct airport details and reporting months."""
    mapping = ONTIME if ontime else T100
    year, month = ("Year", "Month") if ontime else ("YEAR", "MONTH")
    columns = [year, month, *(column for fields in mapping.values() for column in fields)]
    parts = []
    for path in paths:
        for chunk in read_csv(path, columns, chunksize=chunksize):
            for fields in mapping.values():
                frame = chunk[fields].copy()
                frame.columns = DETAILS[:-1] if ontime else DETAILS
                if ontime:
                    frame["country_code"] = "US"  # BTS On-Time is domestic, including US territories.
                for name in DETAILS:
                    frame[name] = frame[name].str.strip()
                if not frame.airport_id.str.fullmatch(r"[1-9][0-9]*").all():
                    raise EtlValidationError(f"{path}: missing or invalid airport ID")
                if frame.airport_code.eq("").any() or frame.city.eq("").any():
                    raise EtlValidationError(f"{path}: missing airport code or city")
                dates = pd.to_numeric(chunk[year], errors="coerce") * 100 + pd.to_numeric(chunk[month], errors="coerce")
                if (dates.isna().any() or not chunk[month].str.fullmatch(r"0?[1-9]|1[0-2]").all()
                        or not chunk[year].str.fullmatch(r"[0-9]{4}").all()):
                    raise EtlValidationError(f"{path}: invalid reporting year/month")
                frame["period"] = dates.astype("int64")
                parts.append(frame.drop_duplicates())
        log_.info(f"Extracted airport observations from {path.name}")
    if not parts:
        raise EtlInputError("No airport observations supplied")
    return pd.concat(parts, ignore_index=True).drop_duplicates()


def latest_details(observations):
    """Reject contradictory same-month details; retain the latest reported record per ID."""
    details = observations.drop_duplicates()
    conflicts = details.duplicated(["airport_id", "period"], keep=False)
    if conflicts.any():
        sample = details.loc[conflicts].head(10).to_dict("records")
        raise EtlValidationError(f"Conflicting airport details within a reporting month: {sample}")
    changed = details.groupby("airport_id")[DETAILS[1:]].nunique().gt(1).any(axis=1)
    log_.info(f"Airports with changes across reporting months: {int(changed.sum())}")
    return details.sort_values("period").drop_duplicates("airport_id", keep="last")[DETAILS].copy()


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"\bst[.]?\b", "saint", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def similar_name(left, right):
    ignored = {"airport", "international", "intl", "regional", "municipal", "field", "the"}
    a = [word for word in normalized(left).split() if word not in ignored]
    b = [word for word in normalized(right).split() if word not in ignored]
    if not a or not b:
        return False
    return (SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= 0.75
            or len(set(a) & set(b)) / max(len(set(a)), len(set(b))) >= 0.75)


def name_evidence(left, right):
    ignored = {"airport", "international", "regional", "municipal", "field", "county",
               "seaplane", "base", "national", "executive", "general", "saint"}
    a, b = ({word for word in normalized(value).split() if len(word) >= 4} - ignored
            for value in [left, right])
    return similar_name(left, right) or bool(a & b)


def identity_name(value):
    ignored = {"airport", "international", "intl", "regional", "municipal", "field", "the"}
    return set(normalized(value.replace("'", "").replace("’", "")).split()) - ignored


def coordinate(value):
    match = re.fullmatch(r"(\d+)-(\d+)-([\d.]+)([NSEW])", value.strip())
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    result = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    return -result if direction in "SW" else result


def nearby(taf, airport):
    lat, lon = coordinate(taf.LATITUDE), coordinate(taf.LONGITUDE)
    if lat is None or lon is None:
        return False
    try:
        other_lat, other_lon = float(airport.latitude_deg), float(airport.longitude_deg)
    except (ValueError, TypeError):
        return False
    if not all(math.isfinite(value) for value in [lat, lon, other_lat, other_lon]):
        return False
    lat, lon, other_lat, other_lon = map(math.radians, [lat, lon, other_lat, other_lon])
    distance = math.sin((lat - other_lat) / 2) ** 2 + math.cos(lat) * math.cos(other_lat) * math.sin((lon - other_lon) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, distance))) <= 5


def state_matches(left, right, locid=""):
    # Source-specific metro/physical-location conventions, not general state equivalence.
    conventions = {"IAD": {"VA", "DC"}, "DCA": {"VA", "DC"},
                   "CBE": {"MD", "WV"}, "CPS": {"MO", "IL"}}
    return left == right or {left, right}.issubset(conventions.get(locid, set()))


def reference_codes(airport):
    codes = {airport.iata_code, airport.local_code} - {""}
    # A US ICAO identifier also preserves identity across IATA/local-code renames.
    ident = getattr(airport, "ident", "")
    if airport.iso_country == "US" and re.fullmatch(r"K[A-Z0-9]{3}", ident):
        codes.add(ident[1:])
    return codes


def enrich(airports, names, ourairports, taf):
    names = read_csv(names, ["Code", "Description"], encoding="cp1252")
    names = names.apply(lambda column: column.str.strip()).drop_duplicates()
    if names.Code.duplicated().any():
        raise EtlValidationError("Conflicting BTS airport-ID lookup descriptions")
    names["name"] = names.Description.str.split(":", n=1).str[-1].str.strip()
    airports = airports.merge(names[["Code", "name"]], left_on="airport_id", right_on="Code", how="left", validate="one_to_one")
    if airports.name.fillna("").eq("").any():
        raise EtlValidationError(f"Official BTS names missing for IDs: {airports.loc[airports.name.fillna('').eq(''), 'airport_id'].tolist()}")
    oa_columns = ["id", "iata_code", "local_code", "name", "iso_country", "iso_region", "latitude_deg", "longitude_deg"]
    oa_header = pd.read_csv(ourairports, nrows=0).columns
    oa_columns.extend(name for name in ["ident", "type"] if name in oa_header)
    oa = read_csv(ourairports, oa_columns).apply(lambda column: column.str.strip())
    taf_columns = ["LOCID", "APORT_NAME", "CITY", "STATE", "LATITUDE", "LONGITUDE"]
    taf = read_csv(taf, taf_columns).apply(lambda column: column.str.strip())
    if taf.LOCID.duplicated().any():
        raise EtlValidationError("Duplicate FAA TAF LOCID metadata")
    taf_index = {row.LOCID: row for row in taf.itertuples(index=False)}
    state_index = {}
    for metadata in taf_index.values():
        state_index.setdefault(metadata.STATE, []).append(metadata)
    code_index = {}
    for row in oa.itertuples(index=False):
        for code in reference_codes(row):
            code_index.setdefault(code, []).append(row)
    matches = []
    audit = []
    for row in airports.itertuples(index=False):
        verified = set()
        methods = set()
        possible = set()
        rejected = set()
        for candidate in code_index.get(row.airport_code, []):
            country = candidate.iso_country
            # BTS treats US territories as US in domestic traffic; OurAirports uses territory ISO codes.
            country_ok = country == row.country_code or (row.country_code == "US"
                         and country in {"PR", "VI", "GU", "AS", "MP"}
                         and row.state_code in {country, "TT"})
            locids = reference_codes(candidate) & taf_index.keys()
            possible.update(locids)
            if not country_ok:
                rejected.add("country_mismatch")
                continue
            if (re.search(r"\b(heliport|helipad)\b", row.name, re.IGNORECASE)
                    and getattr(candidate, "type", "") not in {"", "heliport"}):
                rejected.add("heliport_identity_is_not_the_reference_airport")
                continue
            if row.state_code and not (state_matches(candidate.iso_region.removeprefix("US-"), row.state_code, row.airport_code)
                                       or country == row.state_code or (row.state_code == "TT" and country in {"GU", "AS", "MP"})):
                rejected.add("state_mismatch")
                continue
            for locid in locids:
                metadata = taf_index[locid]
                if not (state_matches(metadata.STATE, row.state_code, locid)
                        or (row.state_code == "TT" and metadata.STATE == country and country in {"GU", "AS", "MP"})):
                    rejected.add("faa_state_mismatch")
                elif not nearby(metadata, candidate):
                    rejected.add("coordinates_missing_or_over_5km")
                elif (similar_name(row.name, candidate.name) or similar_name(row.name, metadata.APORT_NAME)
                      or ((row.airport_code == candidate.iata_code
                           or getattr(candidate, "ident", "") == f"K{row.airport_code}")
                          and (name_evidence(row.name, candidate.name)
                               or name_evidence(row.name, metadata.APORT_NAME)
                               or name_evidence(row.city.split(",")[0], metadata.CITY)))):
                    # Exact identifiers, compatible geography and FAA/OA coordinates
                    # establish identity even when official names have changed.
                    verified.add(metadata.LOCID)
                    methods.add("identifier_name_or_city_and_coordinates")
                else:
                    rejected.add("identifier_without_name_or_city_corroboration")
        # Historical BTS codes may have been reassigned. Recover an identifier
        # change only with corroborating FAA name AND city, plus an independent
        # reference identifier and coordinates. Never fuzzy-match on name alone.
        if not verified and row.country_code == "US":
            for metadata in state_index.get(row.state_code, []):
                if not (identity_name(row.name) and identity_name(row.name) == identity_name(metadata.APORT_NAME)
                        and similar_name(row.city.split(",")[0], metadata.CITY)):
                    continue
                for candidate in code_index.get(metadata.LOCID, []):
                    country_ok = candidate.iso_country == "US" or candidate.iso_country == row.state_code
                    if (country_ok and state_matches(candidate.iso_region.removeprefix("US-"), row.state_code, metadata.LOCID)
                            and nearby(metadata, candidate)
                            and (similar_name(metadata.APORT_NAME, candidate.name)
                                 or metadata.LOCID == candidate.local_code)):
                        verified.add(metadata.LOCID)
                        possible.add(metadata.LOCID)
                        methods.add("historical_identifier_change_exact_name_city_and_coordinates")
        # Prefer the directly verified FAA local identifier over an IATA alias
        # pointing at a different facility (e.g. Akutan seaplane base vs land airport).
        if row.airport_code in verified:
            verified = {row.airport_code}
        matches.append(next(iter(verified)) if len(verified) == 1 else "")
        if row.airport_code in taf_index:
            possible.add(row.airport_code)
        status = "mapped" if len(verified) == 1 else "unmapped"
        reason = "identifiers_state_country_and_coordinates_verified" if len(verified) == 1 else (
            "multiple_verified_faa_candidates" if verified else ";".join(sorted(rejected)) or
            ("no_reference_identifier_match" if possible else "no_faa_identifier_candidate"))
        # International airports are outside the US FAA TAF coverage universe.
        if not verified and row.country_code != "US":
            status, reason = "intentionally_excluded", "outside_us_faa_scope"
        elif not possible:
            status, reason = "intentionally_excluded", "no_faa_identifier_candidate_in_reference_snapshots"
        elif not verified and rejected and not rejected.intersection({"coordinates_missing_or_over_5km"}):
            status, reason = "intentionally_excluded", "no_valid_faa_match:" + ";".join(sorted(rejected))
        audit.append({"airport_id": row.airport_id, "airport_code": row.airport_code,
                      "name": row.name, "country_code": row.country_code, "state_code": row.state_code,
                      "faa_locid": matches[-1], "status": status, "reason": reason,
                      "mapping_method": "|".join(sorted(methods)),
                      "candidate_faa_locids": "|".join(sorted(possible)),
                      "verified_faa_locids": "|".join(sorted(verified))})
    airports["faa_locid"] = matches
    # Verified historical BTS aliases may share one physical FAA airport. Keep
    # every BTS identity, explicitly recording the canonical ID for ranking.
    ambiguous = airports.faa_locid.ne("") & airports.faa_locid.duplicated(keep=False)
    audit = pd.DataFrame(audit)
    audit["canonical_airport_id"] = audit.airport_id
    for locid, group in airports.loc[ambiguous].groupby("faa_locid"):
        indexes = group.index
        names_agree = all(similar_name(left, right) for left in group.name for right in group.name)
        if names_agree:
            audit.loc[indexes, "canonical_airport_id"] = str(min(group.airport_id.astype(int)))
            audit.loc[indexes, "reason"] = "verified_bts_aliases_share_one_faa_series"
        else:
            airports.loc[indexes, "faa_locid"] = ""
            audit.loc[indexes, "faa_locid"] = ""
            audit.loc[indexes, "status"] = "unmapped"
            audit.loc[indexes, "reason"] = "faa_locid_shared_by_conflicting_bts_identities"
    airports["airport_id"] = airports.airport_id.astype("int64")
    log_.info(f"FAA mapping coverage: {audit.status.value_counts().to_dict()}")
    result = airports[COLUMNS].sort_values("airport_id").reset_index(drop=True)
    audit["airport_id"] = audit.airport_id.astype("int64")
    result.attrs["mapping_audit"] = audit.sort_values("airport_id").to_dict("records")
    return result


def validate_coverage(airports, silver_files, chunksize=50000):
    known = set(airports.airport_id.astype(str))
    for path in silver_files:
        missing = set()
        for chunk in read_csv(path, ["origin_id", "destination_id"], chunksize=chunksize):
            for name in chunk:
                values = set(chunk[name].str.strip()) - {""}
                missing.update(values - known)
        if missing:
            raise EtlValidationError(f"{path}: airport IDs absent from lookup: {sorted(missing)}")
        log_.info(f"Airport foreign-key coverage passed: {path.name}")


def mapping_audit_path(airports_path):
    airports_path = Path(airports_path)
    return airports_path.parent.parent / "metadata" / (airports_path.stem + "_mapping_audit.csv")


def run(raw_dir=RAW, silver_dir=SILVER, output=None, overwrite=False, chunksize=50000):
    raw_dir, silver_dir = Path(raw_dir), Path(silver_dir)
    output = Path(output) if output is not None else silver_dir / "airports.csv"
    t100 = sorted((raw_dir / "T-100-Segment(All Carriers)").glob("*.csv"))
    ontime = sorted((raw_dir / "BTS-Carrier-On-Time-Performance").glob("*.csv"))
    names = raw_dir / "BTS-Airport-ID/L_AIRPORT_ID.csv"
    oa = raw_dir / "OurAirports/airports.csv"
    taf = raw_dir / "FAA-TAF/Airports.csv"
    silver_files = [silver_dir / "flight_activity.csv", *sorted((silver_dir / "flight_performance").glob("*.csv"))]

    def build():
        if not t100 or not ontime or chunksize <= 0:
            raise EtlInputError("Supply T-100 and On-Time sources and a positive chunksize")
        if len(silver_files) == 1:
            raise EtlInputError("No silver flight_performance CSVs found for foreign-key validation")
        activity = extract(t100, chunksize=chunksize)
        performance = extract(ontime, ontime=True, chunksize=chunksize)
        # T-100 defines existing airports; On-Time supplements airports absent from T-100.
        extra = performance.loc[~performance.airport_id.isin(activity.airport_id)]
        log_.info(f"Airports added from On-Time only: {extra.airport_id.nunique()}")
        return enrich(latest_details(pd.concat([activity, extra], ignore_index=True)), names, oa, taf)

    def validate(frame):
        if frame.empty or frame.airport_id.duplicated().any():
            raise EtlValidationError("Airport lookup must be nonempty with unique airport_id")
        validate_coverage(frame, silver_files, chunksize)
        _write_csv(pd.DataFrame(frame.attrs["mapping_audit"]), mapping_audit_path(output), overwrite)

    return initialize_generated(inputs=[*t100, *ontime, names, oa, taf, *silver_files], output=output,
                                build=build, validate=validate, overwrite=overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a BTS airport lookup with verified FAA TAF identifiers")
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--silver-dir", type=Path, default=SILVER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--chunksize", type=int, default=50000)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(0 if run(**vars(parser.parse_args())) else 1)
