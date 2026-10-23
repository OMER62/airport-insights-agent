# Evaluation question catalog

This catalog preserves 30 analytical scenarios for an airport investment assistant.
It is a target for evaluating capability, not a claim of 30 implemented operations
or computed reference answers. The current tools cover the five core metrics and
lookup; several scenarios require additional deterministic definitions and tools.

## Evaluation conventions

Users may omit reporting years. Select and disclose actual available periods,
compare equivalent coverage and preserve periods and definitions across follow-ups
unless explicitly changed. Empty candidate sets are valid results. Unknown values
must not become zero.

Questions 20?29 form five independent two-turn conversations: (20,21), (22,23),
(24,25), (26,27) and (28,29). Follow-ups retain prior candidates, selected airports,
thresholds and definitions. The other questions are standalone. Question 30 was
added to bring the catalog to 30 cases.

Terms such as busy, mid-sized, regional, similar-sized and strong growth require
explicit definitions. The current long-haul tool uses scheduled outbound passenger
departures at least 2,000 miles; requests for other populations need additional
support. Retained data alone does not guarantee that an operation is exposed.

Aggregate facts independently before combining them. Distinguish calendar T-100
activity from fiscal TAF boardings and publication edition. Passenger/seat ratios,
reported delays and forecasts are indirect evidence; they do not establish unmet
demand, infrastructure causation or financial profitability.

## Question catalog

| # | Question | Main datasets | Analysis |
|---|---|---|---|
| 1 | Which airports in New England are strong candidates for terminal expansion? | All four | Rank using historical traffic growth, operational pressure and forecast growth. Explain that expansion feasibility requires further investigation. |
| 2 | How does congestion at Los Angeles International compare with Santa Ana? | `airports`, `flight_performance`, `flight_activity` | Compare arrival-delay rates, delay severity and cancellations over the same period. Include traffic volumes for context. |
| 3 | What percentage of flights departing Anchorage are long-haul? | `airports`, `flight_activity` | Define the distance threshold and eligible service categories, then divide long-haul departures by eligible departures with valid distances. |
| 4 | Is there evidence of unmet flight demand at San Francisco International, and what might explain it? | All four | Examine traffic growth, passenger-to-seat ratios, forecasts and reported delay causes. Explain that these are indirect indicators and cannot quantify unmet demand. |
| 5 | Which Texas airports are seeing passenger traffic grow faster than seat capacity? | `airports`, `flight_activity` | Compare passenger and seat growth across comparable periods, examine passenger-to-seat ratios and apply a minimum traffic threshold. |
| 6 | At San Francisco International, are reported delays mainly attributed to weather, airlines or the national aviation system? | `airports`, `flight_performance` | Compare attributed delay minutes across all reported categories, including late-arriving aircraft and security. Disclose reporting coverage. |
| 7 | Which Florida airports have the strongest seasonal peaks in passenger traffic? | `airports`, `flight_activity` | Compare monthly passengers with each airport’s annual monthly average and check whether peaks repeat across available years. |
| 8 | How much does Anchorage’s long-haul departure share change when cargo-only services are included? | `airports`, `flight_activity` | Compare passenger-service, cargo-only and combined shares using the same distance threshold, reporting period and validity rules. |
| 9 | Which busy California airports are expected to see strong passenger growth and already experience frequent arrival delays? | All four | Define busy, combine forecast passenger growth with arrival-delay rates and explain the ranking criteria. |
| 10 | Which airports have declining domestic passenger traffic but freight growth above 10%? | `airports`, `flight_activity` | Compare equivalent periods. Define domestic routes and whether freight covers those same routes; require a meaningful baseline volume. |
| 11 | Which mid-sized airports are expected to have the fastest growth in international passenger boardings? | `airports`, `airport_outlook` | Define mid-sized, combine international boardings on US and foreign carriers, and compare forecast growth. Show percentage and absolute increases. |
| 12 | Which major airports consistently have the highest share of reported delay minutes attributed to late-arriving aircraft? | `airports`, `flight_performance` | Calculate late-arriving-aircraft minutes as a share of total attributed delay minutes and check consistency across months. Avoid interpreting this as proof of gate congestion. |
| 13 | At which airports do winter weather delays tend to coincide with delays attributed to the national aviation system? | `airports`, `flight_performance` | Examine daily weather-attributed and system-attributed delay minutes during winter, adjusting for traffic volume. Report association without claiming causation. |
| 14 | Which growing airports have passenger-to-seat ratios above 90% and worsening departure delays? | `airports`, `flight_activity`, `flight_performance` | Define growth, calculate ratios from eligible passenger-service records and assess departure-delay trends within available performance coverage. |
| 15 | Which airports consistently depend on a single airline for more than 75% of their scheduled passenger seats? | `airports`, `flight_activity` | Calculate each airline’s monthly seat share using `airline_id` and identify airports where one airline consistently exceeds the threshold. |
| 16 | At which regional airports are air-taxi operations expected to grow faster than air-carrier operations? | `airports`, `airport_outlook` | Define regional, compare forecast growth for the two operation categories and show absolute changes alongside percentages. |
| 17 | Which airports are reducing short-haul scheduled flights while offering more passenger seats, and how do their airline-related delays compare? | `airports`, `flight_activity`, `flight_performance` | Define short-haul as under 300 miles, compare departures and seats across equivalent periods, then compare carrier-attributed delay minutes per scheduled flight. |
| 18 | Which busy destination airports have the highest combined cancellation and diversion rates during peak summer travel months? | `airports`, `flight_performance` | Group by scheduled destination and divide flights cancelled or diverted by all scheduled flights. Count each affected flight once and apply a minimum volume threshold. |
| 19 | Which airports have the strongest projected passenger growth, and how does it compare with their recent historical growth? | `airports`, `airport_outlook` | Compare historical and forecast annualized growth using consistent passenger definitions from the same forecast edition. Show baseline volumes and absolute changes. |
| 20 | Which Midwest airports are growing passenger traffic while expanding the number of destinations they serve? | `airports`, `flight_activity` | Define Midwest. Compare departing passenger growth and distinct scheduled passenger destinations across comparable periods. Apply minimum activity thresholds so occasional services do not inflate destination counts. |
| 21 | **Follow-up to 20:** Which of those would remain growth candidates if we excluded their busiest route? | `airports`, `flight_activity` | Retain the shortlist. Identify each airport’s busiest outbound passenger route in the latest period, exclude that same route from both comparison periods, and recalculate growth. |
| 22 | Which busy airports have the biggest gap between morning and evening departure reliability? | `airports`, `flight_performance` | Define morning and evening using scheduled local departure times. Compare departure-delay and cancellation rates with minimum flight counts for each window. |
| 23 | **Follow-up to 22:** Keep only those where the problem is concentrated in the evening rather than spread throughout the day. | `airports`, `flight_performance` | Retain the candidates and compare morning, afternoon and evening rates. Apply an explicit rule for evening concentration; report flight volumes alongside rates. |
| 24 | Which mid-sized airports are expected to add the most passenger boardings over the next five forecast years? | `airports`, `airport_outlook` | Define size using baseline boardings. Rank absolute boarding increases over a disclosed five-year forecast window using consistent categories and one TAF edition. |
| 25 | **Follow-up to 24:** Narrow that list to airports where both domestic and international boardings are expected to grow. | `airports`, `airport_outlook` | Preserve the shortlist and forecast window. Require positive growth in both categories; show each category’s absolute increase and contribution to total growth. |
| 26 | How does Tampa’s passenger traffic growth compare with other Florida airports of a similar size? | `airports`, `flight_activity` | Select peers using an explicit baseline passenger-volume band. Compare departing scheduled passenger growth, absolute increases and seat growth across equivalent periods. |
| 27 | **Follow-up to 26:** Is its growth spread across airlines and destinations, or mostly coming from one airline or route? | `airports`, `flight_activity` | Retain Tampa and the comparison period. Decompose its passenger change separately by airline and route; report the largest contributors without double-counting the two breakdowns. |
| 28 | How does Denver’s departure reliability compare with other airports handling similar flight volumes? | `airports`, `flight_performance` | Define peers using scheduled departure counts. Compare delay rates, positive delay severity and cancellation rates over the same coverage period. |
| 29 | **Follow-up to 28:** Does Denver still look worse or better when we account for differences in airline mix and departure times? | `airports`, `flight_performance` | Recalculate comparisons using common airline and scheduled-time groups with fixed weights. Show adjusted and unadjusted results, disclosing groups excluded for insufficient overlap. |
| 30 | Which growing airports have the most passenger traffic concentrated into just a few months of the year? | `airports`, `flight_activity` | Additional proposed standalone case: filter airports with positive departing scheduled passenger growth and meaningful baseline volume. Rank the share of annual passengers carried in each airport’s three busiest months, show those months, and compare equivalent complete years. Distinguish concentrated seasonal activity from year-round pressure. |

See [testing and evaluation](../06-testing-and-evaluation/testing-and-evaluation.md)
for executed checks, historical live-answer findings and remaining coverage.
