from __future__ import annotations

import json
from html import escape

import streamlit as st

from fpt_rag.config import Settings
from fpt_rag.llm_client import OpenAICompatibleLlmClient
from fpt_rag.retrieval import HybridRetriever

st.set_page_config(page_title="FPT Curriculum Chat", page_icon=":school:", layout="wide")

st.markdown(
    """
    <style>
      .stApp {
        background:
          radial-gradient(circle at top left, rgba(37, 99, 235, 0.10), transparent 28%),
          radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 24%),
          #0b1020;
      }
      .block-container {
        max-width: 1480px;
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
      }
      .chat-shell {
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 24px;
        background: rgba(15, 23, 42, 0.72);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.22);
        padding: 1rem 1rem 0.25rem 1rem;
      }
      .hero-card {
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 20px;
        padding: 1rem 1.1rem;
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.96));
        margin-bottom: 0.9rem;
      }
      .hero-title {
        font-size: 1.55rem;
        font-weight: 700;
        color: #f8fafc;
      }
      .hero-subtitle {
        margin-top: 0.35rem;
        color: #cbd5e1;
        line-height: 1.45;
      }
      .assistant-bubble {
        border: 1px solid rgba(59, 130, 246, 0.18);
        background: linear-gradient(180deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.96));
        border-radius: 18px;
        padding: 0.9rem 1rem;
      }
      .user-bubble {
        border: 1px solid rgba(16, 185, 129, 0.16);
        background: linear-gradient(180deg, rgba(6, 95, 70, 0.20), rgba(15, 23, 42, 0.95));
        border-radius: 18px;
        padding: 0.9rem 1rem;
      }
      .message-meta {
        font-size: 0.78rem;
        color: #94a3b8;
        margin-bottom: 0.35rem;
        letter-spacing: 0.02em;
        text-transform: uppercase;
      }
      .right-panel {
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 24px;
        background: rgba(15, 23, 42, 0.82);
        padding: 1rem;
        min-height: 75vh;
      }
      .source-chip {
        border: 1px solid rgba(148, 163, 184, 0.14);
        border-radius: 16px;
        background: rgba(30, 41, 59, 0.65);
        padding: 0.7rem 0.8rem;
        margin-bottom: 0.5rem;
      }
      .source-chip-title {
        color: #f8fafc;
        font-weight: 600;
      }
      .source-chip-meta {
        color: #94a3b8;
        font-size: 0.8rem;
        margin-top: 0.25rem;
      }
      .status-card {
        border: 1px solid rgba(148, 163, 184, 0.15);
        border-radius: 16px;
        padding: 0.85rem 0.9rem;
        background: rgba(15, 23, 42, 0.78);
        margin-bottom: 0.7rem;
      }
      .status-label {
        color: #94a3b8;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }
      .status-value {
        color: #f8fafc;
        font-size: 1rem;
        font-weight: 600;
        margin-top: 0.15rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_services() -> tuple[Settings, HybridRetriever, OpenAICompatibleLlmClient]:
    settings = Settings()
    return settings, HybridRetriever(settings), OpenAICompatibleLlmClient(settings)


def source_title(hit) -> str:
    payload = hit.payload
    return payload.get("title_en") or payload.get("course_id") or hit.chunk_id


def source_meta(hit) -> str:
    payload = hit.payload
    return (
        f"course_id={payload.get('course_id', '-')} | "
        f"major={payload.get('major_code', '-')} | "
        f"semester={payload.get('semester', '-')} | "
        f"type={payload.get('chunk_type', '-')} | "
        f"score={hit.score:.4f}"
    )


def render_chat_message(role: str, content: str) -> None:
    bubble_class = "assistant-bubble" if role == "assistant" else "user-bubble"
    label = "Assistant" if role == "assistant" else "You"
    with st.chat_message(role):
        st.markdown(
            f"""
            <div class="{bubble_class}">
              <div class="message-meta">{label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(content)


def compact_history(messages: list[dict[str, object]], limit: int = 6) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for message in messages[-limit:]:
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            compact.append({"role": role, "content": content.strip()})
    return compact


def ensure_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("selected_message_index", None)
    st.session_state.setdefault("composer_prefill", "")


def apply_sample(sample: str) -> None:
    st.session_state["composer_prefill"] = sample


def render_sources_for_message(message: dict[str, object]) -> None:
    response = message.get("response")
    if not isinstance(response, dict):
        st.info("No retrieval metadata for this message yet.")
        return

    parsed_query = response.get("parsed_query", {})
    latency_ms = response.get("latency_ms", 0.0)
    hits = response.get("hits", [])

    st.markdown("### Retrieval")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"""
            <div class="status-card">
              <div class="status-label">Intent</div>
              <div class="status-value">{parsed_query.get('intent_group', '-')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="status-card">
              <div class="status-label">Latency</div>
              <div class="status-value">{float(latency_ms):.1f} ms</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("### Sources")
    if not hits:
        st.warning("No sources retrieved for this turn.")
        return

    selected_idx = st.radio(
        "Selected source",
        options=list(range(len(hits))),
        format_func=lambda idx: f"#{idx + 1} {hits[idx]['title']}",
        label_visibility="collapsed",
        key=f"source_picker_{message.get('id')}",
    )

    for idx, hit in enumerate(hits, start=1):
        st.markdown(
            f"""
            <div class="source-chip">
              <div class="source-chip-title">#{idx} {escape(str(hit['title']))}</div>
              <div class="source-chip-meta">{escape(str(hit['meta']))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    selected = hits[selected_idx]
    st.markdown("### Source Viewer")
    st.caption(selected["meta"])
    st.text_area(
        "Original context",
        value=selected["text"],
        height=300,
        key=f"context_{message.get('id')}_{selected_idx}",
    )
    if selected.get("offering"):
        with st.expander("Offering context", expanded=False):
            st.json(selected["offering"], expanded=False)
    with st.expander("Payload metadata", expanded=False):
        st.json(selected.get("payload", {}), expanded=False)


settings, retriever, llm = get_services()
ensure_state()

sample_queries = [
    "AI ky 4 hoc gi?",
    "Mon AIL303m hoc nganh nao va o ky may?",
    "Machine Learning cua AI co learning outcomes gi?",
    "Tai lieu mon DPL302m la gi?",
    "Schedule cua LAB211 la gi?",
]

left, right = st.columns([1.8, 1.0], gap="large")

with left:
    st.markdown(
        """
        <div class="hero-card">
          <div class="hero-title">FPT Curriculum Chat</div>
          <div class="hero-subtitle">
            Chat with the curriculum knowledge base like a real assistant. The app keeps short-term memory per session,
            so follow-up questions such as "mon do" or "ky do" work more naturally.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="chat-shell">', unsafe_allow_html=True)
        if not st.session_state["messages"]:
            st.markdown(
                """
                <div class="assistant-bubble">
                  <div class="message-meta">Assistant</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                "Ask about curriculum, semester roadmap, syllabus details, materials, assessments, or schedule. "
                "Try a sample below or type your own question."
            )
        else:
            for idx, message in enumerate(st.session_state["messages"]):
                render_chat_message(str(message["role"]), str(message["content"]))
                if message["role"] == "assistant" and message.get("response"):
                    if st.button("View sources", key=f"view_sources_{message['id']}", use_container_width=False):
                        st.session_state["selected_message_index"] = idx
                        st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    cols = st.columns(len(sample_queries))
    for idx, sample in enumerate(sample_queries):
        with cols[idx]:
            if st.button(sample, key=f"sample_{idx}", use_container_width=True):
                apply_sample(sample)
                st.rerun()

    prompt = st.chat_input(
        "Ask about curriculum or syllabus...",
        key="main_chat_input",
    )

    if st.session_state.get("composer_prefill") and not prompt:
        st.info(f"Sample ready: {st.session_state['composer_prefill']}")
        if st.button("Send sample question", key="send_sample_prefill", type="primary"):
            prompt = st.session_state.pop("composer_prefill")

    if prompt:
        st.session_state["composer_prefill"] = ""
        user_id = len(st.session_state["messages"])
        st.session_state["messages"].append(
            {"id": f"user-{user_id}", "role": "user", "content": prompt}
        )

        history = compact_history(st.session_state["messages"][:-1], limit=6)
        response = retriever.search(prompt, top_k=6, history=history)

        with st.chat_message("assistant"):
            st.markdown(
                """
                <div class="assistant-bubble">
                  <div class="message-meta">Assistant</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            chunks: list[str] = []

            def stream_answer():
                for chunk in llm.answer_stream(prompt, response.hits, history=history):
                    chunks.append(chunk)
                    yield chunk

            st.write_stream(stream_answer())
            answer_text = "".join(chunks).strip()

        message_hits = [
            {
                "title": source_title(hit),
                "meta": source_meta(hit),
                "text": hit.text,
                "payload": hit.payload,
                "offering": hit.offering,
            }
            for hit in response.hits
        ]
        st.session_state["messages"].append(
            {
                "id": f"assistant-{user_id}",
                "role": "assistant",
                "content": answer_text or "No answer generated.",
                "response": {
                    "parsed_query": {
                        "intent_group": response.parsed_query.intent_group,
                        "target_index": response.parsed_query.target_index,
                        "filters": response.parsed_query.filters.active_items(),
                    },
                    "latency_ms": response.latency_ms,
                    "hits": message_hits,
                },
            }
        )
        st.session_state["selected_message_index"] = len(st.session_state["messages"]) - 1
        st.rerun()

with right:
    st.markdown('<div class="right-panel">', unsafe_allow_html=True)
    st.markdown("### Session")
    st.markdown(
        f"""
        <div class="status-card">
          <div class="status-label">Short-term memory</div>
          <div class="status-value">Last {min(len(compact_history(st.session_state['messages'])), 6)} turns in prompt window</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="status-card">
          <div class="status-label">Runtime</div>
          <div class="status-value">{settings.llm_model or 'LLM not configured'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Clear conversation", use_container_width=True):
        st.session_state["messages"] = []
        st.session_state["selected_message_index"] = None
        st.session_state["composer_prefill"] = ""
        st.rerun()

    selected_index = st.session_state.get("selected_message_index")
    if isinstance(selected_index, int) and 0 <= selected_index < len(st.session_state["messages"]):
        selected_message = st.session_state["messages"][selected_index]
        render_sources_for_message(selected_message)
        with st.expander("Raw response", expanded=False):
            st.code(json.dumps(selected_message.get("response", {}), ensure_ascii=False, indent=2), language="json")
    else:
        st.info("Send a message, then open sources for any assistant answer from the chat timeline.")

    st.markdown("</div>", unsafe_allow_html=True)
