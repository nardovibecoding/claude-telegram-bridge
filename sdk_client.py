# Copyright (c) 2026 Nardo. AGPL-3.0 — see LICENSE
"""Claude Code SDK client wrapper.

Persistent connection to Claude Code CLI via the Agent SDK.
Cold start ~6s once, then 2-3s per message. Auto-reconnects on crash.
"""
import asyncio
import logging
import os
import shutil

# Prevent "nested session" error if running inside Claude Code
for _k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
    os.environ.pop(_k, None)

from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
)

log = logging.getLogger("sdk")

# Model ID mapping
MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# Per-cwd clients: each unique working directory gets its own client
_clients: dict[str, ClaudeSDKClient] = {}  # cwd -> client
_client_lock = asyncio.Lock()
_creation_locks: dict[str, asyncio.Lock] = {}  # cwd -> creation lock


def _get_creation_lock(cwd: str) -> asyncio.Lock:
    if cwd not in _creation_locks:
        _creation_locks[cwd] = asyncio.Lock()
    return _creation_locks[cwd]


async def _get_or_create_client(
    system_prompt: str, model: str, cwd: str
) -> ClaudeSDKClient:
    """Get existing client for cwd or create new one."""
    # Fast path — no lock needed if client exists and is alive
    client = _clients.get(cwd)

    if client is not None:
        try:
            if client._transport and client._transport.is_ready():
                return client
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass
        _clients.pop(cwd, None)

    # Serialize creation per cwd to prevent duplicate clients
    async with _get_creation_lock(cwd):
        # Double-check after acquiring lock — another coroutine may have created it
        if cwd in _clients:
            client = _clients[cwd]
            try:
                if client._transport and client._transport.is_ready():
                    return client
            except Exception:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass
            _clients.pop(cwd, None)

        model_id = MODEL_MAP.get(model, model)
        global_cli = shutil.which("claude")

        options = ClaudeAgentOptions(
            model=model_id,
            permission_mode="bypassPermissions",
            system_prompt=system_prompt or None,
            cwd=cwd,
            cli_path=global_cli,
            setting_sources=["user", "project"],
            allowed_tools=[
                "Skill", "Read", "Write", "Edit", "Bash",
                "Glob", "Grep", "WebFetch", "WebSearch", "Agent",
            ],
        )

        client = ClaudeSDKClient(options)
        await asyncio.wait_for(client.connect(), timeout=30)
        _clients[cwd] = client
        log.info("SDK client connected: model=%s cwd=%s", model_id, cwd)
        return client


async def sdk_query(
    prompt: str,
    system_prompt: str = "",
    model: str = "sonnet",
    cwd: str = "~",
    on_text: callable = None,
    on_tool: callable = None,
) -> str:
    """Send a message to Claude Code SDK. Returns result text.

    Args:
        prompt: User message
        system_prompt: System prompt for the session
        model: haiku/sonnet/opus or full model ID
        cwd: Working directory for Claude
        on_text: Async callback for streaming text blocks
        on_tool: Async callback for tool use blocks (name, input)
    """
    async with _client_lock:
        try:
            client = await _get_or_create_client(system_prompt, model, cwd)
        except Exception as e:
            log.error("Client creation failed: %s", e)
            raise

        result_text = ""
        text_chunks = []

        try:
            await asyncio.wait_for(client.query(prompt), timeout=15)

            async for msg in client.receive_messages():
                if isinstance(msg, ResultMessage):
                    result_text = msg.result or ""
                    break
                elif isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            text_chunks.append(block.text)
                            if on_text:
                                await on_text(block.text)
                        elif isinstance(block, ToolUseBlock):
                            if on_tool:
                                await on_tool(block.name, block.input)

            if not result_text and text_chunks:
                result_text = text_chunks[-1]

            return result_text

        except Exception as e:
            log.error("SDK query failed (cwd=%s): %s — will reconnect", cwd, e)
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5)
            except Exception:
                pass
            _clients.pop(cwd, None)
            raise


async def sdk_disconnect_all():
    """Disconnect all SDK clients. Call on bot shutdown."""
    for cwd, client in list(_clients.items()):
        try:
            await client.disconnect()
            log.info("SDK client disconnected: cwd=%s", cwd)
        except Exception:
            pass
    _clients.clear()
