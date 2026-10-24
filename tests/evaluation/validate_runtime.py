"""Read-only real-server and Chainlit HTTP startup checks, without LLM calls."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "run_app.py").exists())
OUT = ROOT / "artifacts/runtime-validation"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    async with Client(StdioTransport(command=sys.executable, args=[str(ROOT / "app/mcp_server.py")], keep_alive=False), timeout=120) as client:
        tools = await client.list_tools()
        assert len(tools) == 6
        checks["tool_discovery"] = [tool.name for tool in tools]
        ids = {}
        for code in ("LAX", "SNA", "ANC", "SFO"):
            lookup = await client.call_tool("lookup_airports", {"airport_code": code})
            rows = lookup.structured_content["result"]
            assert len(rows) == 1
            ids[code] = rows[0]["canonical_airport_id"]
        requests = [
            ("terminal_expansion_opportunity", {"region": "New England"}),
            ("airport_operational_pressure", {"airport_ids": [ids["LAX"], ids["SNA"]]}),
            ("outbound_long_haul_share", {"airport_ids": [ids["ANC"]]}),
            ("demand_capacity_pressure", {"airport_ids": [ids["SFO"]]}),
            ("demand_capacity_pressure", {"state_code": "TX"}),
        ]
        data = []
        for index, (name, arguments) in enumerate(requests, 1):
            result = await client.call_tool(name, arguments)
            assert not result.is_error
            evidence = result.structured_content
            assert evidence["status"] in ("ok", "partial")
            assert evidence["results"]
            data.append(evidence)
            (OUT / f"mcp-smoke-q{index}.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        assert data[0]["answer_summary"]["leading_candidate"]["airport_code"] == "PVD"
        assert data[0]["forecast_metadata"]["edition"] == 2025
        lax = next(row for row in data[1]["results"] if row["airport_code"] == "LAX")
        assert round(lax["values"]["mean_positive_arrival_delay_minutes"], 2) == 14.04
        assert data[1]["metric_definitions"]["mean_positive_arrival_delay_minutes"]["denominator"] == "arrival_delay_observed_flights"
        assert round(data[2]["results"][0]["values"]["long_haul_share_pct"], 2) == 14.36
        assert data[3]["results"][0]["status"] == "partial"
        assert round(data[3]["results"][0]["values"]["passenger_seat_growth_gap_pp"], 2) == -1.23
        assert len(data[4]["airports"]) == 70
        assert [row["airport_code"] for row in data[4]["answer_summary"]["growing_faster_than_seats"]] == ["ABI", "VCT", "SJT", "SPS", "CRP"]
        checks["first_five_mcp_checks"] = "passed"

    with socket.socket() as temporary_socket:
        temporary_socket.bind(("127.0.0.1", 0))
        port = temporary_socket.getsockname()[1]
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "app"), "PYTHONIOENCODING": "utf-8"}
    command = [sys.executable, "-m", "chainlit", "run", "app/ui/app.py", "--headless", "--host", "127.0.0.1", "--port", str(port)]
    with (OUT / "chainlit-startup.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Chainlit exited before HTTP startup")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                        assert response.status == 200
                        assert b"<html" in response.read().lower()
                        checks["chainlit_http_startup"] = "HTTP 200, HTML served"
                        break
                except OSError:
                    await asyncio.sleep(0.5)
            else:
                raise TimeoutError("Chainlit did not start within 30 seconds")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    checks["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    (OUT / "runtime-smoke.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
