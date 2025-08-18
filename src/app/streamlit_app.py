from __future__ import annotations

import asyncio
import logging
import os
import re
import textwrap
import time
from collections.abc import Coroutine, Iterable, Sequence
from io import BytesIO

import streamlit as st
from pygments.lexers import guess_lexer
from pygments.util import ClassNotFound
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.ai.llm.factory import available_models, available_providers
from app.bot.commands import COMMAND_PROMPTS, get_prompt
from app.runtime import backend
from app.tools.registry import ensure_tools_loaded, list_tools

st.set_page_config(page_title="DevOps Bot Dashboard", layout="centered")

logger = logging.getLogger("devops_bot.streamlit")

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-5")

_SESSION_KEYS = (
    "selected_provider",
    "selected_model",
    "review_provider",
    "review_model",
    "chat_history",
    "last_cmd_input",
    "last_cmd_output",
    "last_cmd_reviewed",
    "last_chat_input",
    "last_chat_output",
    "last_chat_reviewed",
    "enable_tools",
    "preferred_tool",
)

for k in _SESSION_KEYS:
    st.session_state.setdefault(k, None)
st.session_state.chat_history = st.session_state.chat_history or []

st.title("DevOps Bot Dashboard")
st.caption("Chat freely or run focused DevOps checks. Tools are opt-in per request.")

_CODE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)


def run_async[T](coro: Coroutine[object, object, T]) -> T:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    return asyncio.run(coro)


def _split_text_and_code_blocks(text: str) -> Iterable[tuple[str, str | None]]:
    last_end = 0
    for match in _CODE_BLOCK_RE.finditer(text):
        if match.start() > last_end:
            yield text[last_end : match.start()], None
        lang = match.group(1).strip() or None
        yield match.group(2), lang
        last_end = match.end()
    if last_end < len(text):
        yield text[last_end:], None


def render_response_with_code(text: str) -> None:
    for chunk, lang in _split_text_and_code_blocks(text):
        if lang is None:
            clean = chunk.strip()
            if clean:
                st.markdown(clean)
        else:
            code_clean = chunk.strip()
            if not lang:
                lang = None
            if lang is None:
                try:
                    lexer = guess_lexer(code_clean)
                    lang = lexer.name.lower()
                except ClassNotFound:
                    lang = None
            st.code(code_clean, language=lang)


def render_score(review_text: str) -> None:
    m = re.search(r"\"score\"\s*:\s*(\d+)", review_text) or re.search(
        r"Score:\s*(\d+)\s*/\s*10", review_text
    )
    if m:
        st.markdown(f"**Reviewer Score:** {int(m.group(1))}/10")


def _wrap_text_for_pdf(text: str, width: int = 95) -> list[str]:
    lines: list[str] = []
    for chunk, lang in _split_text_and_code_blocks(text):
        if lang is None:
            for para in chunk.splitlines():
                lines.extend(textwrap.wrap(para, width=width) if para.strip() else [""])
        else:
            lines.append(f"[code:{lang or 'text'}]")
            for code_line in chunk.splitlines():
                lines.extend(textwrap.wrap(code_line, width=width, break_long_words=False) or [""])
            lines.extend(["[/code]", ""])
    return lines


def download_buttons(text: str) -> None:
    st.download_button("Download as Markdown", text, file_name="response.md")
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    _, height = letter
    y = height - 40
    for line in _wrap_text_for_pdf(text):
        pdf.drawString(40, y, line.encode("ascii", errors="replace").decode("ascii")[:200])
        y -= 14
        if y < 40:
            pdf.showPage()
            y = height - 40
    pdf.save()
    buffer.seek(0)
    st.download_button("Download as PDF", buffer, file_name="response.pdf")


def _safe_index(options: list[str], value: str | None) -> int:
    return options.index(value) if value in options and options else 0


with st.sidebar:
    st.header("Session")
    providers = available_providers()
    st.session_state.selected_provider = st.selectbox(
        "Provider",
        providers,
        index=_safe_index(providers, st.session_state.get("selected_provider") or DEFAULT_PROVIDER),
    )
    models = run_async(
        available_models(st.session_state.selected_provider)
    ) or ["<no models available>"]
    if st.session_state.get("selected_model") not in models:
        st.session_state.selected_model = models[0] if models else DEFAULT_MODEL
    st.session_state.selected_model = st.selectbox(
        "Model",
        models,
        index=_safe_index(models, st.session_state.get("selected_model")),
    )

    st.divider()
    st.subheader("Reviewer")
    review_providers = available_providers()
    st.session_state.review_provider = st.selectbox(
        "Review Provider",
        review_providers,
        index=_safe_index(
            review_providers,
            st.session_state.get("review_provider") or st.session_state.selected_provider,
        ),
    )
    review_models = run_async(
        available_models(st.session_state.review_provider)
    ) or ["<no models available>"]
    if st.session_state.get("review_model") not in review_models:
        st.session_state.review_model = review_models[0] if review_models else DEFAULT_MODEL
    st.session_state.review_model = st.selectbox(
        "Review Model",
        review_models,
        index=_safe_index(review_models, st.session_state.get("review_model")),
    )

    st.divider()
    st.session_state.enable_tools = st.toggle("Enable tools for this request", value=False)
    ensure_tools_loaded()
    tool_names = ["<auto>"] + [t.name for t in list_tools()]
    st.session_state.preferred_tool = st.selectbox("Preferred tool", tool_names, index=0)
    st.caption(
        "Keep tools off for normal chat. Turn on to allow CLI tool invocation. "
        "Reviewer can use a different provider and model."
    )

tab1, tab2 = st.tabs(["Command Prompts", "Free Chat"])


def _call(prompt: str, memory: Sequence[dict] | None = None) -> str:
    start = time.perf_counter()
    try:
        preferred = st.session_state.get("preferred_tool")
        preferred = None if not preferred or preferred == "<auto>" else preferred
        content = run_async(
            backend.chat(
                prompt,
                list(memory or []),
                provider=st.session_state.get("selected_provider"),
                model=st.session_state.get("selected_model"),
                enable_tools=bool(st.session_state.get("enable_tools")),
                preferred_tool=preferred,
            )
        )
    except Exception as exc:
        logger.exception("Assistant call failed")
        content = f"Error: {exc}"
        st.error("The assistant failed to respond.")
    latency_ms = round((time.perf_counter() - start) * 1000)
    st.caption(
        f"{st.session_state.get('selected_provider')} • "
        f"{st.session_state.get('selected_model')} • "
        f"{latency_ms} ms"
    )
    return content


def _review(u: str, a: str) -> str:
    try:
        return run_async(
            backend.review(
                u,
                a,
                provider=st.session_state.get("review_provider"),
                model=st.session_state.get("review_model"),
            )
        )
    except Exception as exc:
        logger.exception("Reviewer call failed")
        return f"Review error: {exc}"


with tab1:
    command = st.selectbox("Command", list(COMMAND_PROMPTS.keys()))
    user_input_cmd = st.text_area(
        "Input",
        key="cmd_input",
        height=200,
        placeholder="Paste a Docker error, K8s manifest, or Terraform snippet…",
    )
    if st.button("Submit", key="cmd_button"):
        if not user_input_cmd.strip():
            st.warning("Please provide input for the command.")
        else:
            with st.spinner("Generating assistant response…"):
                prompt = get_prompt(command, user_input_cmd) or user_input_cmd
                ai_reply = _call(prompt)
                st.session_state.last_cmd_input = user_input_cmd
                st.session_state.last_cmd_output = ai_reply
                st.session_state.last_cmd_reviewed = None
                st.subheader("Assistant Response")
                render_response_with_code(ai_reply)
                download_buttons(ai_reply)
    if st.session_state.get("last_cmd_output") and st.button("Run Reviewer", key="review_cmd_btn"):
        with st.spinner("Reviewing assistant response…"):
            reviewed_text = _review(
                st.session_state["last_cmd_input"], st.session_state["last_cmd_output"]
            )
            st.session_state.last_cmd_reviewed = reviewed_text
    if st.session_state.get("last_cmd_reviewed"):
        reviewed_text = st.session_state["last_cmd_reviewed"]
        render_score(reviewed_text)
        st.subheader("Reviewer Response")
        render_response_with_code(reviewed_text)
        download_buttons(reviewed_text)

with tab2:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    user_input_chat = st.text_area(
        "Ask a question",
        key="chat_input",
        height=200,
        placeholder="Ask about CI/CD, Kubernetes, Terraform, cloud infra, and more…",
    )
    if st.button("Submit", key="chat_button") and user_input_chat.strip():
        with st.spinner("Generating assistant response…"):
            ai_reply = _call(user_input_chat, st.session_state.chat_history)
            st.session_state.last_chat_input = user_input_chat
            st.session_state.last_chat_output = ai_reply
            st.session_state.last_chat_reviewed = None
            st.session_state.chat_history.append({"role": "user", "content": user_input_chat})
            st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})
            st.subheader("Assistant Response")
            render_response_with_code(ai_reply)
            download_buttons(ai_reply)
    if st.session_state.get("last_chat_output") and st.button(
        "Run Reviewer", key="review_chat_btn"
    ):
        with st.spinner("Reviewing assistant response…"):
            st.session_state.last_chat_reviewed = _review(
                st.session_state["last_chat_input"],
                st.session_state["last_chat_output"],
            )
    if st.session_state.get("last_chat_reviewed"):
        reviewed_text = st.session_state["last_chat_reviewed"]
        render_score(reviewed_text)
        st.subheader("Reviewer Response")
        render_response_with_code(reviewed_text)
        download_buttons(reviewed_text)
    if st.button("Reset Chat History"):
        st.session_state.chat_history = []
        st.success("Chat history has been cleared.")
