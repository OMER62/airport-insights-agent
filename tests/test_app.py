import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import chainlit as cl
import httpx
from chainlit.context import init_http_context
from fastmcp import Client
from google.genai import errors, types
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from ui.agent import run_agent
from ui.app import end_chat, handle_message, start_chat


def completion(content: str | None) -> types.GenerateContentResponse:
    parts = [types.Part(text=content)] if content else []
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])


class GeminiChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = init_http_context()
        self.context.emitter.send_step = AsyncMock()
        cl.user_session.set("mcp_client", SimpleNamespace())
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "LLM_MODEL": "gemini-test"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def ask(self, content):
        message = cl.Message(content=content, type="user_message")
        cl.chat_context.add(message)
        await handle_message(message)

    async def test_follow_up_includes_previous_turn_once(self):
        with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
            api.side_effect = [completion("We are comparing LAX and SNA."), completion("LAX and SNA.")]
            await self.ask("Compare LAX and SNA")
            await self.ask("Which airports did I mention?")
        messages = api.call_args.kwargs["contents"]
        self.assertEqual([m.role for m in messages], ["user", "model", "user"])
        self.assertEqual(messages[0].parts[0].text, "Compare LAX and SNA")
        self.assertEqual(messages[-1].parts[0].text, "Which airports did I mention?")
        self.assertEqual(api.call_args.kwargs["model"], "gemini-test")

    async def test_missing_key_skips_api_and_keeps_error_out_of_history(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                await self.ask("Hello")
        api.assert_not_awaited()
        self.assertEqual(len(cl.chat_context.get()), 1)
        sent = self.context.emitter.send_step.call_args.args[0]
        self.assertIn("GEMINI_API_KEY", sent["output"])

    async def test_provider_errors_and_empty_responses_are_not_remembered(self):
        cases = [
            (errors.ClientError(code=403, response_json={"error": {"message": "private details"}}), "API key"),
            (errors.ClientError(code=429, response_json={"error": {"message": "private details"}}), "quota"),
            (httpx.ConnectError("private details"), "could not complete"),
            (httpx.ReadTimeout("private details"), "timed out"),
            (errors.ClientError(code=404, response_json={"error": {"message": "private details"}}), "not found"),
            (errors.ServerError(code=503, response_json={"error": {"message": "private details"}}), "high demand"),
            (None, "no text"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                cl.chat_context.clear()
                with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                    api.side_effect = error
                    api.return_value = completion(None)
                    await self.ask("Hello")
                sent = self.context.emitter.send_step.call_args.args[0]
                self.assertIn(expected, sent["output"])
                self.assertNotIn("private details", sent["output"])
                self.assertEqual(len(cl.chat_context.get()), 1)
                self.assertFalse(cl.user_session.get("messages"))

    async def test_new_session_has_separate_history(self):
        cl.chat_context.add(cl.Message(content="Private previous question", type="user_message"))
        init_http_context()
        self.assertEqual(cl.chat_context.to_openai(), [])

    async def test_lookup_then_analysis_and_follow_up_keep_tool_evidence(self) -> None:
        server = import_module("mcp_server")
        dao = import_module("analysis.dao_get_gold_data")
        self.context.emitter.update_step = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "gold.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript("""
                    CREATE TABLE airport_dimension(canonical_airport_id INTEGER, airport_code TEXT,
                        name TEXT, state_code TEXT, country_code TEXT, us_region TEXT);
                    INSERT INTO airport_dimension VALUES (1,'MIA','Miami','FL','US','South');
                """)
                connection.commit()
            lookup = completion(None)
            lookup.candidates[0].content.parts = [types.Part(
                function_call=types.FunctionCall(id="lookup", name="lookup_airports", args={"state_code": "FL"}),
                thought_signature=b"preserve-this-signature",
            )]
            analysis = completion(None)
            analysis.candidates[0].content.parts = [types.Part(
                function_call=types.FunctionCall(id="analysis", name="traffic_growth", args={"airport_ids": [1]}),
            )]
            with patch.object(dao, "GOLD_DATABASE_PATH", database):
                async with Client(server.mcp) as client:
                    cl.user_session.set("mcp_client", client)
                    cl.user_session.set("mcp_tools", await load_mcp_tools(client.session, handle_tool_errors=False))
                    with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                        api.side_effect = [lookup, analysis, completion("Miami found; traffic evidence unavailable."),
                                           completion("We were discussing Miami.")]
                        await self.ask("Find Florida airports and compare growth")
                        await self.ask("Which airport?")
                        messages = api.call_args.kwargs["contents"]
        evidence = [part.function_response.response for item in messages
                    for part in item.parts if part.function_response]
        self.assertIn("Miami", json.dumps(evidence[0]))
        self.assertIn("failed", json.dumps(evidence[1]))
        self.assertEqual(messages[-1].parts[0].text, "Which airport?")
        self.assertIn("Miami found", messages[-2].parts[0].text)
        self.assertEqual(messages[1].parts[0].thought_signature, b"preserve-this-signature")

    async def test_invalid_tool_arguments_and_unknown_tools_are_recoverable(self) -> None:
        server = import_module("mcp_server")
        self.context.emitter.update_step = AsyncMock()
        async with Client(server.mcp) as client:
            tools = await load_mcp_tools(client.session, handle_tool_errors=False)
            for name, arguments in (("missing_tool", {}), ("lookup_airports", {"state_code": ""}),
                                    ("traffic_growth", {"airport_ids": "bad"})):
                with self.subTest(name=name):
                    response = completion(None)
                    response.candidates[0].content.parts = [types.Part(
                        function_call=types.FunctionCall(id="bad", name=name, args=arguments),
                    )]
                    with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                        api.side_effect = [response, completion("Evidence unavailable.")]
                        messages = await run_agent(tools, [HumanMessage("Find an airport")])
                    evidence = [message for message in messages if isinstance(message, ToolMessage)]
                    self.assertEqual(evidence[0].status, "error")
                    self.assertEqual(evidence[0].tool_call_id, "bad")
                    self.assertEqual(messages[-1].text, "Evidence unavailable.")

    async def test_round_limit_forces_evidence_summary(self) -> None:
        server = import_module("mcp_server")
        response = completion(None)
        response.candidates[0].content.parts = [types.Part(
            function_call=types.FunctionCall(id="bad", name="lookup_airports", args={"state_code": ""}),
        )]
        self.context.emitter.update_step = AsyncMock()
        async with Client(server.mcp) as client:
            tools = await load_mcp_tools(client.session, handle_tool_errors=False)
            with patch("ui.agent.MAX_TOOL_ROUNDS", 1):
                with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                    api.side_effect = [response, completion("The tool limit was reached; evidence is missing.")]
                    messages = await run_agent(tools, [HumanMessage("Keep researching")])
        self.assertIn("limit", messages[-1].text)
        config = api.call_args.kwargs["config"]
        self.assertFalse(config.tools)
        self.assertIn("Tool-round limit reached", str(config.system_instruction))
        self.assertEqual(len([message for message in messages if isinstance(message, ToolMessage)]), 1)
        self.assertFalse(any(message.type == "system" for message in messages))

    async def test_stdio_startup_discovers_tools_and_cleanup_closes_connection(self) -> None:
        await start_chat()
        client = cl.user_session.get("mcp_client")
        try:
            tools = cl.user_session.get("mcp_tools")
            self.assertEqual(len(tools), 6)
            self.assertTrue(client.is_connected())
            self.assertIn("lookup_airports", [tool.name for tool in tools])
        finally:
            await end_chat()
        self.assertFalse(client.is_connected())

    async def test_parallel_calls_keep_successful_evidence_when_a_sibling_fails(self) -> None:
        server = import_module("mcp_server")
        self.context.emitter.update_step = AsyncMock()
        response = completion(None)
        response.candidates[0].content.parts = [
            types.Part(function_call=types.FunctionCall(id="good", name="lookup_airports", args={"state_code": "FL"})),
            types.Part(function_call=types.FunctionCall(id="bad", name="lookup_airports", args={"state_code": ""})),
        ]
        with patch.object(server.service, "get_gold_data", return_value=[{"canonical_airport_id": 1, "name": "Miami"}]):
            async with Client(server.mcp) as client:
                tools = await load_mcp_tools(client.session, handle_tool_errors=False)
                with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                    api.side_effect = [response, completion("Miami found; other evidence unavailable.")]
                    messages = await run_agent(tools, [HumanMessage("Find airports")])
        evidence = {message.tool_call_id: message for message in messages if isinstance(message, ToolMessage)}
        self.assertEqual(evidence["good"].status, "success")
        self.assertIn("Miami", evidence["good"].text)
        self.assertIn("Miami", json.dumps(evidence["good"].artifact))
        self.assertEqual(evidence["bad"].status, "error")
        steps = [call.args[0] for call in self.context.emitter.send_step.call_args_list]
        self.assertEqual(len([step for step in steps if step["type"] == "tool"]), 2)

    async def test_tool_timeout_returns_evidence_gap_instead_of_failing_the_turn(self) -> None:
        server = import_module("mcp_server")
        self.context.emitter.update_step = AsyncMock()
        response = completion(None)
        response.candidates[0].content.parts = [types.Part(
            function_call=types.FunctionCall(id="slow", name="lookup_airports", args={"state_code": "FL"}),
        )]

        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(60)

        async with Client(server.mcp) as client:
            tools = await load_mcp_tools(client.session, handle_tool_errors=False)
            with patch.object(client.session, "call_tool", side_effect=slow_tool):
                with patch("ui.agent.TOOL_TIMEOUT", 0.01):
                    with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                        api.side_effect = [response, completion("Airport evidence is unavailable.")]
                        messages = await run_agent(tools, [HumanMessage("Find airports")])
        evidence = [message for message in messages if isinstance(message, ToolMessage)]
        self.assertEqual(evidence[0].status, "error")
        self.assertIn("evidence unavailable", evidence[0].text)
        self.assertEqual(messages[-1].text, "Airport evidence is unavailable.")

    async def test_tool_budget_resets_for_follow_up_and_rejects_calls_after_limit(self) -> None:
        server = import_module("mcp_server")
        self.context.emitter.update_step = AsyncMock()
        response = completion(None)
        response.candidates[0].content.parts = [types.Part(
            function_call=types.FunctionCall(id="bad", name="lookup_airports", args={"state_code": ""}),
        )]
        async with Client(server.mcp) as client:
            tools = await load_mcp_tools(client.session, handle_tool_errors=False)
            with patch("ui.agent.MAX_TOOL_ROUNDS", 1):
                with patch("google.genai.models.AsyncModels.generate_content", new_callable=AsyncMock) as api:
                    api.side_effect = [response, response, response, completion("The limit was reached.")]
                    messages = await run_agent(tools, [HumanMessage("Keep researching")])
                    self.assertFalse(getattr(messages[-1], "tool_calls", None))
                    messages = await run_agent(tools, [*messages, HumanMessage("Try again")])
        self.assertEqual(len([message for message in messages if isinstance(message, ToolMessage)]), 2)
        self.assertTrue(api.call_args_list[2].kwargs["config"].tools)
        self.assertFalse(api.call_args_list[3].kwargs["config"].tools)

    async def test_startup_failure_is_explained(self) -> None:
        cl.user_session.set("mcp_client", None)
        with patch("ui.app.SERVER_PATH", Path("missing-airport-server.py")):
            await start_chat()
        self.assertIsNone(cl.user_session.get("mcp_client"))
        sent = self.context.emitter.send_step.call_args.args[0]
        self.assertIn("could not start", sent["output"])
