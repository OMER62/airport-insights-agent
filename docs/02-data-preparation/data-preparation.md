# Data preparation

Preparation turns downloaded aviation snapshots into reusable datasets with
explicit identities, units, missingness and business keys. Its output is the Silver
layer used to build Gold. It runs before chat so questions share prepared evidence
without repeating downloads and cleaning.

## Chosen datasets

| Source | Why selected | Prepared output |
|---|---|---|
| [BTS T-100 Segment, All Carriers](https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FMG) | Monthly traffic, seats, departures, distance and freight, including international and cargo activity | `flight_activity.csv` |
| [BTS Reporting Carrier On-Time Performance](https://transtats.bts.gov/TableInfo.asp?gnoyr_VQ=FGJ&QO_fu146_anzr=b0-gvzr&V0s1_b0yB=D) | Individual scheduled-flight reliability and reported delay causes | Twelve 2025 monthly performance partitions |
| [BTS airport-ID names](https://www.transtats.bts.gov/Download_Lookup.asp?Y11x72=Y_NV42146_VQ), [OurAirports](https://ourairports.com/data/) and [FAA airport metadata](https://www.faa.gov/data_research/aviation/taf) | Official names and independent cross-source identity evidence | `airports.csv` and mapping audit |
| [FAA TAF enplanements and operations](https://www.faa.gov/data_research/aviation/taf) | Historical and forecast annual airport activity | `airport_outlook.csv`, configured edition 2025 |

Snapshots stay in `data/raw/`, cleaned datasets in `data/silver/`, and mapping
metadata in `data/metadata/`.

We chose these datasets to answer four different questions: how much traffic an
airport handles, how reliably flights operate, which physical airport each record
refers to, and how annual activity is expected to develop. The prepared outputs are
CSV tables; the analysis database is built from them in the next stage.

Traffic and flight outcomes are cleaned independently. Airport matching comes
next, followed by outlook preparation.

The airport task reads raw airport observations and checks coverage against cleaned
flight outputs. Outlook depends on the lookup and its audit. The audit is part of
the identity contract rather than a disposable processing log.

## 1. Monthly flight activity

One source record describes aggregated monthly activity for a directed airport
pair, reporting airline/entity, aircraft type/configuration, service class and
source classification. It is not an individual flight. Retaining those dimensions
preserves the detail needed for deliberate downstream aggregation.

We chose T-100 because it combines traffic volume and offered capacity with route,
airline and aircraft detail. It supports questions such as which airports handle
more passengers, which routes carry freight, and how passenger volume compares
with available seats.

### Columns in `flight_activity.csv`

| Column | What it represents |
|---|---|
| `reporting_month` | Month of activity, stored as `YYYY-MM`; combines the source year and month. |
| `origin_id` | BTS airport ID of the segment's departure airport. |
| `destination_id` | BTS airport ID of the segment's arrival airport. Direction matters: A to B and B to A are separate records. |
| `airline_id` | BTS/DOT identifier of the reporting airline. |
| `carrier_entity` | Source carrier-entity code, retaining reporting detail within an airline. |
| `aircraft_type` | Source code identifying the aircraft type used. |
| `aircraft_config` | Source code identifying the aircraft configuration. |
| `service_class` | Service category: `F` scheduled passenger, `G` scheduled cargo, `L` nonscheduled passenger or `P` nonscheduled cargo. |
| `source` | T-100 source-classification code, retained to distinguish source records. |
| `departures` | Departures actually performed for this monthly combination of dimensions. |
| `passengers` | Passengers transported on the segment during the month; not a count of unique travelers. |
| `seats` | Total available seats for the monthly record. This is already aggregated across departures. |
| `distance_miles` | Airport-to-airport segment distance in miles; not total miles flown across all departures. |
| `freight_lbs` | Freight transported during the month, in pounds. |
| `flag_missing_airport_id` | True when either endpoint lacks a BTS airport ID. |
| `flag_passengers_exceed_seats` | True when the passenger count exceeds available seats. |
| `flag_invalid_distance` | True when distance is missing, zero or negative. |
| `flag_same_airport` | True when origin and destination have the same source airport ID. |
| `flag_negative_measurement` | True when any of the five activity measurements is negative. |

The business key combines `reporting_month`, both airport IDs, `airline_id`,
`carrier_entity`, `aircraft_type`, `aircraft_config`, `service_class` and `source`.
A route can therefore have several rows in the same month. Totals must aggregate
across the relevant airline, aircraft and reporting categories.

### Preparation rules

The transformation selects required columns, trims strings, parses numbers,
combines year/month into `reporting_month` and adds quality flags. Categorical codes
remain strings so leading zeros survive. Counts must be integral; malformed
numbers and infinities fail. Missing airport IDs remain flagged, while the other
required key fields must be present. Duplicate business keys across combined
inputs stop publication.

The key choice is to preserve questionable values and restrict their use by metric.
Missing distance need not invalidate passengers or freight; zero seats can describe
cargo activity. Deleting every imperfect record would change unrelated populations.

| Condition | Silver treatment | Downstream consequence |
|---|---|---|
| Zero departures | Preserve | Does not establish an active route |
| Zero seats | Preserve | Cannot supply a passenger/seat ratio denominator |
| Passengers exceed seats | Preserve and flag | Exclude both measures from paired ratio totals |
| Missing, zero or negative distance | Preserve and flag | Exclude from distance-based shares |
| Same origin/destination | Preserve and flag | Gold omits routes with equal canonical endpoints |
| Negative measurement | Preserve and flag | Admit usable nonnegative measurements separately |
| Missing airport ID | Preserve and flag | Cannot join to a canonical route endpoint |

For an illustrative monthly record with 8,000 passengers, 10,000 seats and 100
departures, seats are already a monthly total. Multiplying by departures again
would inflate offered capacity. Distance is segment distance in miles; freight is
weight in pounds.

Silver preserves scheduled passenger (`F`), scheduled cargo (`G`), nonscheduled
passenger (`L`) and nonscheduled cargo (`P`) classes. Current historical activity
tools use scheduled passenger service (`F`), despite broader source coverage.

## 2. Scheduled-flight performance

On-Time adds outcomes that monthly T-100 activity cannot describe. The current task
processes twelve configured 2025 inputs; earlier plans to collect 2024 and 2025 do
not mean both years are implemented.

One output row represents a scheduled flight, including cancellations and
diversions. The business key is flight date, airline ID, flight number, origin ID,
destination ID and scheduled departure time. All six fields are required.

We chose this source because traffic totals cannot tell us whether a flight was
late, cancelled or diverted. Its flight-level records support cancellation rates,
delay comparisons and analysis by scheduled departure time. Its reporting-carrier
scope differs from T-100, so the two tables are not interchangeable populations.

### Columns in the monthly `flight_performance` files

All twelve partitions share the same schema.

| Column | What it represents |
|---|---|
| `flight_date` | Source date of the scheduled flight, stored as `YYYY-MM-DD`. |
| `reporting_month` | Month derived from `flight_date`, used for monthly grouping and partition checks. |
| `airline_id` | BTS/DOT identifier of the reporting airline. |
| `flight_number` | Reporting airline's flight number; it is not unique by itself. |
| `origin_id` | BTS airport ID of the scheduled departure airport. |
| `destination_id` | BTS airport ID of the scheduled destination airport. |
| `scheduled_departure_time` | Scheduled departure in local `HHMM` clock time. |
| `scheduled_arrival_time` | Scheduled arrival in local `HHMM` clock time. |
| `departure_delay_minutes` | Difference from scheduled departure, in minutes; negative means early. |
| `arrival_delay_minutes` | Difference from scheduled arrival, in minutes; negative means early. |
| `cancelled` | Boolean indicating whether the flight was cancelled. |
| `cancellation_code` | Reported reason: `A` carrier, `B` weather, `C` national aviation system or `D` security; blank for noncancelled flights. |
| `diverted` | Boolean indicating whether the flight was diverted. |
| `carrier_delay_minutes` | Reported delay minutes attributed to the carrier. |
| `weather_delay_minutes` | Reported delay minutes attributed to weather. |
| `nas_delay_minutes` | Reported delay minutes attributed to the national aviation system. |
| `security_delay_minutes` | Reported delay minutes attributed to security. |
| `late_aircraft_delay_minutes` | Reported delay minutes attributed to a late-arriving aircraft. |

The delay-cause fields describe reported attribution. A missing value does not
establish that a cause contributed zero minutes.

### Preparation rules

Chunking limits memory use. A temporary SQLite key index catches duplicates across
chunks and files without holding every flight key in memory. All monthly outputs
are prepared before publication.

Dates must belong to the expected partition. Scheduled times remain four-character
local clock strings, including allowed `2400`; they do not establish UTC timestamps
or arrival dates. Early arrivals/departures retain signed negative delays. Missing
delays remain missing. Cancelled flights require a valid cancellation code;
noncancelled flights require a blank code. Five reported delay-cause categories
are retained without manufacturing missing minutes.

A cancelled flight with no arrival delay remains a scheduled flight and a
cancellation. Filling its delay with zero would falsely label an unobserved
completed-arrival outcome as on time.

## 3. Airport identity reconciliation

BTS numerical IDs identify source observations; FAA uses local identifiers. Codes
and names change, and similar codes may describe different facilities. Reconciliation
therefore precedes attaching forecasts.

The process extracts T-100 origin/destination observations and supplements airports
absent there with On-Time observations. It rejects contradictory same-month details
and selects the latest details per BTS ID. BTS lookup descriptions provide names;
OurAirports and FAA metadata corroborate identifiers, geography, names/city and
coordinates.

We chose a separate airport lookup so every traffic, performance and outlook row
can refer to a consistent airport identity. BTS supplies the numerical IDs used
by flight records; FAA identifiers connect those airports to annual outlook data.
OurAirports supplies independent evidence for checking the match.

### Columns in `airports.csv`

One row represents one BTS airport ID. This source identity is retained even when
several verified BTS IDs refer to the same physical airport.

| Column | What it represents |
|---|---|
| `airport_id` | BTS airport ID; unique key of this lookup and the target of flight-table endpoint IDs. |
| `airport_code` | Airport code from the selected BTS observation, useful for display and reference checks. |
| `faa_locid` | Verified FAA location identifier used to attach outlook records; blank when no accepted mapping exists. |
| `name` | Airport name supplied by the BTS airport-ID lookup. |
| `city` | City associated with the selected airport observation. |
| `state_code` | State or territory code associated with the airport observation. |
| `country_code` | Country code associated with the airport observation. |

### Columns in the mapping audit

The audit records the identity decision for each airport. It shares `airport_id`,
`airport_code` and `faa_locid` with the lookup and adds the following fields.

| Column | What it represents |
|---|---|
| `status` | Decision category: `mapped`, `unmapped` or `intentionally_excluded`. |
| `reason` | Explanation of the accepted match, unresolved identity or deliberate exclusion. |
| `mapping_method` | Matching methods recorded during reconciliation. |
| `candidate_faa_locids` | FAA identifiers considered as possible matches. |
| `verified_faa_locids` | FAA identifiers that passed the verification checks. |
| `canonical_airport_id` | BTS ID selected to represent the physical airport, allowing verified aliases to be counted once in Gold. |

For example, flight records join `origin_id` and `destination_id` to
`airports.airport_id`. Outlook records use `airport_id` after matching the FAA
identifier. `airport_code` is a readable label; the joins rely on verified IDs.

### Preparation rules

Coordinate corroboration uses a five-kilometer rule. Historical identifier changes
require additional exact normalized-name and city corroboration; fuzzy matching
alone is insufficient. Explicit conventions handle certain metro/physical-state
differences and US territories.

Verified BTS aliases sharing an FAA facility receive one canonical ID when their
names agree: the smallest BTS ID in the group. Conflicting shared mappings remain
unresolved. Silver retains source IDs while Gold ranks physical airports once.

The lookup contains BTS ID, airport code, FAA identifier, name, city, state and
country. Its audit adds status, reason, candidates, verified identifiers, mapping
method and canonical ID. Every nonblank airport ID in cleaned flight outputs must
be covered by the lookup.

## 4. Annual airport outlook

The outlook combines FAA passenger enplanements and operations into one annual
record per BTS airport ID, fiscal year, edition and source scenario. Edition 2025
is configured download metadata because raw activity CSVs do not contain it.

We chose FAA TAF because it places historical airport activity and annual forecasts
in the same source framework. The enplanements table provides passenger boardings;
the operations table adds aircraft activity, which can develop differently from
passenger demand.

### Columns in `airport_outlook.csv`

| Column | What it represents |
|---|---|
| `airport_id` | BTS airport ID obtained from the verified FAA-to-BTS mapping. |
| `fiscal_year` | FAA fiscal year of the activity or forecast; it should not be treated as a calendar-year total. |
| `taf_edition` | Forecast release edition, configured as `2025`; distinct from the year being described. |
| `scenario` | Scenario label retained from the FAA source, distinguishing source series for the same airport and year. |
| `domestic_passengers` | Domestic air-carrier passenger enplanements. |
| `air_taxi_passengers` | Air-taxi passenger enplanements. |
| `commuter_passengers` | Commuter passenger enplanements. |
| `international_us_passengers` | International enplanements on US carriers. |
| `international_foreign_passengers` | International enplanements on foreign carriers. |
| `air_carrier_operations` | Air-carrier aircraft operations, counting takeoffs and landings. |
| `air_taxi_operations` | Air-taxi aircraft operations, counting takeoffs and landings. |

The unique key is `airport_id`, `fiscal_year`, `taf_edition` and `scenario`.
Although the five boarding columns are named `*_passengers`, their unit is
boardings, not unique people. A connecting traveler may board more than once.
For example, a future fiscal-year row in edition 2025 describes that year's
outlook as published in the 2025 release; the edition is not the forecast year.

### Preparation rules

A full outer join preserves passenger-only and operations-only records. Missing
counterparts, blanks and literal `NULL` measurements remain null. Explicit zeros
remain zero. Measures must be nonnegative integers; source and final keys must be
unique.

Five boarding categories are retained: domestic air carrier, air taxi, commuter,
international US carrier and international foreign carrier. Operations retain
air-carrier and air-taxi categories. Boardings count embarkations, including another
boarding by a connecting passenger. Operations include takeoffs and landings;
neither quantity is interchangeable with unique people or departures.

The process checks audit/lookup agreement and relevant flight-airport coverage.
Unresolved relevant mappings block publication. Documented exclusions and verified
FAA airports without activity in the edition are permitted. FAA rows outside
verified BTS mappings are omitted with logged counts. Coverage is checked in memory;
no additional outlook coverage CSV is published.

## Publication and recovery

Tasks own dataset rules. The initializer assembles work; the shared runner owns
execution and publication. Single CSVs are staged and published after their checks
pass. Replacement requires explicit overwrite.

Performance publication uses a lock and directory swap with backup/rollback. An
interrupted swap may require recovery; it is not a transaction across crashes.
Airport lookup and audit are separate publications: the audit is written before
the lookup, so the pair is not atomic. Outlook's stale-audit checks protect the next
stage from inconsistent identity inputs.

Gold's separate build is explained in [data modeling](../03-data-modeling/data-modeling.md).
Test methods and measured results are in
[testing and evaluation](../06-testing-and-evaluation/testing-and-evaluation.md).
