import streamlit as st
import tempfile
import os
from rag import (
    load_sessions, create_session, delete_session,
    get_session, update_session,
    add_document_to_session, answer_question
)

st.set_page_config(
    page_title="RAG Document Q&A",
    page_icon="📄",
    layout="wide"
)

st.markdown("""
<style>
.source-chip {
    display: inline-block;
    background: #EAF3DE;
    color: #3B6D11;
    padding: 2px 10px;
    border-radius: 99px;
    font-size: 12px;
    margin: 2px;
    border: 1px solid #C0DD97;
}
.session-meta {
    font-size: 11px;
    color: #888;
    margin-top: 2px;
}
</style>
""", unsafe_allow_html=True)

# ---------- Init state ----------
if "active_session" not in st.session_state:
    st.session_state.active_session = None

# ---------- Sidebar ----------
with st.sidebar:
    st.title("📄 RAG Q&A")
    st.markdown("---")

    # New chat button
    if st.button("New Chat", use_container_width=True, type="primary"):
        sid = create_session()
        st.session_state.active_session = sid
        st.rerun()

    st.markdown("---")
    st.markdown("**Chat History**")

    sessions = load_sessions()

    if not sessions:
        st.caption("No chats yet. Click New Chat.")
    else:
        for sid, s in sorted(
            sessions.items(),
            key=lambda x: x[1]["created_at"],
            reverse=True
        ):
            col1, col2 = st.columns([5, 1])
            with col1:
                is_active = st.session_state.active_session == sid
                label = f"{'▶ ' if is_active else ''}{s['name']}"
                if st.button(label, key=f"sess_{sid}", use_container_width=True):
                    st.session_state.active_session = sid
                    st.rerun()
                st.markdown(
                    f'<div class="session-meta">'
                    f'{s["created_at"]} · '
                    f'{len(s.get("documents", []))} docs · '
                    f'{s.get("total_questions", 0)} questions'
                    f'</div>',
                    unsafe_allow_html=True
                )
            with col2:
                if st.button("🗑", key=f"del_{sid}"):
                    delete_session(sid)
                    if st.session_state.active_session == sid:
                        st.session_state.active_session = None
                    st.rerun()

# ---------- Main area ----------
if not st.session_state.active_session:
    st.title("Document Q&A")
    st.info("Click **New Chat** in the sidebar to start.")
    st.stop()

session_id = st.session_state.active_session
session = get_session(session_id)

if not session:
    st.session_state.active_session = None
    st.rerun()

# Header
col1, col2 = st.columns([4, 1])
with col1:
    new_name = st.text_input(
        "Chat name",
        value=session["name"],
        label_visibility="collapsed"
    )
    if new_name != session["name"]:
        update_session(session_id, {"name": new_name})

with col2:
    st.caption(f"Created: {session['created_at']}")

st.markdown("---")

# Two columns: docs + chat
left, right = st.columns([1, 2])

# ---------- Left: Documents ----------
with left:
    st.markdown("**Documents in this chat**")

    docs = session.get("documents", [])
    if not docs:
        st.caption("No documents yet.")
    else:
        for doc in docs:
            with st.container():
                st.markdown(f"📄 **{doc['filename']}**")
                st.caption(
                    f"{doc['pages']} pages · {doc['chunks']} chunks"
                )

    st.markdown("---")
    uploaded = st.file_uploader(
        "Add PDF to this chat",
        type="pdf",
        accept_multiple_files=True
    )

    if uploaded:
        already = [d["filename"] for d in docs]
        new_files = [f for f in uploaded if f.name not in already]

        if new_files:
            for file in new_files:
                with st.spinner(f"Indexing {file.name}..."):
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".pdf"
                    ) as tmp:
                        tmp.write(file.read())
                        tmp_path = tmp.name

                    add_document_to_session(
                        session_id, tmp_path, file.name
                    )
                    os.unlink(tmp_path)

            st.success(f"Added {len(new_files)} document(s)!")
            st.rerun()

    # Stats
    if docs:
        st.markdown("---")
        st.markdown("**Session Stats**")
        total_pages = sum(d["pages"] for d in docs)
        total_chunks = sum(d["chunks"] for d in docs)
        latencies = session.get("latencies", [])
        avg_lat = round(
            sum(latencies) / len(latencies)
        ) if latencies else 0

        c1, c2 = st.columns(2)
        c1.metric("Pages", total_pages)
        c2.metric("Chunks", total_chunks)
        c1.metric("Questions", session.get("total_questions", 0))
        c2.metric("Avg ms", avg_lat)

# ---------- Right: Chat ----------
with right:
    st.markdown("**Chat**")

    history = session.get("chat_history", [])

    if not history:
        if docs:
            st.info(
                f"Ask anything about your "
                f"{len(docs)} document(s)."
            )
        else:
            st.info("Upload documents on the left first.")

    for msg in history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.write(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.write(msg["content"])
                if msg.get("sources"):
                    for src in msg["sources"]:
                        st.markdown(
                            f'<span class="source-chip">'
                            f'📄 {src}</span>',
                            unsafe_allow_html=True
                        )
                if msg.get("latency"):
                    st.caption(f"⚡ {msg['latency']}ms")

    if docs:
        question = st.chat_input(
            f"Ask about your {len(docs)} document(s)..."
        )
        if question:
            with st.chat_message("user"):
                st.write(question)

            with st.chat_message("assistant"):
                with st.spinner("Searching documents..."):
                    answer, sources, latency = answer_question(
                        session_id, question
                    )
                st.write(answer)
                if sources:
                    for src in sources:
                        st.markdown(
                            f'<span class="source-chip">'
                            f'📄 {src}</span>',
                            unsafe_allow_html=True
                        )
                st.caption(f"⚡ {latency}ms")

            st.rerun()