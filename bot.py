# Copyright (c) 2026 Nardo. AGPL-3.0 — see LICENSE
"""Telegram bot that bridges messages to Claude Code SDK.

Usage:
    BOT_TOKEN=your_token ALLOWED_USERS=123456 python bot.py
"""
import asyncio
import html
import json
import logging
import os
import re
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes,
)

from sdk_client import sdk_query, sdk_disconnect_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("bridge")

# ── Config from env ──────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USERS = {int(x) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()}
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "You are a helpful coding assistant.")
WORKING_DIR = os.environ.get("WORKING_DIR", os.path.expanduser("~"))
MODEL = os.environ.get("MODEL", "sonnet")
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("RATE_LIMIT", "5"))
CHAT_DIRS = json.loads(os.environ.get("CHAT_DIRS", "{}"))

# ── Background task state ────────────────────────────────────────────
_bg_tasks: dict[int, asyncio.Task] = {}  # chat_id -> running task

# ── Rate limiting state ─────────────────────────────────────────────
_rate_limits: dict[int, list[float]] = {}  # user_id -> list of timestamps


def _auth(user_id: int) -> bool:
    """Check if user is allowed. Empty ALLOWED_USERS = allow all."""
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def _check_rate_limit(user_id: int) -> int | None:
    """Check rate limit. Returns seconds to wait, or None if OK."""
    now = time.time()
    timestamps = _rate_limits.get(user_id, [])
    # Prune old timestamps
    timestamps = [t for t in timestamps if now - t < 60]
    _rate_limits[user_id] = timestamps

    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        oldest = timestamps[0]
        wait = int(60 - (now - oldest)) + 1
        return wait

    timestamps.append(now)
    return None


# ── Markdown / HTML helpers ─────────────────────────────────────────
def _escape_html(text: str) -> str:
    """Escape <, >, & but preserve code blocks (``` and `)."""
    # Extract code blocks and inline code, escape the rest
    parts = []
    # Split on fenced code blocks first
    segments = re.split(r'(```[\s\S]*?```)', text)
    for seg in segments:
        if seg.startswith('```') and seg.endswith('```'):
            parts.append(seg)  # preserve code blocks as-is
        else:
            # Split on inline code
            inline_parts = re.split(r'(`[^`]+`)', seg)
            for ip in inline_parts:
                if ip.startswith('`') and ip.endswith('`') and len(ip) > 1:
                    parts.append(ip)  # preserve inline code
                else:
                    parts.append(html.escape(ip))
    return ''.join(parts)


def _markdown_to_tg_html(text: str) -> str:
    """Convert markdown to Telegram-compatible HTML.

    Handles: **bold**, *italic*, `code`, ```code blocks```.
    """
    # Step 1: Extract fenced code blocks and replace with placeholders
    code_blocks = []

    def _store_code_block(m):
        idx = len(code_blocks)
        lang = m.group(1) or ""
        code = html.escape(m.group(2))
        code_blocks.append(f"<pre>{code}</pre>")
        return f"\x00CODEBLOCK{idx}\x00"

    result = re.sub(r'```(\w*)\n?([\s\S]*?)```', _store_code_block, text)

    # Step 2: Extract inline code
    inline_codes = []

    def _store_inline(m):
        idx = len(inline_codes)
        inline_codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00INLINE{idx}\x00"

    result = re.sub(r'`([^`]+)`', _store_inline, result)

    # Step 3: Escape HTML in remaining text
    result = html.escape(result)

    # Step 4: Convert markdown formatting
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    result = re.sub(r'\*(.+?)\*', r'<i>\1</i>', result)

    # Step 5: Restore code blocks and inline code
    for i, block in enumerate(code_blocks):
        result = result.replace(f"\x00CODEBLOCK{i}\x00", block)
    for i, code in enumerate(inline_codes):
        result = result.replace(f"\x00INLINE{i}\x00", code)

    return result


async def _safe_edit_text(msg, text: str, **kwargs):
    """Edit message with HTML parse mode, fallback to plain text on error."""
    try:
        converted = _markdown_to_tg_html(text)
        await msg.edit_text(converted, parse_mode="HTML", **kwargs)
    except BadRequest:
        await msg.edit_text(text, parse_mode=None, **kwargs)
    except Exception:
        pass


async def _safe_reply_text(msg, text: str, **kwargs):
    """Reply with HTML parse mode, fallback to plain text on error."""
    try:
        converted = _markdown_to_tg_html(text)
        return await msg.reply_text(converted, parse_mode="HTML", **kwargs)
    except BadRequest:
        return await msg.reply_text(text, parse_mode=None, **kwargs)


async def _handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages — send to Claude SDK."""
    msg = update.effective_message
    user_id = update.effective_user.id

    if not _auth(user_id):
        await msg.reply_text("Not authorized.")
        return

    prompt = msg.text
    if not prompt:
        return

    # Rate limiting
    wait = _check_rate_limit(user_id)
    if wait is not None:
        await msg.reply_text(f"Rate limited, try again in {wait}s")
        return

    chat_id = msg.chat_id
    cwd = CHAT_DIRS.get(str(chat_id), WORKING_DIR)

    # Cancel previous task if still running
    if chat_id in _bg_tasks and not _bg_tasks[chat_id].done():
        _bg_tasks[chat_id].cancel()

    # Send "thinking" indicator
    status_msg = await msg.reply_text("Thinking...")

    async def _run():
        start = time.monotonic()
        tool_steps = []
        last_text = ""

        async def on_text(text: str):
            nonlocal last_text
            last_text = text
            # Update status with latest text snippet
            snippet = text[:200] + "..." if len(text) > 200 else text
            await _safe_edit_text(status_msg, snippet)

        async def on_tool(name: str, inp: dict):
            desc = _tool_description(name, inp)
            tool_steps.append(desc)
            progress = "\n".join(f"  {s}" for s in tool_steps[-5:])
            await _safe_edit_text(status_msg, f"Working...\n{progress}")

        try:
            result = await sdk_query(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                model=MODEL,
                cwd=cwd,
                on_text=on_text,
                on_tool=on_tool,
            )

            elapsed = time.monotonic() - start
            footer = f"\n\n({elapsed:.1f}s, {len(tool_steps)} tool calls)"

            # Send final result
            final = (result or last_text or "Done (no output).")
            if len(final) + len(footer) > 4096:
                # Split long messages
                for i in range(0, len(final), 4000):
                    await _safe_reply_text(msg, final[i:i+4000])
                await _safe_reply_text(msg, footer.strip())
            else:
                await _safe_edit_text(status_msg, final + footer)

        except asyncio.CancelledError:
            await status_msg.edit_text("Cancelled.")
        except Exception as e:
            log.error("SDK error: %s", e)
            await status_msg.edit_text(f"Error: {e}")

    task = asyncio.create_task(_run())
    _bg_tasks[chat_id] = task


def _tool_description(name: str, inp: dict) -> str:
    """Generate a short description of a tool use."""
    if name == "Bash":
        cmd = inp.get("command", "")[:60]
        return f"$ {cmd}"
    elif name == "Read":
        path = inp.get("file_path", "")
        return f"Read {os.path.basename(path)}"
    elif name in ("Edit", "Write"):
        path = inp.get("file_path", "")
        return f"{name} {os.path.basename(path)}"
    elif name == "Glob":
        return f"Glob {inp.get('pattern', '')}"
    elif name == "Grep":
        return f"Grep {inp.get('pattern', '')[:40]}"
    elif name == "WebSearch":
        return f"Search: {inp.get('query', '')[:40]}"
    elif name == "Agent":
        return f"Agent: {inp.get('description', '')[:40]}"
    else:
        return f"{name}"


async def _handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos — download and send to Claude for analysis."""
    msg = update.effective_message
    user_id = update.effective_user.id

    if not _auth(user_id):
        await msg.reply_text("Not authorized.")
        return

    # Rate limiting
    wait = _check_rate_limit(user_id)
    if wait is not None:
        await msg.reply_text(f"Rate limited, try again in {wait}s")
        return

    chat_id = msg.chat_id
    cwd = CHAT_DIRS.get(str(chat_id), WORKING_DIR)
    msg_id = msg.message_id

    # Download the photo (largest size)
    photo_file = await msg.photo[-1].get_file()
    tmp_path = f"/tmp/tg_upload_{msg_id}.jpg"
    await photo_file.download_to_drive(tmp_path)

    caption = msg.caption or ""
    prompt = f"User sent an image: {tmp_path}"
    if caption:
        prompt += f"\nCaption: {caption}"
    prompt += " — please read and analyze it"

    # Cancel previous task if still running
    if chat_id in _bg_tasks and not _bg_tasks[chat_id].done():
        _bg_tasks[chat_id].cancel()

    status_msg = await msg.reply_text("Analyzing image...")

    async def _run():
        start = time.monotonic()
        tool_steps = []
        last_text = ""

        async def on_text(text: str):
            nonlocal last_text
            last_text = text
            snippet = text[:200] + "..." if len(text) > 200 else text
            await _safe_edit_text(status_msg, snippet)

        async def on_tool(name: str, inp: dict):
            desc = _tool_description(name, inp)
            tool_steps.append(desc)
            progress = "\n".join(f"  {s}" for s in tool_steps[-5:])
            await _safe_edit_text(status_msg, f"Working...\n{progress}")

        try:
            result = await sdk_query(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                model=MODEL,
                cwd=cwd,
                on_text=on_text,
                on_tool=on_tool,
            )

            elapsed = time.monotonic() - start
            footer = f"\n\n({elapsed:.1f}s, {len(tool_steps)} tool calls)"
            final = (result or last_text or "Done (no output).")
            if len(final) + len(footer) > 4096:
                for i in range(0, len(final), 4000):
                    await _safe_reply_text(msg, final[i:i+4000])
                await _safe_reply_text(msg, footer.strip())
            else:
                await _safe_edit_text(status_msg, final + footer)

        except asyncio.CancelledError:
            await status_msg.edit_text("Cancelled.")
        except Exception as e:
            log.error("SDK error: %s", e)
            await status_msg.edit_text(f"Error: {e}")
        finally:
            # Cleanup temp file
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    task = asyncio.create_task(_run())
    _bg_tasks[chat_id] = task


async def _handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle incoming documents — download and send to Claude."""
    msg = update.effective_message
    user_id = update.effective_user.id

    if not _auth(user_id):
        await msg.reply_text("Not authorized.")
        return

    # Rate limiting
    wait = _check_rate_limit(user_id)
    if wait is not None:
        await msg.reply_text(f"Rate limited, try again in {wait}s")
        return

    chat_id = msg.chat_id
    cwd = CHAT_DIRS.get(str(chat_id), WORKING_DIR)
    msg_id = msg.message_id
    filename = msg.document.file_name or "unknown"

    # Download the document
    doc_file = await msg.document.get_file()
    tmp_path = f"/tmp/tg_upload_{msg_id}_{filename}"
    await doc_file.download_to_drive(tmp_path)

    caption = msg.caption or ""
    prompt = f"User sent a file: {tmp_path}"
    if caption:
        prompt += f"\nCaption: {caption}"
    prompt += " — please read and analyze it"

    # Cancel previous task if still running
    if chat_id in _bg_tasks and not _bg_tasks[chat_id].done():
        _bg_tasks[chat_id].cancel()

    status_msg = await msg.reply_text("Analyzing file...")

    async def _run():
        start = time.monotonic()
        tool_steps = []
        last_text = ""

        async def on_text(text: str):
            nonlocal last_text
            last_text = text
            snippet = text[:200] + "..." if len(text) > 200 else text
            await _safe_edit_text(status_msg, snippet)

        async def on_tool(name: str, inp: dict):
            desc = _tool_description(name, inp)
            tool_steps.append(desc)
            progress = "\n".join(f"  {s}" for s in tool_steps[-5:])
            await _safe_edit_text(status_msg, f"Working...\n{progress}")

        try:
            result = await sdk_query(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                model=MODEL,
                cwd=cwd,
                on_text=on_text,
                on_tool=on_tool,
            )

            elapsed = time.monotonic() - start
            footer = f"\n\n({elapsed:.1f}s, {len(tool_steps)} tool calls)"
            final = (result or last_text or "Done (no output).")
            if len(final) + len(footer) > 4096:
                for i in range(0, len(final), 4000):
                    await _safe_reply_text(msg, final[i:i+4000])
                await _safe_reply_text(msg, footer.strip())
            else:
                await _safe_edit_text(status_msg, final + footer)

        except asyncio.CancelledError:
            await status_msg.edit_text("Cancelled.")
        except Exception as e:
            log.error("SDK error: %s", e)
            await status_msg.edit_text(f"Error: {e}")
        finally:
            # Cleanup temp file
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    task = asyncio.create_task(_run())
    _bg_tasks[chat_id] = task


async def _handle_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    chat_id = update.effective_chat.id
    if chat_id in _bg_tasks and not _bg_tasks[chat_id].done():
        _bg_tasks[chat_id].cancel()
        await update.message.reply_text("Cancelling...")
    else:
        await update.message.reply_text("Nothing running.")


async def _shutdown(app: Application):
    """Cleanup on shutdown."""
    for task in _bg_tasks.values():
        if not task.done():
            task.cancel()
    await sdk_disconnect_all()


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, _handle_message
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO, _handle_photo
    ))
    app.add_handler(MessageHandler(
        filters.Document.ALL, _handle_document
    ))
    app.add_handler(MessageHandler(
        filters.Regex(r"^/cancel"), _handle_cancel
    ))

    app.post_shutdown = _shutdown

    log.info("Bot starting — model=%s, allowed_users=%s, chat_dirs=%s",
             MODEL, ALLOWED_USERS or "all", CHAT_DIRS or "none")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
