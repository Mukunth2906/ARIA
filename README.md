# 🔐 ARIA: Autonomous Response & Inbox Assistant

> **Enterprise-grade, verification-gated AI executive assistant for Google Workspace (Gmail & Calendar) built with LangGraph, FastAPI, and Streamlit.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.0-blue.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35.0-FF4B4B.svg?style=flat&logo=streamlit)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat&logo=python)](https://www.python.org)

ARIA is not a simple auto-sending email bot. It is an **agentic workflow assistant** engineered around **safety gates, human-in-the-loop verification, and adaptive profile memory**. Every outbound action passes through an orchestrated verification pipeline before anything reaches the Google Workspace APIs.

---

## 🚀 Key Features

- **🛡️ 6-Gate Verification Chain**:
  1. **Confidence Gate**: Ambiguity detection (threshold ≥ 0.60). Automatically triggers selective RAG to disambiguate or requests clarification.
  2. **Recipient Validation**: Format check, disposable domain blocklist, and intent matching.
  3. **PII Scanner**: Scans for passwords, API tokens, financial cards, SSN/Aadhaar/PAN, and server credentials.
  4. **Content Policy**: Blocks harassment, abusive language, spam patterns, and tone mismatches.
  5. **Risk Scorer**: Evaluates action reversibility, content sensitivity, and recipient risk (LOW / MEDIUM / HIGH).
  6. **Human-in-the-Loop Gate**: Pauses execution using LangGraph state interrupts (`interrupt_before=["human_confirm"]`), providing a live draft preview with full options to **Confirm & Send**, **Edit & Re-verify**, or **Cancel**.
- **🧠 Continuous Memory & Profile Adaptation**:
  - Dynamically learns user habits, top contacts, calendar constraints, and preferences.
  - Rewrites affected profile sections in under 3 present-tense sentences to prevent token bloat.
  - Primary storage in MongoDB Atlas with seamless offline fallback to local JSON.
- **⚡ Optimized Inference**:
  - Consolidated architecture that requires only **4 LLM calls per email action** (down from 7).
  - Flexible multi-provider support: GitHub Models (`openai/gpt-4.1`), Google Gemini (`gemini-1.5-flash`), or OpenAI (`gpt-4o-mini`).
- **📋 Immutable Audit Logging**:
  - Unconditionally records all actions (`SENT`, `BLOCKED`, `CANCELLED_BY_USER`, `CLARIFICATION_REQUESTED`) to an append-only audit trail (`aria_audit.jsonl`).

---

## 🏗️ Architecture & Workflow

```mermaid
flowchart TD
    User([User Request]) --> Loader[profile_loader\nLoads user preferences & habits]
    Loader --> Intent[parse_intent\nClassifies intent & extracts entities]
    Intent --> Conf{Confidence Router\nThreshold >= 0.60?}

    Conf -- "< 0.60 (Attempts < 2)" --> RAG[selective_rag\nChromaDB context lookup]
    RAG --> Intent
    Conf -- "< 0.60 (Attempts >= 2)" --> Clarify[ask_clarify\nAsk user for clarification]
    Clarify --> Audit[audit_log]

    Conf -- ">= 0.60" --> Scanner[security_scanner\nLocal syntax + PII + Policy + Risk]
    Scanner -- "Blocked" --> Audit
    Scanner -- "Passed" --> Drafter[draft_email\nPolishes tone & clarity]

    Drafter --> HumanConfirm{human_confirm\n★ LangGraph Interrupt ★}
    HumanConfirm -- "User Cancels" --> Audit
    HumanConfirm -- "User Edits" --> Scanner
    HumanConfirm -- "User Confirms" --> FinalSafety{final_safety_check\nDeterministic gate checks}

    FinalSafety -- "Checks Failed" --> Audit
    FinalSafety -- "Cleared" --> Execute[execute_send\nSends via Gmail API]
    Execute --> Audit

    Audit --> Updater[profile_updater\nLearns new facts & updates DB]
    Updater --> EndNode([Session Complete])
```

---

## 📁 Repository Structure

```
ARIA/
├── backend/
│   ├── graph.py                    # LangGraph StateGraph builder, nodes, and conditional edges
│   ├── main.py                     # FastAPI REST API (endpoints: /api/chat, /api/confirm, /api/edit, etc.)
│   ├── state.py                    # AgentState TypedDict (single source of truth for graph data)
│   ├── nodes/
│   │   ├── audit.py                # Immutable JSONL audit logger (aria_audit.jsonl)
│   │   ├── confidence.py           # Threshold router (proceed / RAG / clarify)
│   │   ├── draft_email.py          # LLM email drafting and polishing
│   │   ├── executor.py             # Calls Gmail API send_email()
│   │   ├── intent.py               # Combined intent parser + entity extractor
│   │   ├── profile.py              # Profile loader and session updater nodes
│   │   ├── rag.py                  # ChromaDB lazy-loaded vector store lookup
│   │   └── verification/
│   │       ├── security_scanner.py # Combined PII + Policy + Risk scanner
│   │       ├── human_confirm.py    # Passthrough interrupt target for UI confirmation
│   │       ├── final_safety.py     # Deterministic sanity checks before send
│   │       ├── recipient_validator.py
│   │       ├── pii_scanner.py
│   │       ├── content_policy.py
│   │       └── risk_scorer.py
│   ├── profile/
│   │   ├── schema.py               # UserProfile dataclass & serialization
│   │   ├── summarizer.py           # Builds [PERSONAL CONTEXT] bundle for prompts
│   │   └── updater.py              # Session observation extractor & section rewriter
│   └── utils/
│       ├── calendar_client.py      # Google Calendar API (list events, create events)
│       ├── db.py                   # MongoDB Atlas client with local JSON fallback
│       ├── display.py              # Colorama terminal status visualizer for CLI
│       ├── gmail_client.py         # Gmail API (list inbox, send email)
│       ├── llm.py                  # Flexible LLM provider setup (GitHub Models / Gemini / OpenAI)
│       └── token_manager.py        # Google OAuth 2.0 credentials & token refresh
├── frontend/
│   └── app.py                      # Streamlit UI (dual-column chat + verification cards + audit)
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
└── README.md                       # Project documentation
```

---

## 🛠️ Quickstart

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Mukunth2906/ARIA.git
cd ARIA
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Add your preferred API key (choose at least one):
- `GITHUB_TOKEN`: Free GitHub Personal Access Token ([GitHub Settings](https://github.com/settings/tokens))
- `GEMINI_API_KEY`: Google Gemini Key ([Google AI Studio](https://aistudio.google.com/app/apikey))
- `OPENAI_API_KEY`: OpenAI API Key ([OpenAI Platform](https://platform.openai.com/api-keys))

*(Optional: Set `MONGO_URI` if connecting to MongoDB Atlas. If omitted, profiles are stored locally in `profiles/`.)*

### 3. Run the Application

#### Start the FastAPI Backend (Port 8001):
```bash
python -m uvicorn backend.main:app --reload --port 8001
```

#### Start the Streamlit Frontend:
```bash
streamlit run frontend/app.py
```

Open `http://localhost:8501` to access the interactive ARIA dashboard.

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
