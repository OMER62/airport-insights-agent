"""Live first-five evaluation: python evaluate_agent.py --runs 2 --output PATH."""

# Imports follow local path and environment setup so this script runs directly.
# ruff: noqa: E402

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "run_app.py").exists())
sys.path.insert(0, str(ROOT / "app"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
from chainlit.context import init_http_context
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from ui.agent import DEFAULT_MODEL, SYSTEM_PROMPT, run_agent


def check_answer(index, result):
    """Flag known regressions; these checks do not replace manual evidence review."""
    answer = result.get("answer", "")
    calls = [call for message in result.get("messages", []) for call in message.get("tool_calls", [])]
    metrics = [call for call in calls if call["name"] != "lookup_airports"]
    expected = {1: "terminal_expansion_opportunity", 2: "airport_operational_pressure",
                3: "outbound_long_haul_share", 4: "demand_capacity_pressure", 5: "demand_capacity_pressure"}
    flags = []
    if not answer:
        flags.append("No answer")
    if not any(call["name"] == expected[index] for call in metrics):
        flags.append("Expected analytical tool not called")
    if any(call["args"].get("region") == "South" for call in metrics) and index == 5:
        flags.append("Texas geography broadened to South")
    if index == 5 and not any(call["args"].get("state_code", "").upper() == "TX" for call in metrics):
        flags.append("Texas search did not use server-side state selection")
    if index == 2 and re.search(r"when flights are delayed|among delayed flights|per delayed flight", answer, re.I):
        flags.append("Review delay denominator: delayed-flight wording")
    if index == 2 and "per observed completed arrival" not in answer.lower():
        flags.append("Missing explicit observed-arrival delay denominator")
    if index == 1 and "PVD" not in answer.split("\n\n")[0] and "Green" not in answer.split("\n\n")[0]:
        flags.append("Opening does not name PVD")
    if index == 4 and not re.search(r"partial|incomplete|paired.*coverage", answer, re.I):
        flags.append("Partial measurement coverage not disclosed")
    if re.search(r"TAF\s*2024\s*edition|2024\s*(?:TAF\s*)?edition", answer, re.I):
        flags.append("Review forecast edition: tool metadata is 2025")
    errors = [message.get("name") for message in result.get("messages", [])
              if message.get("type") == "tool" and message.get("status") == "error"]
    if errors:
        flags.append(f"Tool errors: {errors}")
    return {"flags": flags, "tool_calls": [{"name": call["name"], "args": call["args"]} for call in calls],
            "answer_words": len(answer.split()), "manual_review_required": True}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--pause", type=float, default=15)
    parser.add_argument("--question", type=int, choices=range(1, 6))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1 or args.pause < 0:
        parser.error("runs must be positive and pause nonnegative")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "configuration.json").exists():
        parser.error("Choose a new output directory to preserve prior evidence")
    rows = (ROOT / "docs/01-overview/test-set.md").read_text(encoding="utf-8").splitlines()
    questions = [row.split("|")[2].strip() for row in rows if any(row.startswith(f"| {i} |") for i in range(1, 6))]
    config = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "model": os.getenv("LLM_MODEL") or DEFAULT_MODEL,
              "prompt": SYSTEM_PROMPT, "runs": args.runs, "questions": questions,
              "method": "Production agent and middleware, real stdio MCP; fresh history per question; browser UI bypassed"}
    (out / "configuration.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    summaries = []
    transport = StdioTransport(command=sys.executable, args=[str(ROOT / "app/mcp_server.py")], keep_alive=False)
    async with Client(transport, timeout=120, init_timeout=30) as client:
        tools = await load_mcp_tools(client.session, handle_tool_errors=False)
        (out / "tools.json").write_text(json.dumps([{"name": t.name, "description": t.description, "schema": t.args_schema} for t in tools], indent=2, default=str), encoding="utf-8")
        for run in range(1, args.runs + 1):
            for index, question in enumerate(questions, 1):
                if args.question and args.question != index:
                    continue
                init_http_context()
                start = time.monotonic()
                result = {"question": question, "run": run, "attempt_errors": []}
                for attempt in range(2):
                    try:
                        messages = await run_agent(tools, [HumanMessage(content=question)])
                        result["messages"] = [message.model_dump(mode="json") for message in messages]
                        result["answer"] = messages[-1].text
                        break
                    except Exception as error:
                        # Provider exception text can contain request data or credentials.
                        detail = type(error).__name__
                        result["attempt_errors"].append(detail)
                        if attempt == 0 and (getattr(error, "code", None) == 429 or "RateLimit" in detail):
                            print(f"Run {run} Q{index}: rate limit; retrying in 55 seconds", flush=True)
                            await asyncio.sleep(55)
                        else:
                            result["error"] = detail
                            break
                result["seconds"] = round(time.monotonic() - start, 2)
                result["checks"] = check_answer(index, result)
                filename = f"run{run}-q{index}"
                (out / f"{filename}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                (out / f"{filename}.md").write_text(f"# Run {run}, question {index}\n\n{question}\n\n{result.get('answer', result.get('error', 'No answer'))}\n", encoding="utf-8")
                summaries.append({"run": run, "question": index, "seconds": result["seconds"], **result["checks"]})
                (out / "checks.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
                print(f"Run {run} Q{index}: {result['seconds']}s; flags={result['checks']['flags']}", flush=True)
                await asyncio.sleep(args.pause)


if __name__ == "__main__":
    asyncio.run(main())
