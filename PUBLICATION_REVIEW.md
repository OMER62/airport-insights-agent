# Pre-publication review — 2026-10-23

Status: **hold publication pending dependency remediation and rights review.**
Nothing was published, committed, removed from the index, or rewritten in Git history.
Existing working changes were preserved.

## Fixes applied

- Extended `.gitignore` for logs, local SQLite databases and sidecars, credentials
  in key files, virtual environments, coverage, caches, packaging output, and
  evaluation transcripts. Kept the existing explicit Gold database exception.
- Updated the existing `.env.example` to use an obvious key placeholder and the
  same model example as the code default; aligned README examples with it.
- Bound the launcher and documented manual launch command to `127.0.0.1`.
- Documented Gemini data transmission, unauthenticated local-use scope, license
  boundaries, and source permission checks. Fixed a README typo.
- Moved runtime-check output to ignored `artifacts/runtime-validation`; evaluation
  provider exceptions now record only exception type, avoiding sensitive details.
- Replaced copied assignment prose with an original project-scope description.

## Secrets and private information

- Scanned tracked files, untracked publication candidates, local ignored text
  files, and all objects reachable through local branches, remote-tracking refs,
  tags, and reflogs. The repository is not shallow. There is one commit
  (`dd61742`), one local branch (`main`), the local `origin/main` tracking ref,
  and no tags. `git fsck --full --no-reflogs` reported no extra dangling objects.
- Scans checked provider-token patterns, private-key headers, credential-bearing
  URLs, credential assignments, email addresses, and local user paths. Candidate
  matches were reviewed without printing secret values. No confirmed credentials
  were found; **no rotation is indicated by this audit**. If credentials were
  previously shared elsewhere, removal here would not replace rotation.
- The initial commit's author/committer metadata contains a name and email
  address. `LICENSE` names the author. Confirm these are intended to be public.
  Exact email values are intentionally omitted here. Changing existing commit
  metadata would require a separately reviewed history rewrite.
- Ignored Ruff caches contain local user paths; generated Chainlit translations
  contain example email addresses. Neither is in the publication candidate.
- No internal service URLs, customer records, screenshots, notebooks, PDFs, or
  image assets were found in the publication candidate. Public aviation URLs and
  localhost development URLs are intentional.
- Read the Gold database in read-only mode: six aviation/evidence tables;
  `PRAGMA quick_check` returned `ok`. Scanned distinct text values in every text
  column for the same patterns, with no matches. This is not a forensic scan of
  unused SQLite pages or a guarantee against all forms of personal information.

## Dependency and code security

Queried PyPI release metadata and OSV for all ten directly pinned application and
development dependencies. All pinned releases exist and declare Python 3.11
compatibility. No full transitive audit was completed.

| Dependency | Finding | Proposed action requiring review |
|---|---|---|
| `chainlit==2.12.0` | [CVE-2026-86099](https://www.cve.org/CVERecord?id=CVE-2026-86099): unauthenticated session-ID path traversal with arbitrary directory deletion, affecting versions through 2.12.0. | Select a release with a verified fix or replace the affected integration; inspect the patch and rerun full chat/runtime tests. Localhost binding reduces network exposure but is not a patch. |
| `chainlit==2.12.0` | [CVE-2026-82290](https://www.cve.org/CVERecord?id=CVE-2026-82290): missing ownership checks for feedback changes. No persisted feedback/data layer is configured here. | Verify remediation with the Chainlit upgrade. |
| `fastmcp==2.14.7` | [Gemini CLI command injection](https://github.com/advisories/GHSA-m8x7-r2rg-vh5g), [OAuth-proxy consent bypass](https://github.com/advisories/GHSA-rww4-4w9c-7733), and [OpenAPI SSRF/path traversal](https://github.com/advisories/GHSA-vv7q-7jx5-f767). Advisory fixed version: 3.2.0. | Upgrade to a verified fixed FastMCP 3.x release and test the client, transport cleanup, tool registration, and Chainlit adapters. This crosses a major version and was not applied automatically. |

Dependency locations: `requirements.txt:1` (Chainlit), `requirements.txt:3`
(FastMCP). Pins were left unchanged pending the upgrade review.

The FastMCP affected features appear unused: this project starts a fixed local
stdio process, without Gemini CLI installation, an OAuth proxy, or an OpenAPI
provider. This limits apparent exploitability, but does not remove the vulnerable
dependency. PyPI/OSV returned no Chainlit findings; the additional CVE-source check
above caught the two Chainlit records, demonstrating a coverage gap.

Static review found parameterized user SQL filters, a read-only SQLite connection,
fixed subprocess argument arrays without shell execution, masked MCP errors, and
sanitized chat errors. No obvious arbitrary code execution or SQL injection was
found in these paths. The model has only the six analysis tools, not shell/file
write tools. This was a focused review, not a penetration test.

## Reproducibility and repository hygiene

- Only `LICENSE` and `README.md` are currently tracked. Application code, tests,
  configuration, docs, and the Gold database are untracked. A clone of the current
  commit therefore cannot run the described application. Review and commit the
  intended files after resolving the blockers; no staging was performed here.
- No ignored files are already tracked (`git ls-files -ci --exclude-standard`).
- The intentional database exception is 101,695,488 bytes (about 97 MiB). Consider
  a separately reviewed Git LFS or release-download approach for future growth;
  no binary was deleted, moved, or converted. Other local databases are ignored.
- Created a separate Python 3.11 environment in the system temporary directory for checks. Attempted installation
  using `pip install --only-binary=:all: -r requirements-dev.txt`. It stopped
  because Chainlit pins `literalai==0.1.201`, whose PyPI release has only an sdist.
  Source build scripts were not executed. This is a limitation of the safe audit
  install, not proof that the normal README install fails.
- Full installation, full chat/MCP tests, HTTP startup, and live Gemini requests
  remain unverified. No API key was used and no paid model calls were made.
- Installed only wheel distributions for pandas, Pydantic, pytest, Ruff, and
  their dependencies in the ignored audit environment. `pytest -q tests/analysis
  tests/etl` completed with **257 passed and 15 failed**; all 15 failures were
  imports of the absent `fastmcp` package in MCP-dependent cases, not failed
  calculation assertions. A focused rerun confirmed the same dependency issue.
  The full suite is not green and must be rerun in a complete fixed environment.
- Ruff passed for `app`, `tests`, and `run_app.py`; syntax parsing passed for all
  34 Python files. `pip check` passed for the partial audit environment, and
  `git diff --check` passed. Read-only traffic-growth and New England expansion
  queries against the distributed database returned results successfully.
- Requirements pin direct packages only; transitive dependencies are not locked
  or hash-verified. After the dependency upgrade, resolve and audit the complete
  environment and record a tested lock/constraints file.
- README covers purpose, setup, usage, environment variables, public sources, and
  analytical limitations. Raw and Silver snapshots and the mapping audit are not
  present; rebuilding the exact distributed database from public downloads is
  not independently reproducible without acquisition dates, exact extracts,
  checksums, and those inputs. Model naming was checked against Google documentation; account access and live responses were not tested.

## Publishing rights and owner decisions

1. Replaced the copied assignment summary with an original description of implemented
   project scope following the user's instruction. No source PDF is distributed.
   The maintainer must still verify rights to any assessment-derived question wording
   and any employer-owned code; removing attribution alone does not establish rights.
2. Verify the provenance and redistribution conditions of the prepared database's
   actual BTS/FAA inputs. [OurAirports](https://ourairports.com/data/) explicitly
   releases its data to the public domain. That does not establish the rights to
   every other input. See `THIRD_PARTY_NOTICES.md` for the source inventory.
3. Confirm code authorship/employer rights and intentional publication of author
   identity and commit email. An MIT project license already exists and was left
   unchanged; no new license was selected.

Remote branches not represented in this checkout, deleted remote history,
external artifacts, upstream authorship, legal permission, and exhaustive
secret-detection coverage could not be verified. Fetched origin branches and tags during review; the same single commit and no tags were present.

## Validation results

- Ruff: all checks passed. Markdown local links and `git diff --check`: passed.
- Initial analysis/ETL run: 257 passed, 15 failed solely because FastMCP was not
  installed in the partial environment. Installed FastMCP separately from wheels
  and reran service/MCP tests; final results are recorded below.
- `pip-audit` of direct application pins reported the two unique FastMCP issues
  above (duplicate PYSEC/GHSA aliases). Registry results alone missed other
  advisories; the broader advisory review is reflected in the table.
- SQLite `quick_check`: ok; 8,696 distinct text values scanned without matches.

- Final service/MCP rerun: **99 passed**, including the 15 tests initially blocked
  by missing FastMCP. Two upstream Authlib deprecation warnings. Combined with the
  earlier passing analysis/ETL tests, no tested project behavior remains failing.
  Full UI tests and Chainlit HTTP startup were not run.

- Audit of the installed partial environment additionally flagged transitive
  `diskcache==5.6.3` (`PYSEC-2026-2447`, no fixed version listed), plus the temporary
  environment's bootstrap pip/setuptools. Review DiskCache usage and remediation
  during dependency upgrades; bootstrap tooling findings are separate from app pins.
  This partial audit does not cover the unresolved Chainlit dependency tree.
