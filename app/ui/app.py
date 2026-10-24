import os
import sys
from pathlib import Path

import chainlit as cl
import httpx
from chainlit.logger import logger as log_
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from langchain_core.exceptions import (
    ModelAPIError,
    ModelAuthenticationError,
    ModelError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
)
from langchain_core.messages import HumanMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_mcp_adapters.tools import load_mcp_tools
from ui.agent import TOOL_TIMEOUT, run_agent

SERVER_PATH = Path(__file__).resolve().parents[1] / "mcp_server.py"
ACTIVE_CLIENTS: set[Client] = set()


async def show_error(content: str) -> None:
    error = cl.Message(content=content)
    await error.send()
    cl.chat_context.remove(error)


async def _close_client(client: Client) -> None:
    """Close the MCP connection - transport cleanup still runs after a failed initialization."""
    try:
        try:
            await client.close()
        finally:
            await client.transport.close()
    except Exception as error:  # Cleanup boundary must not hide the original startup failure.
        log_.error(f"Airport MCP cleanup failed: {type(error).__name__}")


@cl.on_chat_start
async def start_chat() -> None:
    """Connect the chat to its MCP process - reuse the connection across messages."""
    transport = StdioTransport(command=sys.executable, args=[str(SERVER_PATH)], keep_alive=False)
    client = Client(transport, timeout=TOOL_TIMEOUT, init_timeout=30)
    cl.user_session.set("mcp_client", None)
    cl.user_session.set("messages", [])
    try:
        await client.__aenter__()
        tools = await load_mcp_tools(client.session, handle_tool_errors=False)
    except Exception as error:  # Process/protocol boundary needs one startup failure message.
        log_.error(f"Airport MCP startup failed: {type(error).__name__}")
        await _close_client(client)
        await show_error("Airport tools could not start. Check dependencies and restart the chat.")
        return
    ACTIVE_CLIENTS.add(client)
    cl.user_session.set("mcp_client", client)
    cl.user_session.set("mcp_tools", tools)


@cl.on_chat_end
async def end_chat() -> None:
    client = cl.user_session.get("mcp_client")
    if client is not None:
        cl.user_session.set("mcp_client", None)
        ACTIVE_CLIENTS.discard(client)
        await _close_client(client)


@cl.on_app_shutdown
async def close_clients() -> None:
    for client in tuple(ACTIVE_CLIENTS):
        await _close_client(client)
        ACTIVE_CLIENTS.discard(client)


@cl.on_message
async def handle_message(message: cl.Message) -> None:
    client = cl.user_session.get("mcp_client")
    tools = cl.user_session.get("mcp_tools") or []
    history = cl.user_session.get("messages") or []
    messages = [*history, HumanMessage(content=message.content)]
    if not os.getenv("GEMINI_API_KEY"):
        await show_error("Add GEMINI_API_KEY to your .env file, restart the app, and try again.")
        return
    if client is None:
        await show_error("Airport tools are unavailable. Restart the chat to reconnect.")
        return
    try:
        messages = await run_agent(tools=tools, messages=messages)
        answer = messages[-1].text if messages else ""
    except (ModelError, ChatGoogleGenerativeAIError) as error:
        status = getattr(error, "code", None) or getattr(error.__cause__, "code", None)
        log_.error(f"Gemini request failed: {type(error).__name__}, status={status}")
        if isinstance(error, (ModelAuthenticationError, ModelPermissionDeniedError)):
            await show_error("Gemini rejected the API key. Check GEMINI_API_KEY and restart the app.")
        elif isinstance(error, ModelRateLimitError):
            await show_error("Gemini's rate limit or quota was reached. Check your quota or try again later.")
        elif isinstance(error, ModelNotFoundError):
            await show_error("Gemini model was not found. Set LLM_MODEL to an available Gemini model and restart.")
        elif isinstance(error, ModelAPIError) and getattr(error, "code", None) == 503:
            await show_error("Gemini is busy due to high demand. Retry shortly or choose another Gemini model in LLM_MODEL.")
        else:
            await show_error("Gemini could not complete the request. Check LLM_MODEL and try again.")
        return
    except httpx.TimeoutException:
        await show_error("Gemini timed out. Try again or choose a faster Gemini model in LLM_MODEL.")
        return
    except httpx.TransportError:
        await show_error("Gemini could not complete the request. Check your connection, then retry.")
        return
    if not answer:
        await show_error("Gemini returned no text. Try rephrasing your question.")
        return
    cl.user_session.set("messages", messages)
    await cl.Message(content=answer).send()
