from dotenv import load_dotenv
load_dotenv()

import os
import time
import uuid
import json
import shutil
from datetime import datetime
from langchain_groq import ChatGroq
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_classic.chains import RetrievalQA
from langchain_classic.prompts import PromptTemplate

SESSIONS_FILE = "./sessions.json"
CHROMA_BASE = "./chroma_sessions"

embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model_name="llama-3.3-70b-versatile",
    temperature=0.1
)

PROMPT_TEMPLATE = """You are a helpful document assistant.
Use ONLY the following context from the uploaded documents to answer.
If the answer is not in the context, say "I couldn't find this in the uploaded documents."

Context:
{context}

Question: {question}

Answer:"""

prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=["context", "question"]
)

# ---------- Session management ----------

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sessions(sessions):
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=2)

def create_session(name=None):
    session_id = uuid.uuid4().hex[:8]
    sessions = load_sessions()
    sessions[session_id] = {
        "id": session_id,
        "name": name or f"Chat {len(sessions) + 1}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "documents": [],
        "chat_history": [],
        "chroma_folder": f"{CHROMA_BASE}/{session_id}",
        "total_questions": 0,
        "latencies": []
    }
    save_sessions(sessions)
    return session_id

def delete_session(session_id):
    sessions = load_sessions()
    if session_id in sessions:
        folder = sessions[session_id].get("chroma_folder")
        if folder and os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
        del sessions[session_id]
        save_sessions(sessions)

def get_session(session_id):
    sessions = load_sessions()
    return sessions.get(session_id)

def update_session(session_id, data):
    sessions = load_sessions()
    if session_id in sessions:
        sessions[session_id].update(data)
        save_sessions(sessions)

# ---------- Document indexing ----------

def add_document_to_session(session_id, pdf_path, filename):
    session = get_session(session_id)
    folder = session["chroma_folder"]
    os.makedirs(folder, exist_ok=True)

    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = splitter.split_documents(documents)

    # Filter empty chunks — this is why you get the error
    chunks = [c for c in chunks if c.page_content.strip()]

    if not chunks:
        return len(documents), 0

    for chunk in chunks:
        chunk.metadata["source_file"] = filename

    existing_docs = session.get("documents", [])

    # Process in batches of 50 to avoid memory issues
    BATCH_SIZE = 50

    if existing_docs:
        vectorstore = Chroma(
            persist_directory=folder,
            embedding_function=embeddings
        )
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            vectorstore.add_documents(batch)
    else:
        # First document — create from first batch
        first_batch = chunks[:BATCH_SIZE]
        vectorstore = Chroma.from_documents(
            documents=first_batch,
            embedding=embeddings,
            persist_directory=folder
        )
        # Add remaining batches
        for i in range(BATCH_SIZE, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            vectorstore.add_documents(batch)

    docs = existing_docs.copy()
    docs.append({
        "filename": filename,
        "pages": len(documents),
        "chunks": len(chunks)
    })
    update_session(session_id, {"documents": docs})

    return len(documents), len(chunks)


def load_session_vectorstore(session_id):
    session = get_session(session_id)
    folder = session["chroma_folder"]
    if not os.path.exists(folder):
        return None
    return Chroma(
        persist_directory=folder,
        embedding_function=embeddings
    )

# ---------- Q&A ----------

from langchain_classic.memory import ConversationBufferWindowMemory
from langchain_classic.chains import ConversationalRetrievalChain

def answer_question(session_id, question):
    vectorstore = load_session_vectorstore(session_id)
    if not vectorstore:
        return "No documents uploaded yet.", [], 0

    start = time.time()

    # Build memory from existing chat history
    session = get_session(session_id)
    history = session.get("chat_history", [])

    memory = ConversationBufferWindowMemory(
        memory_key="chat_history",
        return_messages=True,
        output_key="answer",
        k=10  # remember last 10 exchanges
    )

    # Load previous messages into memory
    for i in range(0, len(history) - 1, 2):
        if i + 1 < len(history):
            memory.chat_memory.add_user_message(history[i]["content"])
            memory.chat_memory.add_ai_message(history[i + 1]["content"])

    # Conversational chain with memory
    qa_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(search_kwargs={"k": 4}),
        memory=memory,
        return_source_documents=True,
        verbose=False
    )

    result = qa_chain.invoke({"question": question})
    latency = round((time.time() - start) * 1000)

    answer = result["answer"]
    sources = list(set([
        f"{doc.metadata.get('source_file', 'Doc')} — Page {doc.metadata.get('page', 0) + 1}"
        for doc in result["source_documents"]
    ]))

    # Save to history
    history.append({"role": "user", "content": question})
    history.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "latency": latency
    })

    latencies = session.get("latencies", [])
    latencies.append(latency)

    update_session(session_id, {
        "chat_history": history,
        "total_questions": session.get("total_questions", 0) + 1,
        "latencies": latencies
    })

    return answer, sources, latency

