# Third-party sources and permissions

The existing MIT license covers project code owned by its author. It does not
relicense upstream datasets or third-party packages.

| Material | Source and status | Before publication |
|---|---|---|
| Airport reference data | [OurAirports](https://ourairports.com/data/) explicitly releases its data to the public domain, without an accuracy warranty. | Retain source attribution and identify the actual snapshot date. |
| Traffic, offered capacity, airport IDs, flight reliability | [BTS TranStats](https://www.transtats.bts.gov/) T-100 and Reporting Carrier On-Time Performance. | Verify terms for the exact downloaded extracts and record acquisition dates, filters, and checksums. Exact source files are absent from this repository. |
| Historical and forecast airport activity | [FAA Terminal Area Forecast](https://www.faa.gov/data_research/aviation/taf). | Verify the exact exports, edition, and redistribution conditions. The builder also cites an FAA web application JavaScript file as evidence for scenario codes; do not assume the website's code is licensed as project code. |
| Prepared SQLite snapshot | `data/gold/airport_gold.db`, derived from the above sources. | Confirm provenance and redistribution rights for every input before committing this binary. The MIT code license alone does not establish these rights. |
| Python dependencies | Packages named in `requirements*.txt` and their transitive dependencies. | Preserve upstream notices when redistributing their code or bundled assets. A complete resolved dependency/license inventory remains outstanding. |

No screenshots, notebooks, PDFs, or standalone image assets were found in the
publication candidate. Generated Chainlit assets and translations are local and
ignored. The audit did not establish authorship of every source-code passage;
the author must confirm there is no undisclosed copied or employer-owned code.
