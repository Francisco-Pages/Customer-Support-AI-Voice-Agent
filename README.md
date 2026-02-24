# HVAC Voice AI Customer Support Agent

> An AI-powered voice agent that handles inbound and outbound customer support calls for HVAC products using Twilio, LiveKit, GPT-4o, and RAG.

---

## Table of Contents

1. [Product Requirements Document (PRD)](#1-product-requirements-document-prd)
2. [Architecture Specification](#2-architecture-specification)
3. [Design Document](#3-design-document)
4. [User Stories](#4-user-stories)

---

## 1. Product Requirements Document (PRD)

### 1.1 Overview

This document defines the requirements for an AI-powered voice customer support agent designed to handle inbound and outbound phone calls for an HVAC product company. The agent will leverage large language models (LLMs), retrieval-augmented generation (RAG), and tool integrations to deliver accurate, responsive, and human-like support experiences at scale.

### 1.2 Problem Statement

HVAC customers frequently need support for product troubleshooting, warranty inquiries, parts availability, and scheduling service appointments. Traditional call centers are expensive to scale, inconsistent in quality, and unavailable 24/7. An AI voice agent can handle a large volume of routine calls, reduce wait times, and escalate complex cases to human agents — improving customer satisfaction while reducing operational cost.

### 1.3 Goals

- Handle inbound customer support calls autonomously for common HVAC support scenarios
- Execute outbound calls for appointment reminders, maintenance follow-ups, and warranty notifications
- Provide accurate answers grounded in the product knowledge base via RAG
- Execute tools (scheduling, warranty lookup, parts check, escalation) in real time during calls
- Identify repeat callers and personalize responses using stored customer data
- Escalate safety-critical situations immediately with hardcoded responses
- Maintain a full audit trail of calls, transcripts, and outcomes

### 1.4 Non-Goals

- The agent will not replace human agents for complex technical repairs or legal disputes
- The agent will not handle video or chat — voice only in v1
- The agent will not process payments directly (can transfer to secure IVR)

### 1.5 Success Metrics

| Metric | Target |
|---|---|
| Call containment rate (resolved without human) | >= 70% |
| Average handle time | <= 4 minutes |
| Customer satisfaction score (post-call SMS survey) | >= 4.0 / 5.0 |
| First call resolution rate | >= 65% |
| Agent response latency (end of caller utterance to agent speech) | <= 1.5 seconds |
| Uptime | >= 99.9% |

### 1.6 Functional Requirements

#### 1.6.1 Inbound Calls
- FR-01: The system must accept inbound calls via Twilio phone number and route audio to the LiveKit agent pipeline
- FR-02: The agent must greet callers by name if their phone number matches an existing customer record
- FR-03: The agent must understand natural language requests and map them to one of: RAG query, tool call, or escalation
- FR-04: The agent must provide answers grounded in the HVAC product knowledge base using RAG
- FR-05: The agent must execute tool calls (scheduling, warranty, parts, escalation) during the call
- FR-06: The agent must detect and respond to safety-critical keywords (gas leak, carbon monoxide, fire, electrical hazard) with a hardcoded emergency response
- FR-07: The agent must offer to transfer to a human agent at any point upon request
- FR-08: The agent must handle caller interruptions and barge-ins gracefully

#### 1.6.2 Outbound Calls
- FR-09: The system must initiate outbound calls via Twilio based on scheduled triggers or manual dispatch
- FR-10: Outbound calls must only be placed to customers with documented TCPA consent on file
- FR-11: Outbound call types: appointment reminders, maintenance follow-ups, warranty expiration alerts
- FR-12: The agent must handle voicemail detection and leave a structured voicemail message
- FR-13: Outbound call outcomes (answered, voicemail, no answer, declined) must be logged

#### 1.6.3 RAG & Knowledge Base
- FR-14: The agent must query the vector database for relevant context before generating a response to product-related questions
- FR-15: RAG queries must be filtered by relevant metadata (product category, document type) before vector search
- FR-16: Retrieved context must be ranked by relevance and top-k results injected into the LLM prompt
- FR-17: Frequently asked questions must be cached to reduce vector DB query latency

#### 1.6.4 Data & Persistence
- FR-18: All calls must be logged with: caller ID, timestamp, duration, transcript, resolution status, and agent actions taken
- FR-19: Customer records must include: name, phone number, address, products registered, service history, TCPA consent status
- FR-20: Conversation summaries must be stored and surfaced to the agent on repeat calls

### 1.7 Non-Functional Requirements

- NFR-01: Agent response latency must not exceed 1.5 seconds under normal operating conditions
- NFR-02: The system must support at least 50 concurrent calls
- NFR-03: All data at rest must be encrypted (AES-256); all data in transit must use TLS 1.2+
- NFR-04: The system must be deployable via Docker and support horizontal scaling
- NFR-05: Twilio webhook endpoints must respond within 5 seconds or Twilio will timeout
- NFR-06: The system must log all LLM inputs and outputs for audit and debugging

### 1.8 Constraints & Assumptions

- Callers are English-speaking (multilingual support is out of scope for v1)
- The existing vector database is already populated with HVAC product documentation
- TCPA consent is collected and stored externally before outbound campaigns are triggered
- Human agent transfer is handled via Twilio's `<Dial>` verb or SIP transfer

---

## 2. Architecture Specification

### 2.1 System Overview

```
                          ┌─────────────────────────────────────┐
                          │            PSTN / Caller             │
                          └──────────────┬──────────────────────┘
                                         │ Voice Call
                          ┌──────────────▼──────────────────────┐
                          │              Twilio                  │
                          │  (Call control, audio streaming,     │
                          │   outbound dialing, TwiML routing)   │
                          └──────────────┬──────────────────────┘
                                         │ WebSocket (Media Stream)
                          ┌──────────────▼──────────────────────┐
                          │           FastAPI App               │
                          │  - /inbound  (TwiML webhook)        │
                          │  - /outbound (trigger endpoint)     │
                          │  - /stream   (WebSocket handler)    │
                          └──────────────┬──────────────────────┘
                                         │
                          ┌──────────────▼──────────────────────┐
                          │         LiveKit Agent Pipeline      │
                          │                                     │
                          │  STT (Deepgram/Whisper)             │
                          │       ↓                             │
                          │  Agent Core (GPT-4o)                │
                          │       ↓                             │
                          │  TTS (ElevenLabs/OpenAI TTS)        │
                          └──┬──────────────┬───────────────────┘
                             │              │
              ┌──────────────▼──┐     ┌─────▼───────────────────┐
              │   Tool Runner   │     │      RAG Retriever       │
              │                 │     │                          │
              │ - Scheduling    │     │  Vector DB Query         │
              │ - Warranty      │     │  Metadata Filtering      │
              │ - Parts Lookup  │     │  Context Ranking         │
              │ - Escalation    │     │  Query Cache             │
              └──────┬──────────┘     └─────┬────────────────────┘
                     │                      │
        ┌────────────▼──────────────────────▼────────────────────┐
        │                    Data Layer                          │
        │                                                        │
        │   PostgreSQL (SQL)            Vector Database          │
        │   - customers                 - product docs           │
        │   - calls                     - troubleshooting guides │
        │   - appointments              - FAQs                   │
        │   - consent_records           - installation manuals   │
        │   - call_summaries            - parts catalogs         │
        └────────────────────────────────────────────────────────┘
```

### 2.2 Component Breakdown

#### 2.2.1 Telephony Layer (Twilio)
- Receives inbound PSTN calls and responds with TwiML to open a Media Stream WebSocket
- Initiates outbound calls via Twilio REST API with pre-validated TCPA-consented numbers
- Handles call transfer (`<Dial>`), hold music, and voicemail detection (AMD)
- Webhooks: `/inbound` (call start), `/status` (call events), `/recording` (if recording enabled)

#### 2.2.2 API Layer (FastAPI)
- Stateless webhook handler for Twilio events
- WebSocket endpoint `/stream` bridges Twilio audio to LiveKit
- REST endpoints for outbound call dispatch, admin operations, and health checks
- Authentication: API key for internal services, Twilio signature validation for webhooks

#### 2.2.3 Voice AI Pipeline (LiveKit Agents SDK)
- **STT**: Deepgram Nova-2 (optimized for telephony, low latency) or OpenAI Whisper
- **LLM**: GPT-4o with function calling enabled
- **TTS**: OpenAI TTS (`tts-1`) or ElevenLabs for more natural voice
- **VAD**: Silero VAD for detecting end-of-utterance on noisy phone audio
- **Turn management**: Handles interruptions, barge-in, and silence timeouts

#### 2.2.4 Agent Core (GPT-4o)
- Stateful conversation with a rolling context window
- System prompt encodes: persona, HVAC domain knowledge boundaries, tool use rules, safety overrides
- Safety layer runs before LLM: keyword matching for emergency triggers
- Tool calls are executed synchronously with optimistic "hold" phrases to mask latency
- Conversation summary is prepended to context window on repeat callers

#### 2.2.5 RAG Retriever
- On each product-related query: construct search string → apply metadata filters → vector search → rerank → inject top-k into prompt
- Metadata filters: `product_category`, `doc_type` (manual, faq, troubleshooting, warranty), `brand`
- Cache layer (Redis or in-memory): TTL-based caching of frequent query results
- Fallback: if no relevant context found above confidence threshold, agent acknowledges limitation and offers escalation

#### 2.2.6 Tool Runner
- Tools are registered as OpenAI function definitions and called by the LLM
- Each tool call is validated, executed, and its result returned to the LLM within the same turn
- Tools run with a hard timeout (3 seconds); timeout triggers a graceful fallback response

| Tool | Description | Data Source |
|---|---|---|
| `lookup_customer` | Fetch customer record by phone number | PostgreSQL |
| `lookup_warranty` | Check warranty status by serial number | PostgreSQL |
| `check_parts_availability` | Query parts inventory | PostgreSQL / ERP API |
| `create_appointment` | Schedule a service appointment | PostgreSQL / Calendar API |
| `update_appointment` | Modify or cancel an appointment | PostgreSQL / Calendar API |
| `get_call_history` | Retrieve prior call summaries for caller | PostgreSQL |
| `transfer_to_agent` | Trigger Twilio call transfer to human | Twilio API |
| `send_followup_sms` | Send post-call SMS to caller | Twilio Messaging API |

#### 2.2.7 Data Layer

**PostgreSQL Schema (core tables)**

```sql
-- Customers
customers (
  id            UUID PRIMARY KEY,
  phone_e164    VARCHAR(20) UNIQUE NOT NULL,
  name          VARCHAR(255),
  email         VARCHAR(255),
  address       TEXT,
  tcpa_consent  BOOLEAN DEFAULT FALSE,
  consent_date  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT NOW()
)

-- Registered products per customer
customer_products (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  product_model  VARCHAR(100),
  serial_number  VARCHAR(100) UNIQUE,
  install_date   DATE,
  warranty_expiry DATE
)

-- Call records
calls (
  id              UUID PRIMARY KEY,
  customer_id     UUID REFERENCES customers(id),
  direction       VARCHAR(10),  -- 'inbound' | 'outbound'
  twilio_call_sid VARCHAR(100) UNIQUE,
  started_at      TIMESTAMPTZ,
  ended_at        TIMESTAMPTZ,
  duration_sec    INTEGER,
  resolution      VARCHAR(50),  -- 'resolved' | 'escalated' | 'voicemail' | 'no_answer'
  transcript      TEXT,
  summary         TEXT
)

-- Appointments
appointments (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  call_id        UUID REFERENCES calls(id),
  scheduled_at   TIMESTAMPTZ,
  service_type   VARCHAR(100),
  status         VARCHAR(50),  -- 'scheduled' | 'confirmed' | 'completed' | 'cancelled'
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
)

-- Outbound campaign queue
outbound_queue (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  campaign_type  VARCHAR(50),  -- 'reminder' | 'followup' | 'warranty_alert'
  scheduled_at   TIMESTAMPTZ,
  status         VARCHAR(50),  -- 'pending' | 'dispatched' | 'completed' | 'failed'
  payload        JSONB,
  created_at     TIMESTAMPTZ DEFAULT NOW()
)
```

### 2.3 Data Flow: Inbound Call

```
1. Caller dials Twilio number
2. Twilio POSTs to /inbound → FastAPI returns TwiML <Stream> pointing to /stream WebSocket
3. FastAPI opens LiveKit session; Twilio streams μ-law audio over WebSocket
4. LiveKit STT transcribes audio in real time
5. VAD detects end of utterance → transcript sent to Agent Core
6. Safety layer checks for emergency keywords → if triggered, hardcoded response returned
7. Agent Core queries PostgreSQL for customer record (by caller phone number)
8. If product/knowledge question: RAG Retriever queries vector DB, injects context into prompt
9. GPT-4o generates response (with tool calls if needed)
10. Tool Runner executes tool calls → results returned to GPT-4o for final response
11. TTS converts response text to audio → streamed back through LiveKit → Twilio → caller
12. Loop until call ends or transfer triggered
13. On call end: transcript saved, summary generated, call record written to PostgreSQL
```

### 2.4 Data Flow: Outbound Call

```
1. Scheduler or admin triggers outbound job (reads from outbound_queue)
2. System validates TCPA consent for target customer
3. FastAPI calls Twilio REST API to initiate outbound call with /outbound webhook URL
4. On answer: same LiveKit pipeline as inbound, with outbound-specific system prompt
5. AMD (Answering Machine Detection): if voicemail, play recorded message and hang up
6. Call outcome logged to calls table; outbound_queue record updated
```

### 2.5 Deployment Architecture

```
┌─────────────────────────────────────────────┐
│               Cloud Provider                │
│                                             │
│  ┌─────────────┐    ┌─────────────────────┐ │
│  │  App Server │    │   LiveKit Server    │ │
│  │  (FastAPI)  │◄──►│  (self-hosted or   │ │
│  │  Docker     │    │   LiveKit Cloud)    │ │
│  └──────┬──────┘    └─────────────────────┘ │
│         │                                   │
│  ┌──────▼──────┐    ┌─────────────────────┐ │
│  │ PostgreSQL  │    │    Redis Cache      │ │
│  │ (managed)   │    │    (RAG cache,      │ │
│  └─────────────┘    │     sessions)       │ │
│                     └─────────────────────┘ │
└─────────────────────────────────────────────┘
```

- Containerized with Docker; orchestrated with Docker Compose (dev) or Kubernetes (prod)
- LiveKit: use LiveKit Cloud for v1, migrate to self-hosted for cost control at scale
- PostgreSQL: managed instance (RDS, Cloud SQL, or Supabase)
- Secrets: environment variables via `.env`; production secrets via cloud secrets manager

---

## 3. Design Document

### 3.1 Agent Persona & Voice Design

**Persona**: The agent presents as "Alex," a knowledgeable and friendly HVAC support specialist.

- Tone: professional, calm, empathetic — never robotic or overly formal
- Speech pacing: moderate, with natural pauses after questions
- Acknowledgment phrases: used while processing ("Let me look that up for you", "One moment") to mask tool/RAG latency
- Does not claim to be human if sincerely asked; acknowledges it is an automated assistant

### 3.2 System Prompt Design

The system prompt is structured in layers:

```
[IDENTITY]
You are Alex, an AI customer support agent for [Company Name], an HVAC product company.
You help customers with product questions, troubleshooting, warranty inquiries,
parts availability, and service scheduling.

[BEHAVIOR RULES]
- Always greet the caller by name if known.
- Be concise. Phone callers do not want long monologues.
- Ask one question at a time.
- If you do not know the answer, say so and offer to escalate.
- Never speculate about safety-critical issues. Refer to emergency services immediately.
- Do not discuss topics unrelated to HVAC products or customer service.

[SAFETY OVERRIDE]
If the caller mentions: gas leak, carbon monoxide, CO detector, fire, electrical hazard,
smoke, explosion — immediately respond with:
"This sounds like an emergency. Please hang up and call 911 immediately.
Do not attempt to operate any equipment."

[CONTEXT]
Customer record: {customer_context}
Prior call summary: {prior_summary}
Retrieved knowledge: {rag_context}

[TOOLS]
You have access to the following tools: {tool_list}
Use tools proactively when customer needs require it. Always confirm before scheduling.
```

### 3.3 Conversation Flow Design

#### 3.3.1 Inbound Call Flow

```
CALL START
    │
    ▼
Lookup caller by phone number
    │
    ├── Known caller ──► "Hi [Name], welcome back to [Company] support. How can I help you today?"
    │
    └── Unknown caller ► "Thank you for calling [Company] HVAC support. I'm Alex.
                          May I have your name and the best number to reach you?"
    │
    ▼
Classify intent
    │
    ├── Troubleshooting ──► RAG query → diagnose → recommend action → offer appointment
    │
    ├── Warranty inquiry ► lookup_warranty tool → relay status → offer escalation if disputed
    │
    ├── Parts question ──► check_parts_availability tool → relay availability / ETA
    │
    ├── Schedule service ► create_appointment tool → confirm details → send SMS confirmation
    │
    ├── Billing/Payment ► Transfer to human (out of AI scope)
    │
    ├── Emergency ───────► Hardcoded emergency response (no LLM)
    │
    └── Other ───────────► Attempt to help or escalate
    │
    ▼
Resolution
    │
    ├── Resolved ──► "Is there anything else I can help you with?" → close call → post-call SMS
    │
    └── Escalated ► "I'm going to connect you with one of our specialists." → Twilio transfer
    │
    ▼
Post-call
    Save transcript, generate summary, log to PostgreSQL
```

#### 3.3.2 Outbound Call Flow

```
CALL INITIATED
    │
    ▼
Answering Machine Detection (AMD)
    │
    ├── Human answered ──► Personalized greeting → deliver campaign message → handle questions
    │
    └── Voicemail ───────► Play pre-recorded message → hang up → log outcome
    │
    ▼
Campaign types:
    - Appointment reminder: confirm/cancel/reschedule
    - Maintenance follow-up: check satisfaction, offer next service
    - Warranty expiration: inform customer, offer renewal or upgrade
    │
    ▼
Log outcome → update outbound_queue
```

### 3.4 RAG Pipeline Design

```
User utterance
    │
    ▼
Intent classifier (LLM or rule-based)
    │
    ├── Is this a knowledge question? ──► YES ──► Continue
    │                                    NO  ──► Skip RAG, go straight to tool/response
    ▼
Query construction
    - Extract key entities: product model, symptom, part name
    - Apply metadata filters: doc_type, product_category
    │
    ▼
Vector search (top-10 candidates)
    │
    ▼
Reranking (cross-encoder or LLM-based)
    - Select top-3 most relevant chunks
    │
    ▼
Cache check
    - Hash the query → check Redis cache → return cached result if hit
    │
    ▼
Inject into LLM prompt as [CONTEXT]
```

### 3.5 Latency Budget

| Stage | Target Latency |
|---|---|
| Twilio audio → LiveKit STT | 100–200ms |
| VAD (end-of-utterance detection) | 300–500ms |
| Safety keyword check | <5ms |
| Customer DB lookup | <50ms |
| RAG query (cache miss) | 200–400ms |
| RAG query (cache hit) | <20ms |
| GPT-4o inference | 400–800ms |
| Tool execution | <500ms per tool |
| TTS generation (first audio chunk) | 200–400ms |
| **Total (no tool call)** | **~1.2–1.8s** |
| **Total (with one tool call)** | **~1.7–2.3s** |

### 3.6 Safety & Error Handling

| Scenario | Handling |
|---|---|
| Emergency keyword detected | Hardcoded response; bypass LLM entirely |
| RAG returns no confident results | Agent acknowledges gap, offers escalation |
| Tool call times out (>3s) | Agent says "I'm having trouble accessing that right now" and offers callback |
| LLM call fails | Fallback to scripted response; log error; offer to transfer |
| Call drops mid-conversation | Save partial transcript; mark call as incomplete |
| Caller silent for >10 seconds | Agent prompts once; second silence triggers polite close |
| Caller abusive/threatening | Warn once; transfer to human or end call |
| Max turns exceeded (>20 turns) | Agent proactively offers escalation |

### 3.7 Security Design

- Twilio webhook signature validation on every inbound request (X-Twilio-Signature header)
- No PII logged in plaintext application logs; structured logs reference UUIDs only
- All API keys and credentials stored in environment variables; never hardcoded
- Database access via parameterized queries only (no raw string interpolation)
- Customer phone numbers stored in E.164 format; hashed for cache keys
- TCPA consent check is a hard gate in outbound call initiation — no consent = no call
- Role-based access for any admin endpoints

---

## 4. User Stories

### 4.1 Inbound Customer Stories

---

**US-001 — First-time caller greeting**
> As a first-time caller, I want the agent to ask for my name and contact information so that my details can be saved for future calls.

**Acceptance Criteria:**
- Agent greets caller without using a name it does not have
- Agent asks for name and phone number if not already on file
- Customer record is created in PostgreSQL after the call

---

**US-002 — Returning caller recognition**
> As a returning customer, I want the agent to recognize me by my phone number and greet me by name so that I don't have to repeat my information.

**Acceptance Criteria:**
- Agent looks up phone number at call start
- If found, agent greets caller by name within the opening line
- Prior call summary is available to the agent as context

---

**US-003 — Product troubleshooting**
> As a customer whose HVAC unit is not cooling, I want the agent to walk me through troubleshooting steps so that I can resolve the issue without scheduling a technician.

**Acceptance Criteria:**
- Agent queries vector DB for relevant troubleshooting guide
- Agent presents steps in plain, spoken language (not bullet points)
- If issue cannot be resolved, agent offers to schedule a service appointment
- If safety risk is identified, agent immediately escalates

---

**US-004 — Warranty status inquiry**
> As a customer, I want to know whether my HVAC unit is still under warranty so that I know if a repair will be covered.

**Acceptance Criteria:**
- Agent calls `lookup_warranty` with customer's serial number
- Agent clearly states warranty status (active, expired, or not found)
- If expired, agent offers relevant service plan options or transfer to sales

---

**US-005 — Parts availability check**
> As a customer attempting a DIY repair, I want to know if a specific replacement part is in stock so that I can decide whether to order it or hire a technician.

**Acceptance Criteria:**
- Agent identifies the part from the customer's description or model number
- Agent calls `check_parts_availability` and relays result
- If in stock, agent provides estimated delivery timeframe or directs to ordering

---

**US-006 — Service appointment scheduling**
> As a customer, I want to schedule a service appointment over the phone so that a technician can come out and inspect my unit.

**Acceptance Criteria:**
- Agent collects: preferred date/time range, service address, issue description
- Agent calls `create_appointment` and confirms the booking
- Agent sends an SMS confirmation to the caller's number after the call
- Appointment is visible in PostgreSQL

---

**US-007 — Appointment rescheduling**
> As a customer, I want to reschedule an existing appointment so that it fits my updated availability.

**Acceptance Criteria:**
- Agent looks up existing appointment by customer ID
- Agent confirms current appointment details before making changes
- Agent calls `update_appointment` with new date/time
- Confirmation SMS is sent with updated appointment details

---

**US-008 — Emergency safety situation**
> As a customer who smells gas near their HVAC unit, I want the agent to immediately direct me to emergency services so that I am not harmed.

**Acceptance Criteria:**
- Safety layer detects keyword ("gas leak", "smell gas", "CO", "carbon monoxide", etc.)
- LLM is bypassed entirely
- Agent delivers hardcoded emergency response directing caller to call 911
- Call is flagged in logs as safety event

---

**US-009 — Human agent transfer request**
> As a customer with a complex billing dispute, I want to be transferred to a human agent so that my issue can be resolved properly.

**Acceptance Criteria:**
- Agent recognizes transfer request (explicit or implicit, e.g., "talk to a person")
- Agent acknowledges and explains the transfer
- Agent calls `transfer_to_agent` tool; Twilio executes the call transfer
- Partial transcript is logged before transfer completes

---

**US-010 — Unresolvable question escalation**
> As a customer asking a question the agent cannot answer from the knowledge base, I want the agent to acknowledge its limitation and offer alternatives so that I am not given incorrect information.

**Acceptance Criteria:**
- If RAG returns no confident result, agent does not hallucinate an answer
- Agent says it is unable to find that information and offers: escalation, callback, or email follow-up
- Interaction is logged with resolution = "unresolved" for review

---

### 4.2 Outbound Call Stories

---

**US-011 — Appointment reminder call**
> As a customer with an upcoming service appointment, I want to receive a reminder call so that I don't miss the appointment.

**Acceptance Criteria:**
- Outbound call is triggered 24 hours before scheduled appointment
- Agent identifies itself and states the appointment details
- Customer can confirm, reschedule, or cancel via voice response
- Outcome is logged and appointment record updated accordingly

---

**US-012 — TCPA consent enforcement**
> As a compliance officer, I want to ensure that outbound calls are only placed to customers who have given TCPA consent so that the company does not violate federal regulations.

**Acceptance Criteria:**
- Outbound call initiation always checks `tcpa_consent = TRUE` in customer record
- If consent is missing or revoked, the call is not placed and the queue record is marked "blocked — no consent"
- No exceptions or bypasses exist in the code path

---

**US-013 — Voicemail handling**
> As a customer who missed an outbound call, I want the agent to leave a professional voicemail so that I know the reason for the call.

**Acceptance Criteria:**
- Twilio AMD detects voicemail/answering machine
- Agent plays a pre-scripted voicemail message (not LLM-generated)
- Message includes company name, reason for call, and callback number
- Outcome logged as "voicemail"

---

**US-014 — Warranty expiration alert**
> As a customer whose warranty is expiring within 30 days, I want to receive a proactive call so that I can decide whether to purchase an extended warranty or service plan.

**Acceptance Criteria:**
- Scheduler identifies customers with `warranty_expiry` within 30 days
- Outbound call is queued with campaign_type = 'warranty_alert'
- Agent informs customer of expiration date and offers options
- Outcome and any customer responses are logged

---

### 4.3 Administrative Stories

---

**US-015 — Call record audit**
> As an operations manager, I want to review complete call records including transcripts and summaries so that I can monitor agent quality and resolve disputes.

**Acceptance Criteria:**
- Every call has a record in the `calls` table with transcript and summary
- Records are queryable by date range, customer, resolution status
- No PII is exposed in logs outside of the secured database

---

**US-016 — Outbound campaign dispatch**
> As an operations manager, I want to trigger an outbound call campaign for a list of customers so that I can notify them about a product recall or service bulletin.

**Acceptance Criteria:**
- Admin endpoint accepts a list of customer IDs and campaign type
- Records are inserted into `outbound_queue` with scheduled time
- System validates TCPA consent for each record before enqueueing
- Campaign status is trackable via status field on each queue record

---

**US-017 — Knowledge base currency**
> As a product manager, I want the RAG knowledge base to reflect current product documentation so that the agent does not give outdated answers.

**Acceptance Criteria:**
- A documented process exists for adding/updating documents in the vector DB
- New documents are chunked, embedded, and stored with correct metadata
- Agent uses the most recently ingested version of a document when multiple versions exist

---

## 5. Tech Stack Summary

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API Framework | FastAPI |
| Voice Platform | LiveKit Agents SDK |
| Telephony | Twilio (Voice + Messaging) |
| LLM | OpenAI GPT-4o |
| STT | Deepgram Nova-2 |
| TTS | OpenAI TTS (`tts-1`) |
| Vector Database | (existing — to be connected) |
| SQL Database | PostgreSQL |
| ORM | SQLAlchemy + Alembic |
| Cache | Redis |
| Task Queue | ARQ (async) or Celery |
| Containerization | Docker + Docker Compose |
| Secrets Management | Environment variables / cloud secrets manager |

---

*Document version: 1.0 — Last updated: 2026-02-24*
