# Deterministic analysis

The analysis service converts a selected airport population and reporting periods
into reproducible measurements. It resolves defaults, aggregates compatible Gold
facts, applies eligibility rules and returns structured evidence. Gemini can choose
an analysis but cannot redefine its arithmetic.

## Why these metrics were selected

The selected metrics separate five questions: is passenger activity growing, are
arrivals disrupted, what service mix does the airport support, are passengers
growing faster than offered seats, and which airports merit further expansion
investigation? These are related questions, but each needs a different measurement.

| Selected metric / tool | Question answered | Main output |
|---|---|---|
| Historical passenger growth / `traffic_growth` | How much has observed passenger activity changed? | Passenger change, growth %, CAGR % |
| Arrival operational pressure / `airport_operational_pressure` | How often are scheduled destination arrivals disrupted? | Arrival disruption % |
| Outbound long-haul share / `outbound_long_haul_share` | How much departing service operates over long distances? | Departure-weighted long-haul % |
| Passenger-versus-seat growth / `demand_capacity_pressure` | Is passenger activity increasing faster than offered seating? | Growth gap and passenger/seat ratios |
| Expansion screening / `terminal_expansion_opportunity` | Which eligible airports combine growth, forecast additions and operational pressure? | Score contributions, screening score and national rank |

The choice favors quantities available from the prepared datasets, explicit
populations and reproducible arithmetic. Passenger activity and offered seats come
from BTS T-100 Segment (All Carriers); arrival outcomes come from BTS Reporting
Carrier On-Time Performance; forecast boardings come from FAA Terminal Area
Forecast (TAF). The analysis reads their prepared Gold facts.

The rationale below explains what each definition is useful for. It does not imply
that the chosen thresholds or screening weights have been statistically calibrated
against successful airport investments. Long-haul share and passenger-versus-seat
growth are descriptive analyses; neither is an extra component of the expansion score.

## Shared request inputs and period rules

Choose exactly one of a nonempty canonical airport-ID list, a supported region or a
two-letter state code. State codes are normalized to uppercase. Named airports can
be resolved through lookup. Invalid selections and period combinations fail the
request contract; unknown canonical IDs produce an invalid-input result.

Explicit years are respected. Defaults use available complete prior calendar years,
with the latest suitable endpoint and latest earlier comparable activity baseline.
Expansion requires activity and performance availability. State/regional searches
can proceed when a usable subset has observations; missing selected airports stay
visible rather than blocking or silently shrinking the whole search.

When explicit source attestations are absent, observed twelve-month inventory can
identify candidate periods for descriptive analysis. That fallback does not verify
source completeness and does not qualify the results for ranking. An explicitly
incomplete attestation is not silently replaced by the fallback.

Forecast context separately selects an unambiguous historical-to-forecast window
five fiscal years apart, within one edition and compatible evidence categories.
Returned metadata records actual years, edition and scenarios. The fiscal baseline
need not equal the historical traffic baseline.

## 1. Historical passenger growth

### Why this metric

Absolute change shows the scale of added activity. Percentage growth makes change
relative to the airport's starting size. CAGR annualizes that change so a two-year
comparison is not mistaken for a one-year rate. Reporting all three avoids relying
on a large percentage at a very small airport or a large count at an already large
airport alone. Observed passengers describe realized activity, not latent demand.

### Inputs and full formula

Use outbound scheduled passenger records for both selected calendar endpoints.
Let `P0` be the sum of eligible passengers in baseline calendar year `Y0`, `P1`
the corresponding sum in endpoint year `Y1`, and `n = Y1 - Y0 > 0`. Both sums
must use comparable service populations. Passengers are counts, years are elapsed
calendar years.
Return absolute passenger change, percentage growth and compound annual growth:

```text
absolute_change = P1 - P0                                      [passengers]
growth_pct = 100 * (P1 / P0 - 1)                               [%]
cagr_pct = 100 * ((P1 / P0) ** (1 / n) - 1)                    [% per year]
```

### Outputs and interpretation

The output contains the endpoint totals and all three change measures.
An illustrative change from 100,000 to 121,000 passengers over two years gives
+21,000 passengers, +21% total growth and +10% annualized growth. A zero baseline
leaves percentage growth undefined while preserving absolute change. This is
segment passenger activity, not unique travelers or measured unmet demand.

## 2. Arrival operational pressure

### Why this metric

A disruption rate expresses operational pressure relative to the number of flights,
so airports with different traffic volumes can be compared. Including cancellations
and diversions avoids describing performance only for flights that completed their
planned arrival. Mean positive delay adds severity context; cancellation rate
shows a specific failure outcome separately.

### Inputs and full formula

Use the selected calendar year's destination-arrival performance facts. Let `A`
be reported scheduled arrivals, `C` the classifiable arrivals, `K` cancellations,
`V` diversions, and `T` completed, nondiverted arrivals with observed arrival delay.
For each flight in `T`, `d_i` is arrival delay in minutes; negative means early.
Let `L` count flights in `T` with `d_i >= 15`, and `D` count the union of cancelled,
diverted and qualifying late arrivals.

This metric measures arrival disruption at the scheduled destination. A disrupted
flight is cancelled, diverted or completed at least 15 minutes late. Each flight
counts once. The denominator is the matching classifiable population.

```text
D = count(cancelled OR diverted OR (completed with observed delay >= 15))
C = count(cancelled OR diverted OR completed with observed arrival delay)
arrival_disruption_pct = 100 * D / C                           [%]
arrival_delay_rate_pct = 100 * L / count(T)                     [%]
mean_positive_arrival_delay_minutes = sum(max(d_i, 0), i in T) / count(T)
                                                             [minutes per observed completed arrival]
cancellation_rate_pct = 100 * K / A                            [%]
```

### Outputs and interpretation

Return the disruption rate, supporting flight counts, delay rate, mean positive
delay and cancellation rate. Each zero denominator leaves its affected rate
undefined. Unknown outcomes are disclosed through coverage rather than counted
as successful arrivals.

The mean includes early and on-time completed arrivals in its denominator. For
example, delays of -5, 0 and 30 minutes produce a mean positive delay of 10 minutes,
not 30 minutes per delayed flight. The result also provides traffic context and
reported cause minutes with their own coverage.

Disruption is an operational-pressure proxy. It does not directly measure terminal
congestion. Reported weather, carrier, NAS, security and late-aircraft categories
do not establish that expansion would remove the reported delay.

## 3. Outbound long-haul share

### Why this metric

Long-haul share describes the airport's service mix. Weighting by departures means
a frequently operated route contributes more than an infrequent route; counting
routes or source rows would miss that distinction. This provides context for
airport comparisons without treating long distance itself as evidence of congestion.
The 2,000-mile cutoff is a project definition, not a universal long-haul standard.

### Inputs and full formula

Current tools use scheduled passenger departures, with the airport as origin, and
classify distances of at least 2,000 miles as long haul. The threshold includes
exactly 2,000 miles. It was unresolved in early preparation designs and is now a
fixed tool definition; the exposed tool does not offer a threshold override.

For each eligible outbound activity record `r`, let `w_r` be its departure count
and `m_r` its distance in miles. `E` contains records with valid positive distance;
`O` contains the observed outbound departure population before distance exclusions.

```text
distance_eligible_departures = sum(w_r, r in E)
long_haul_departures = sum(w_r, r in E where m_r >= 2000)
long_haul_share_pct = 100 * long_haul_departures / distance_eligible_departures
                                                             [%]
distance_coverage_pct = 100 * distance_eligible_departures / sum(w_r, r in O)
                                                             [% of departures]
```

### Outputs and interpretation

Return the long-haul and distance-eligible departure counts, observed departures,
share and coverage. A zero eligible denominator leaves the share undefined.

Weight by departures rather than source rows, route counts or passengers. An
illustrative 200 long-haul departures among 1,000 distance-eligible departures gives
20%. If 100 other departures have unknown distance, disclose that the distance
coverage is 1,000/1,100; do not classify those departures as short haul. Cargo-inclusive
comparisons remain outside the exposed tool despite retained cargo source data.

## 4. Passenger-versus-seat growth

### Why this metric

Passenger growth alone cannot show whether airlines are adding seating at a similar
pace. Comparing both growth rates identifies airports where observed passenger
activity is outpacing offered seating. The passenger/seat ratio adds starting and
ending context: the same growth gap can mean different things at different initial
utilization levels. Offered airline seats measure a service supply, not physical
terminal capacity.

### Inputs and full formula

Let `P0` and `P1` be paired eligible passenger totals in the baseline and endpoint
calendar years, and `S0` and `S1` the seat totals from those same records.
Use paired passenger/seat records within each endpoint: valid nonnegative passengers,
positive seats and passengers no greater than seats. Pairing prevents passenger
totals from one population being compared to seats from a different population.

```text
baseline_ratio_pct = 100 * P0 / S0                            [%]
end_ratio_pct = 100 * P1 / S1                                 [%]
passenger_growth_pct = 100 * (P1 / P0 - 1)                     [%]
seat_growth_pct = 100 * (S1 / S0 - 1)                          [%]
passenger_seat_growth_gap_pp = passenger_growth_pct - seat_growth_pct
                                                             [percentage points]
ratio_change_pp = end_ratio_pct - baseline_ratio_pct           [percentage points]
```

### Outputs and interpretation

Return all six measures with the paired passenger and seat totals. These growth
rates describe the whole selected interval; they are not annualized. A zero
denominator makes only the affected calculation and dependent differences undefined.
A positive growth gap alone can occur when both passengers and seats decline, so
the growing-airport shortlist additionally requires positive passenger growth.

For example, passengers growing from 80,000 to 88,000 and seats from 100,000 to
105,000 give +10% passenger growth, +5% seat growth, a +5 percentage-point gap, and
ratios increasing from 80% to approximately 83.81%. These illustrative values
indicate tighter offered seating, not a measured quantity of unserved passengers.
The ratio is not distance-weighted industry passenger load factor.

The tool includes operational and fiscal forecast context so an analyst can
interpret the growth panel without redundant calls. Its positive-growth shortlist
requires ranking eligibility, passenger growth above zero and passenger growth
exceeding seat growth. A partial result can remain useful descriptively without
qualifying for that shortlist.

## 5. Expansion screening

### Why these components

The score uses historical CAGR for observed growth momentum, absolute forecast
boarding additions for the scale of expected future activity, and arrival
disruption for operational pressure. CAGR normalizes historical growth for elapsed
time. Absolute forecast additions retain scale that a percentage forecast alone
could obscure at small airports. National percentiles put these different units
onto a common scale before weighting.

The 40% historical, 40% forecast and 20% operational weights define a growth-led
screen: growth contributes 80% of the score and disruption 20%. This is a transparent
project policy, not an estimated relationship between these signals and investment
returns. Higher disruption increases the score because it flags pressure for
investigation; it does not establish a need for terminal construction.

### Inputs and eligibility

Expansion screening combines growth and operational evidence across eligible US
airports before filtering the requested geography.

Eligibility requires complete mandatory historical/operational measurements,
verified source completeness and forecast interpretation, positive historical
passenger growth, positive forecast boarding additions, at least 10,000 baseline
scheduled passengers and at least 1,000 scheduled arrivals. These are project
screening conventions rather than universal investment standards.

Forecast additions are the difference between annual boardings at the endpoints,
not cumulative passengers over five years. A zero forecast baseline can still
support positive absolute additions even when percentage growth is undefined.
Missing components do not become zero or trigger hidden redistribution of weights.

### Full formula

For each eligible airport `a`, let `P0_a` and `P1_a` be historical passenger totals,
`n` the elapsed calendar years, `B0_a` and `B5_a` the annual forecast boardings at
fiscal endpoints five years apart, and `D_a` and `C_a` the disrupted and classifiable
arrival counts in the selected operational calendar year.

```text
historical_a = 100 * ((P1_a / P0_a) ** (1 / n) - 1)            [% per year]
forecast_a = B5_a - B0_a                                     [additional annual boardings]
operational_a = 100 * D_a / C_a                              [%]
```

Each component percentile uses the same eligible national cohort. With N airports,
L lower values and E equal values, the percentile is:

```text
percentile(x_a) = 100 * (L + (E - 1) / 2) / (N - 1), N > 1
H_a = percentile(historical_a)
F_a = percentile(forecast_a)
O_a = percentile(operational_a)
historical_contribution_a = 0.40 * H_a
forecast_contribution_a = 0.40 * F_a
operational_contribution_a = 0.20 * O_a
score_a = historical_contribution_a + forecast_contribution_a + operational_contribution_a
national_rank_a = 1 + count(eligible airports with score > score_a)
```

### Outputs and interpretation

Return the three raw component values, their national percentiles, weighted
contributions, total score and national rank. Include cohort IDs, weights, period
metadata and reasons for exclusion so the result can be reconstructed. Airports
that fail eligibility remain visible in the selected results without a score.

A singleton receives 50 for each component percentile. Ties receive midpoint percentiles; equal scores share
competition ranks, such as 1, 1, 3. Returned ranks remain national after filtering.
An illustrative airport with component percentiles 80, 60 and 50 receives
32 + 24 + 10 = 66 score points. That score is not a percentile, probability or
financial return.

## Result interpretation and unsupported questions

Results carry selection, resolved periods, source metadata, units, per-airport
values, coverage, exclusions and relevant component panels. Expansion also returns
cohort IDs, weights, eligibility summaries and ranks. Exclusion reasons overlap;
their counts must not be summed as disjoint groups.

| Status | Meaning |
|---|---|
| `ok` | Supported values under the relevant checks; inspect individual panels too |
| `partial` | Some observations or source evidence are incomplete |
| `undefined` | A calculation has an unusable denominator |
| `ineligible` | Airport fails screening rules or reference-population requirements |
| `invalid_input` | Selection refers to an unsupported canonical identity |
| `insufficient_evidence` | Required periods or measurements are unavailable |

Request-schema violations raise validation errors rather than necessarily producing
a result status. A valid low-volume descriptive calculation can also have ranking
eligibility false. Evidence coverage must be interpreted in its stated unit:
records, flights and departures are different populations.

Peer matching, seasonal analysis, causal explanations, terminal capacity and
profitability exceed the implemented operations. Retained data does not authorize
the model to invent these calculations. Evaluation of these boundaries is covered
in [testing and evaluation](../06-testing-and-evaluation/testing-and-evaluation.md).


## Implementation references

- [Metric arithmetic](../../app/analysis/metrics.py): growth, disruption, long-haul share, passenger/seat measures and weighted score.
- [Analysis service](../../app/analysis/service.py): period resolution, Gold aggregation, coverage, eligibility, percentiles and national ranking.
- [Evidence definitions](../../app/analysis/evidence.py): units, populations, source names and result interpretation.
- [Request and result models](../../app/analysis/models.py): accepted inputs and structured outputs.
