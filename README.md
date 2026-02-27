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

- Handle inbound customer support calls autonomously for common HVAC support scenarios across residential units, commercial systems, and parts & accessories
- Execute outbound calls for appointment reminders, maintenance follow-ups, and warranty notifications
- Provide accurate answers grounded in the product knowledge base via RAG (Pinecone)
- Execute tools (scheduling, warranty lookup, parts check, escalation) in real time during calls
- Identify repeat callers and personalize responses using stored customer data
- Escalate safety-critical situations immediately with hardcoded responses
- Maintain a full audit trail of calls, transcripts, and outcomes

### 1.4 Non-Goals

- The agent will not replace human agents for complex technical repairs or legal disputes
- The agent will not handle video or chat — voice only in v1
- The agent will not process payments directly (can transfer to secure IVR)
- The agent will not support languages other than English in v1
- The agent will not provide an admin dashboard in v1 — administration is API-only

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
- FR-04: The agent must provide answers grounded in the HVAC product knowledge base using RAG via Pinecone
- FR-05: The agent must execute tool calls (scheduling, warranty, parts, escalation) during the call
- FR-06: The agent must detect and respond to safety-critical keywords (gas leak, carbon monoxide, fire, electrical hazard) with a hardcoded emergency response
- FR-07: The agent must offer the caller the choice of live transfer or scheduled callback when escalation is needed
- FR-08: The agent must handle caller interruptions and barge-ins gracefully

#### 1.6.2 Outbound Calls
- FR-09: The system must initiate outbound calls via Twilio based on scheduled triggers or manual API dispatch
- FR-10: Outbound calls must only be placed to customers with documented TCPA consent on file
- FR-11: Outbound call types: appointment reminders, maintenance follow-ups, warranty expiration alerts
- FR-12: The agent must handle voicemail detection (AMD) and leave a pre-scripted voicemail message
- FR-13: Outbound call outcomes (answered, voicemail, no answer, declined) must be logged

#### 1.6.3 RAG & Knowledge Base
- FR-14: The agent must query Pinecone for relevant context before generating a response to product-related questions
- FR-15: RAG queries must be filtered by metadata (product_category, doc_type, product_line) before vector search
- FR-16: Retrieved context must be ranked by relevance; top-k results injected into the LLM prompt
- FR-17: Frequently queried results must be cached in Redis to reduce Pinecone query latency

#### 1.6.4 Data & Persistence
- FR-18: All calls must be logged with: caller ID, timestamp, duration, transcript, resolution status, and agent actions taken
- FR-19: Customer records must include: name, phone number, address, registered products, service history, TCPA consent status
- FR-20: Conversation summaries must be stored and surfaced to the agent on repeat calls
- FR-21: An SMS appointment confirmation must be sent via Twilio Messaging after any appointment is created or modified

#### 1.6.5 Product Scope
- FR-22: The agent must support queries related to residential HVAC units (installation, troubleshooting, maintenance, warranty)
- FR-23: The agent must support queries related to commercial HVAC systems (specifications, service scheduling, parts)
- FR-24: The agent must support parts & accessories inquiries (availability, compatibility, ordering guidance)

#### 1.6.6 Geo-Search (Technician & Distributor Locator)
- FR-25: When a caller asks to find a technician, the agent must ask for the caller's city and state, geocode the input to X, Y, Z Cartesian coordinates, and return the 5 nearest technicians via Pinecone vector search
- FR-26: When a caller asks to find a distributor, the agent must follow the same geocoding and vector search flow and return the 5 nearest distributors
- FR-27: Geocoding (city + state → latitude/longitude → X/Y/Z unit vector) must be performed server-side before querying Pinecone; the caller is never asked for raw coordinates
- FR-28: The geo-search Pinecone index must be kept separate from the HVAC knowledge-base index and must use 3-dimensional vectors (one per Cartesian axis)

### 1.7 Non-Functional Requirements

- NFR-01: Agent response latency must not exceed 1.5 seconds under normal operating conditions
- NFR-02: The system must support at least 50 concurrent calls
- NFR-03: All data at rest must be encrypted (AES-256); all data in transit must use TLS 1.2+
- NFR-04: The system must be containerized with Docker and deployable on AWS
- NFR-05: Twilio webhook endpoints must respond within 5 seconds or Twilio will timeout
- NFR-06: The system must log all LLM inputs and outputs for audit and debugging
- NFR-07: LiveKit must be self-hosted on AWS for cost control and data residency

### 1.8 Constraints & Assumptions

- Callers are English-speaking (multilingual support is out of scope for v1)
- The Pinecone vector database is already populated with HVAC product documentation
- TCPA consent is collected and stored before any outbound campaigns are triggered
- All customer-facing integrations are built from scratch — no existing CRM, ERP, or scheduling system
- Human agent transfer is handled via Twilio's `<Dial>` verb or SIP transfer
- Admin operations are performed via REST API; no web dashboard in v1
- Escalation always offers the caller two options: immediate live transfer or scheduled callback

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
                          │   outbound dialing, TwiML routing,   │
                          │   SMS messaging)                     │
                          └──────────────┬──────────────────────┘
                                         │ WebSocket (Media Stream)
                          ┌──────────────▼──────────────────────┐
                          │           FastAPI App               │
                          │  - /inbound  (TwiML webhook)        │
                          │  - /outbound (trigger endpoint)     │
                          │  - /stream   (WebSocket handler)    │
                          │  - /admin/*  (REST API)             │
                          └──────────────┬──────────────────────┘
                                         │
                          ┌──────────────▼──────────────────────┐
                          │   LiveKit Agent Pipeline (AWS)      │
                          │                                     │
                          │  STT (Deepgram Nova-2)              │
                          │       ↓                             │
                          │  Agent Core (GPT-4o)                │
                          │       ↓                             │
                          │  TTS (OpenAI TTS - tts-1)           │
                          └──┬──────────────┬───────────────────┘
                             │              │
              ┌──────────────▼──┐     ┌─────▼───────────────────┐
              │   Tool Runner   │     │      RAG Retriever       │
              │                 │     │                          │
              │ - Scheduling    │     │  Pinecone Query          │
              │ - Warranty      │     │  Metadata Filtering      │
              │ - Parts Lookup  │     │  Context Reranking       │
              │ - Escalation    │     │  Redis Cache             │
              │ - SMS (Twilio)  │     │                          │
              └──────┬──────────┘     └─────┬────────────────────┘
                     │                      │
        ┌────────────▼──────────────────────▼────────────────────┐
        │                    Data Layer (AWS)                    │
        │                                                        │
        │   PostgreSQL / RDS                Pinecone             │
        │   - customers                     - residential docs   │
        │   - customer_products             - commercial docs    │
        │   - calls                         - parts catalogs     │
        │   - appointments                  - troubleshooting    │
        │   - outbound_queue                - FAQs               │
        │                                   - installation       │
        │   Redis (ElastiCache)             - warranty guides    │
        │   - RAG query cache                                    │
        │   - session state                                      │
        └────────────────────────────────────────────────────────┘
```

### 2.2 Component Breakdown

#### 2.2.1 Telephony Layer (Twilio)
- Receives inbound PSTN calls and responds with TwiML to open a Media Stream WebSocket
- Initiates outbound calls via Twilio REST API with pre-validated TCPA-consented numbers
- Handles call transfer (`<Dial>`), hold music, and voicemail detection (AMD)
- Sends SMS appointment confirmations via Twilio Messaging API
- Webhooks: `/inbound` (call start), `/status` (call events)

#### 2.2.2 API Layer (FastAPI)
- Stateless webhook handler for Twilio events
- WebSocket endpoint `/stream` bridges Twilio audio to LiveKit
- REST endpoints for outbound call dispatch, admin operations, and health checks
- Admin endpoints (API key protected): campaign dispatch, call record queries, customer management
- Authentication: API key for internal/admin services, Twilio signature validation for webhooks

#### 2.2.3 Voice AI Pipeline (LiveKit Agents SDK — self-hosted on AWS)
- **STT**: Deepgram Nova-2 (optimized for telephony audio, low latency)
- **LLM**: GPT-4o with function calling enabled
- **TTS**: OpenAI TTS (`tts-1`) — streamed for low time-to-first-audio
- **VAD**: Silero VAD for end-of-utterance detection on noisy phone audio
- **Turn management**: Handles interruptions, barge-in, and silence timeouts

#### 2.2.4 Agent Core (GPT-4o)
- Stateful conversation with a rolling context window
- System prompt encodes: persona, HVAC domain knowledge boundaries, product scope (residential, commercial, parts), tool use rules, safety overrides
- Safety layer runs before LLM: regex/keyword matching for emergency triggers
- Tool calls executed with optimistic bridge phrases ("Let me check that for you...") to mask latency
- Conversation summary prepended to context window on repeat callers
- Escalation flow always offers two options: live transfer or scheduled callback

#### 2.2.5 RAG Retriever (Pinecone)
- On each product-related query: construct search string → apply metadata filters → Pinecone query → rerank → inject top-k into prompt
- Metadata filters: `product_category` (residential, commercial, parts), `doc_type` (manual, faq, troubleshooting, warranty, catalog), `product_line`
- Redis cache: hash normalized query → cache top-k results with TTL (30 minutes default)
- Fallback: if no result above confidence threshold, agent acknowledges limitation and triggers escalation flow

#### 2.2.6 Tool Runner
- Tools registered as OpenAI function definitions; called by GPT-4o via function calling
- Each tool call is validated, executed, and result returned to GPT-4o within the same turn
- Hard timeout of 3 seconds per tool; timeout triggers graceful fallback response

| Tool | Description | Data Source |
|---|---|---|
| `lookup_customer` | Fetch customer record by phone number | PostgreSQL |
| `lookup_warranty` | Check warranty status by serial number or customer ID | PostgreSQL |
| `check_parts_availability` | Query parts inventory by part number or description | PostgreSQL |
| `create_appointment` | Schedule a service appointment | PostgreSQL |
| `update_appointment` | Modify or cancel an existing appointment | PostgreSQL |
| `get_call_history` | Retrieve prior call summaries for the caller | PostgreSQL |
| `transfer_to_agent` | Trigger Twilio live call transfer to human agent | Twilio API |
| `schedule_callback` | Book a human agent callback for the customer | PostgreSQL |
| `send_appointment_sms` | Send SMS appointment confirmation to caller | Twilio Messaging API |
| `search_technicians` | Find the 5 nearest certified technicians for a given city and state | Pinecone (geo index) |
| `search_distributors` | Find the 5 nearest authorized distributors for a given city and state | Pinecone (geo index) |

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
  id              UUID PRIMARY KEY,
  customer_id     UUID REFERENCES customers(id),
  product_model   VARCHAR(100),
  product_line    VARCHAR(50),   -- 'residential' | 'commercial' | 'parts'
  serial_number   VARCHAR(100) UNIQUE,
  install_date    DATE,
  warranty_expiry DATE
)

-- Parts & accessories inventory
parts_inventory (
  id              UUID PRIMARY KEY,
  part_number     VARCHAR(100) UNIQUE NOT NULL,
  description     VARCHAR(255),
  compatible_with TEXT[],        -- array of compatible model numbers
  quantity_on_hand INTEGER DEFAULT 0,
  lead_time_days  INTEGER
)

-- Call records
calls (
  id              UUID PRIMARY KEY,
  customer_id     UUID REFERENCES customers(id),
  direction       VARCHAR(10),   -- 'inbound' | 'outbound'
  twilio_call_sid VARCHAR(100) UNIQUE,
  started_at      TIMESTAMPTZ,
  ended_at        TIMESTAMPTZ,
  duration_sec    INTEGER,
  resolution      VARCHAR(50),   -- 'resolved' | 'escalated' | 'transferred' |
                                 --  'callback_scheduled' | 'voicemail' | 'no_answer'
  transcript      TEXT,
  summary         TEXT,
  safety_event    BOOLEAN DEFAULT FALSE
)

-- Appointments
appointments (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  call_id        UUID REFERENCES calls(id),
  scheduled_at   TIMESTAMPTZ,
  service_type   VARCHAR(100),
  product_line   VARCHAR(50),   -- 'residential' | 'commercial'
  status         VARCHAR(50),   -- 'scheduled' | 'confirmed' | 'completed' | 'cancelled'
  notes          TEXT,
  sms_sent       BOOLEAN DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
)

-- Outbound campaign queue
outbound_queue (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  campaign_type  VARCHAR(50),   -- 'reminder' | 'followup' | 'warranty_alert'
  scheduled_at   TIMESTAMPTZ,
  status         VARCHAR(50),   -- 'pending' | 'dispatched' | 'completed' |
                                --  'failed' | 'blocked_no_consent'
  payload        JSONB,
  created_at     TIMESTAMPTZ DEFAULT NOW()
)

-- Callback requests (escalation option 2)
callbacks (
  id             UUID PRIMARY KEY,
  customer_id    UUID REFERENCES customers(id),
  call_id        UUID REFERENCES calls(id),
  requested_at   TIMESTAMPTZ DEFAULT NOW(),
  scheduled_for  TIMESTAMPTZ,
  reason         TEXT,
  status         VARCHAR(50)    -- 'pending' | 'completed' | 'cancelled'
)
```

**Pinecone Index Structure — Knowledge Base**

```
Index: ai-agent
Dimensions: 1536 (OpenAI text-embedding-3-small)
Metric: cosine

Metadata schema per vector:
{
  "doc_id":          "string",
  "doc_type":        "manual" | "faq" | "troubleshooting" | "warranty" | "catalog" | "installation",
  "product_category": "residential" | "commercial" | "parts",
  "product_line":    "string",   -- e.g. "CentralAir-5000", "CommercialRTU"
  "chunk_index":     "integer",
  "source_file":     "string",
  "last_updated":    "string"    -- ISO date
}
```

**Pinecone Index Structure — Geo Directory**

```
Index: locations
Dimensions: 3  (X, Y, Z Cartesian unit vector derived from lat/lon)
Metric: dotproduct  -- maximises for nearest point on the unit sphere

Geocoding pipeline (city + state → vector):
  1. Resolve city + state to (lat, lon) via geocoding service
  2. Convert to radians: φ = lat_rad, λ = lon_rad
  3. Project onto unit sphere:
       X = cos(φ) · cos(λ)
       Y = cos(φ) · sin(λ)
       Z = sin(φ)
  4. Store [X, Y, Z] as the vector for each record

Metadata schema per vector:
{
  "record_type":  "technician" | "distributor",
  "name":         "string",
  "address":      "string",
  "city":         "string",
  "state":        "string",
  "phone":        "string",
  "certifications": ["string"],  -- technicians only, e.g. ["NATE", "EPA-608"]
  "product_lines": ["string"],   -- e.g. ["residential", "commercial"]
  "last_updated": "string"       -- ISO date
}

Query flow for search_technicians / search_distributors:
  1. Agent asks caller for city and state
  2. Geocode city+state → (lat, lon) → [X, Y, Z]
  3. Query locations with filter { record_type: "technician" | "distributor" }
     top_k = 5
  4. Return the 5 nearest records; agent reads name, city, and phone to caller
```

### 2.3 Data Flow: Inbound Call

```
1.  Caller dials Twilio number
2.  Twilio POSTs to /inbound → FastAPI returns TwiML <Stream> pointing to /stream WebSocket
3.  FastAPI opens LiveKit session; Twilio streams μ-law audio over WebSocket
4.  LiveKit STT (Deepgram Nova-2) transcribes audio in real time
5.  VAD detects end of utterance → transcript sent to Agent Core
6.  Safety layer checks for emergency keywords → if triggered, hardcoded response returned immediately
7.  Agent Core calls lookup_customer (PostgreSQL) using caller phone number
8.  If returning caller, prior call summary prepended to context
9.  If product/knowledge question: RAG Retriever checks Redis cache → on miss, queries Pinecone
10. Pinecone results filtered by product_category and doc_type → top-k injected into prompt
11. GPT-4o generates response (with tool calls if needed)
12. Tool Runner executes tool calls → results returned to GPT-4o for final response
13. OpenAI TTS converts response to audio → streamed back through LiveKit → Twilio → caller
14. Loop until call ends or escalation triggered
15. On escalation: agent offers live transfer OR callback — caller chooses
16. On call end: transcript saved, GPT-4o generates summary, call record written to PostgreSQL
17. If appointment was created: send_appointment_sms fires via Twilio Messaging
```

### 2.4 Data Flow: Outbound Call

```
1. Scheduler reads pending records from outbound_queue (scheduled_at <= NOW())
2. For each record: validate tcpa_consent = TRUE in customers table
   - If FALSE: mark status = 'blocked_no_consent', skip
3. FastAPI calls Twilio REST API to initiate outbound call
4. Twilio triggers /outbound webhook on answer
5. AMD (Answering Machine Detection):
   - Human: LiveKit pipeline starts with outbound-specific system prompt
   - Voicemail: pre-scripted TTS message played, call ended, outcome logged
6. Human call proceeds like inbound (same pipeline, different prompt context)
7. Call outcome logged to calls table; outbound_queue record updated to 'completed'
```

### 2.5 Deployment Architecture (AWS)

```
┌──────────────────────────────────────────────────────────┐
│                        AWS                               │
│                                                          │
│  ┌────────────────────┐   ┌──────────────────────────┐  │
│  │   ECS / EC2        │   │   LiveKit Server         │  │
│  │   FastAPI App      │◄──►   (EC2, self-hosted)     │  │
│  │   (Docker)         │   │                          │  │
│  └─────────┬──────────┘   └──────────────────────────┘  │
│            │                                             │
│  ┌─────────▼──────────┐   ┌──────────────────────────┐  │
│  │   RDS              │   │   ElastiCache (Redis)    │  │
│  │   PostgreSQL       │   │   - RAG query cache      │  │
│  │   (managed)        │   │   - Session state        │  │
│  └────────────────────┘   └──────────────────────────┘  │
│                                                          │
│  ┌────────────────────┐   ┌──────────────────────────┐  │
│  │   Secrets Manager  │   │   CloudWatch             │  │
│  │   API keys, creds  │   │   Logs, metrics, alerts  │  │
│  └────────────────────┘   └──────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │                             │
  ┌──────▼──────┐              ┌───────▼──────┐
  │   Pinecone  │              │   Twilio /   │
  │   (managed) │              │   OpenAI /   │
  └─────────────┘              │   Deepgram   │
                               └──────────────┘
```

- FastAPI app containerized with Docker; deployed to AWS ECS (Fargate) or EC2
- LiveKit self-hosted on a dedicated EC2 instance (c5.xlarge or higher recommended)
- PostgreSQL on AWS RDS (Multi-AZ for production)
- Redis on AWS ElastiCache
- Secrets (API keys, DB credentials) stored in AWS Secrets Manager
- Logs and metrics via AWS CloudWatch

---

## 3. Design Document

### 3.1 Agent Persona & Voice Design

**Persona**: The agent presents as "Alex," a knowledgeable and friendly HVAC support specialist.

- Tone: professional, calm, empathetic — never robotic or overly formal
- Speech pacing: moderate, with natural pauses after questions
- Acknowledgment phrases used while processing to mask latency: "Let me look that up for you", "One moment", "Give me just a second"
- Does not claim to be human if sincerely asked; acknowledges it is an automated assistant
- Voice: OpenAI TTS `tts-1`, voice `alloy` (or `nova` — confirm during testing)

### 3.2 System Prompt Design

The system prompt is structured in layers:

```
[IDENTITY]
You are Alex, an AI customer support agent for [Company Name], an HVAC product company.
You help customers with questions about residential HVAC units, commercial HVAC systems,
and parts & accessories — including troubleshooting, warranty inquiries, parts availability,
and service scheduling.

[BEHAVIOR RULES]
- Always greet the caller by name if known.
- Be concise. Phone callers do not want long monologues.
- Ask one question at a time.
- Respond in plain spoken English — no bullet points, no markdown.
- If you do not know the answer, say so honestly and offer to escalate.
- Never speculate about safety-critical issues. Use the safety response immediately.
- Do not discuss topics unrelated to HVAC products or customer service.
- When escalating, always offer the caller two options:
    Option 1: Transfer to a live agent right now.
    Option 2: Schedule a callback at a convenient time.

[SAFETY OVERRIDE]
If the caller mentions: gas leak, smell gas, carbon monoxide, CO detector, fire,
electrical hazard, smoke, explosion, burning smell — immediately respond with:
"This sounds like an emergency situation. Please hang up and call 911 immediately.
Do not attempt to operate any equipment."
Do not engage further on the topic.

[CONTEXT]
Customer record: {customer_context}
Prior call summary: {prior_summary}
Retrieved knowledge: {rag_context}

[TOOLS]
You have access to the following tools: {tool_list}
Use tools proactively when customer needs require it.
Always confirm details with the customer before creating or modifying appointments.
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
                          May I have your name?"
    │
    ▼
Classify intent
    │
    ├── Troubleshooting (residential/commercial) ──► RAG (Pinecone) → diagnose → recommend action → offer appointment
    │
    ├── Warranty inquiry ──────────────────────────► lookup_warranty → relay status → offer escalation if disputed
    │
    ├── Parts inquiry ─────────────────────────────► check_parts_availability → relay availability / compatibility
    │
    ├── Schedule service ──────────────────────────► create_appointment → confirm → send_appointment_sms
    │
    ├── Manage appointment ────────────────────────► update_appointment → confirm → send_appointment_sms
    │
    ├── Find technician ─────────────────────────────► Ask city + state → search_technicians → read top 5 to caller
    │
    ├── Find distributor ────────────────────────────► Ask city + state → search_distributors → read top 5 to caller
    │
    ├── Billing / Payment ─────────────────────────► Escalate (out of AI scope)
    │
    ├── Emergency ─────────────────────────────────► Hardcoded emergency response (bypasses LLM)
    │
    └── Unresolvable ──────────────────────────────► Escalate
    │
    ▼
Escalation (if needed)
    │
    ├── "Would you prefer to speak with someone right now, or
    │    should I schedule a callback at a time that works for you?"
    │
    ├── Live transfer ──► transfer_to_agent → Twilio <Dial>
    │
    └── Callback ───────► schedule_callback → confirm time → log to callbacks table
    │
    ▼
Resolution / Close
    "Is there anything else I can help you with?"
    → Close call
    → If appointment created/modified: send_appointment_sms
    │
    ▼
Post-call processing
    Save transcript → generate summary (GPT-4o) → write to calls table
```

#### 3.3.2 Outbound Call Flow

```
CALL INITIATED (from outbound_queue)
    │
    ▼
TCPA consent validated → AMD
    │
    ├── Human answered ──► Personalized greeting → deliver campaign message → handle questions
    │
    └── Voicemail ───────► Pre-scripted TTS voicemail → hang up → log 'voicemail'
    │
    ▼
Campaign-specific flows:
    │
    ├── Appointment reminder:
    │     "You have a service appointment on [date] at [time]."
    │     Caller can confirm / reschedule / cancel → update_appointment → send_appointment_sms
    │
    ├── Maintenance follow-up:
    │     "We're checking in on your recent service visit."
    │     Collect satisfaction feedback → log notes → offer next service booking
    │
    └── Warranty expiration alert:
          "Your warranty for [product] expires on [date]."
          Offer extended warranty info → escalate to sales if interested
    │
    ▼
Log outcome → update outbound_queue
```

### 3.4 RAG Pipeline Design (Pinecone)

```
User utterance
    │
    ▼
Intent classification
    │
    ├── Knowledge question? ──► YES ──► Continue
    │                           NO  ──► Skip RAG, go to tool/response
    ▼
Query construction
    - Extract entities: product model, product line, symptom, part name/number
    - Determine metadata filters:
        product_category: residential | commercial | parts
        doc_type: manual | faq | troubleshooting | warranty | catalog | installation
    │
    ▼
Redis cache lookup
    - Key: SHA256(normalized_query + metadata_filters)
    - HIT ──► Return cached result (skip Pinecone)
    - MISS ──► Continue
    │
    ▼
Pinecone query
    - Embed query with OpenAI text-embedding-3-small
    - Query with metadata filter + top_k=10
    │
    ▼
Reranking
    - Score chunks by relevance to query
    - Select top-3 chunks
    - If max score < 0.70 threshold → no confident result → escalation fallback
    │
    ▼
Cache result in Redis (TTL: 30 minutes)
    │
    ▼
Inject top-3 chunks into LLM prompt as [CONTEXT]
```

### 3.5 Latency Budget

| Stage | Target Latency |
|---|---|
| Twilio audio → LiveKit STT (Deepgram) | 100–200ms |
| VAD (end-of-utterance detection) | 300–500ms |
| Safety keyword check | <5ms |
| Customer DB lookup (PostgreSQL/RDS) | <50ms |
| RAG query — Redis cache hit | <20ms |
| RAG query — Pinecone (cache miss) | 200–400ms |
| Geo-search — Pinecone (3D dot-product, top_k=5) | 50–150ms |
| GPT-4o inference | 400–800ms |
| Tool execution (PostgreSQL) | <100ms |
| Tool execution (Twilio API) | <500ms |
| OpenAI TTS (first audio chunk streamed) | 200–400ms |
| **Total (no tool call, cache hit)** | **~1.0–1.5s** |
| **Total (no tool call, cache miss)** | **~1.2–1.8s** |
| **Total (with one tool call)** | **~1.7–2.3s** |

### 3.6 Escalation Design

When the agent cannot resolve an issue, it always presents the caller with two explicit options:

> *"I want to make sure you get the right help. I can connect you with one of our specialists right now, or if you'd prefer, I can schedule a callback at a time that works better for you. Which would you prefer?"*

| Path | Tool | Outcome |
|---|---|---|
| Live transfer | `transfer_to_agent` | Twilio `<Dial>` to human agent queue; partial transcript logged |
| Scheduled callback | `schedule_callback` | Time confirmed with caller; record written to `callbacks` table |

### 3.7 Safety & Error Handling

| Scenario | Handling |
|---|---|
| Emergency keyword detected | Hardcoded response; LLM bypassed; call flagged as safety_event in DB |
| RAG returns no confident result (score < 0.70) | Agent acknowledges, offers live transfer or callback |
| Pinecone query fails | Log error, skip RAG, agent continues without context, offers escalation |
| Tool call times out (>3s) | Agent: "I'm having trouble accessing that right now" — offers callback |
| LLM call fails | Fallback scripted response; log error; offer escalation |
| Call drops mid-conversation | Save partial transcript; mark resolution = 'dropped' |
| Caller silent >10 seconds | Agent prompts once; second silence closes call politely |
| Caller abusive/threatening | Warn once; transfer to human or end call |
| Max turns exceeded (>20) | Agent proactively offers escalation |
| Outbound — no TCPA consent | Call blocked; queue record marked 'blocked_no_consent'; no retry |

### 3.8 Security Design

- Twilio webhook signature validation on every inbound request (`X-Twilio-Signature` header)
- No PII logged in plaintext application logs; structured logs reference UUIDs only
- All API keys and credentials stored in AWS Secrets Manager; never hardcoded or in `.env` in production
- Database access via parameterized queries only — no raw string interpolation
- Customer phone numbers stored in E.164 format; SHA256-hashed for Redis cache keys
- TCPA consent check is a hard gate in the outbound call code path — no exceptions
- Admin API endpoints protected by API key authentication
- All traffic between services uses TLS 1.2+; RDS encryption at rest enabled

---

## 4. User Stories

### 4.1 Inbound Customer Stories

---

**US-001 — First-time caller greeting**
> As a first-time caller, I want the agent to ask for my name so that my details can be saved for future calls.

**Acceptance Criteria:**
- Agent greets caller without using a name it does not have
- Agent asks for name during the call
- Customer record is created in PostgreSQL

---

**US-002 — Returning caller recognition**
> As a returning customer, I want the agent to recognize me by my phone number and greet me by name so that I don't have to repeat my information.

**Acceptance Criteria:**
- Agent looks up phone number at call start via `lookup_customer`
- If found, agent greets caller by name in the opening line
- Prior call summary is available to the agent as context

---

**US-003 — Residential unit troubleshooting**
> As a homeowner whose HVAC unit is not cooling, I want the agent to walk me through troubleshooting steps so that I can resolve the issue without scheduling a technician.

**Acceptance Criteria:**
- Agent queries Pinecone filtered to `product_category: residential` and `doc_type: troubleshooting`
- Agent presents steps in plain spoken language (no bullet points or markdown)
- If unresolved, agent offers to schedule a service appointment
- If safety risk is identified, agent triggers emergency response

---

**US-004 — Commercial system inquiry**
> As a facilities manager with a commercial HVAC system issue, I want to get relevant support information specific to commercial equipment so that I receive accurate guidance.

**Acceptance Criteria:**
- Agent identifies the inquiry as commercial via context or direct confirmation
- RAG query is filtered to `product_category: commercial`
- Response references commercial-specific documentation, not residential guides

---

**US-005 — Parts availability check**
> As a customer attempting a DIY repair, I want to know if a specific replacement part is in stock and compatible with my unit so that I can decide whether to order it or hire a technician.

**Acceptance Criteria:**
- Agent identifies the part from customer's description or model/part number
- Agent calls `check_parts_availability` and relays stock status and compatibility
- If in stock, agent provides estimated lead time

---

**US-006 — Warranty status inquiry**
> As a customer, I want to know whether my HVAC unit is still under warranty so that I know if a repair will be covered.

**Acceptance Criteria:**
- Agent calls `lookup_warranty` with customer's serial number or product record
- Agent clearly states warranty status: active, expired, or not found
- If expired, agent offers escalation or relevant service plan information

---

**US-007 — Service appointment scheduling**
> As a customer, I want to schedule a service appointment over the phone so that a technician can inspect my unit.

**Acceptance Criteria:**
- Agent collects: preferred date/time range, service address, issue description, product line (residential/commercial)
- Agent calls `create_appointment` and confirms the booking details
- Agent calls `send_appointment_sms` — customer receives SMS confirmation
- Appointment is visible in the `appointments` table with correct `product_line`

---

**US-008 — Appointment rescheduling**
> As a customer, I want to reschedule an existing appointment so that it fits my updated availability.

**Acceptance Criteria:**
- Agent retrieves existing appointment via `get_call_history` or customer lookup
- Agent confirms current appointment details before modifying
- Agent calls `update_appointment` with new date/time
- Updated SMS confirmation sent via `send_appointment_sms`

---

**US-009 — Emergency safety situation**
> As a customer who smells gas near their HVAC unit, I want the agent to immediately direct me to emergency services so that I am not harmed.

**Acceptance Criteria:**
- Safety layer detects keyword before LLM processes the input
- Agent delivers hardcoded emergency response directing caller to call 911
- LLM is not invoked for this response
- Call is flagged in the `calls` table with `safety_event = TRUE`

---

**US-010 — Escalation with choice**
> As a customer with an issue the agent cannot resolve, I want to choose between speaking to a live agent immediately or scheduling a callback so that I can get help on my own terms.

**Acceptance Criteria:**
- Agent clearly presents both escalation options
- If live transfer chosen: `transfer_to_agent` called; Twilio executes the transfer
- If callback chosen: `schedule_callback` called; customer confirms preferred time
- Partial transcript and reason for escalation logged before transfer or callback creation

---

**US-011 — Unresolvable question**
> As a customer asking a question outside the knowledge base, I want the agent to acknowledge it cannot answer rather than guess, so that I am not given incorrect information.

**Acceptance Criteria:**
- If Pinecone returns no result above confidence threshold (0.70), agent does not fabricate an answer
- Agent acknowledges the limitation and offers the escalation choice (live transfer or callback)
- Interaction logged with `resolution = 'unresolved'`

---

### 4.2 Outbound Call Stories

---

**US-012 — Appointment reminder call**
> As a customer with an upcoming service appointment, I want to receive a reminder call so that I don't miss it.

**Acceptance Criteria:**
- Outbound call triggered 24 hours before appointment from `outbound_queue`
- Agent states appointment date, time, and service type
- Customer can confirm, reschedule, or cancel via voice
- `update_appointment` called for any changes; SMS confirmation sent
- Outcome logged in `calls` and `outbound_queue` updated

---

**US-013 — TCPA consent enforcement**
> As a compliance officer, I want outbound calls placed only to customers with TCPA consent so that the company does not violate federal regulations.

**Acceptance Criteria:**
- Every outbound call initiation checks `tcpa_consent = TRUE`
- No consent: call is not placed; queue record set to `blocked_no_consent`
- No bypass or override exists in the code path

---

**US-014 — Voicemail handling**
> As a customer who missed an outbound call, I want the agent to leave a professional voicemail so that I know why I was called.

**Acceptance Criteria:**
- Twilio AMD detects answering machine
- Pre-scripted TTS message played (not LLM-generated)
- Message includes company name, reason for call, and callback number
- Outcome logged as `voicemail`

---

**US-015 — Warranty expiration alert**
> As a customer whose warranty expires within 30 days, I want a proactive call so that I can consider an extended warranty or service plan.

**Acceptance Criteria:**
- Scheduler identifies customers with `warranty_expiry` within 30 days
- Outbound queued with `campaign_type = 'warranty_alert'`
- Agent informs customer of expiration and presents options
- Outcome and any decisions logged

---

### 4.3 Geo-Search Stories

---

**US-019 — Find a nearby technician**
> As a customer who needs an in-home repair, I want the agent to find certified HVAC technicians near my city so that I can contact one directly.

**Acceptance Criteria:**
- Agent asks for city and state before invoking the tool
- `search_technicians` geocodes city + state to an X/Y/Z unit vector and queries the `locations` Pinecone index with `record_type = "technician"`
- Agent reads name, city, and phone number for each of the 5 results
- If geocoding fails (unrecognized city/state), agent asks the caller to clarify or spell the city name
- Tool call completes within the 3-second hard timeout; on timeout, agent offers to escalate

---

**US-020 — Find a nearby distributor**
> As a contractor who needs to purchase parts locally, I want the agent to find authorized HVAC distributors near my location so that I can visit or call one directly.

**Acceptance Criteria:**
- Agent asks for city and state before invoking the tool
- `search_distributors` geocodes city + state to an X/Y/Z unit vector and queries the `locations` Pinecone index with `record_type = "distributor"`
- Agent reads name, city, and phone number for each of the 5 results
- If no distributors are indexed within a reasonable radius, agent acknowledges and offers to escalate to the main sales line
- Tool call completes within the 3-second hard timeout; on timeout, agent offers to escalate

---

### 4.4 Administrative Stories

---

**US-016 — Call record audit**
> As an operations manager, I want to query call records including transcripts and summaries via the admin API so that I can monitor quality and resolve disputes.

**Acceptance Criteria:**
- Every call has a record in `calls` with transcript and summary
- Admin API supports filtering by date range, customer ID, resolution status, safety_event flag
- No PII exposed in application logs; only structured UUID-based references

---

**US-017 — Outbound campaign dispatch**
> As an operations manager, I want to trigger an outbound campaign for a list of customers via the admin API so that I can notify them about a product recall or service bulletin.

**Acceptance Criteria:**
- Admin endpoint `POST /admin/campaigns` accepts customer ID list and campaign type
- System validates TCPA consent per customer before inserting into `outbound_queue`
- Campaign progress trackable via `status` field on each queue record

---

**US-018 — Knowledge base updates**
> As a product manager, I want to add or update documents in the Pinecone knowledge base so that the agent always provides current information.

**Acceptance Criteria:**
- A documented ingestion process exists for adding documents to Pinecone
- Documents are chunked, embedded (text-embedding-3-small), and stored with correct metadata
- `last_updated` metadata field is set on ingestion
- Old versions of updated documents are replaced or marked superseded

---

## 5. Tech Stack Summary

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| API Framework | FastAPI |
| Voice Platform | LiveKit Agents SDK (self-hosted on AWS EC2) |
| Telephony | Twilio (Voice + Messaging API) |
| LLM | OpenAI GPT-4o |
| STT | Deepgram Nova-2 |
| TTS | OpenAI TTS (`tts-1`) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector Database | Pinecone (managed) |
| SQL Database | PostgreSQL (AWS RDS) |
| ORM | SQLAlchemy + Alembic |
| Cache | Redis (AWS ElastiCache) |
| Task Queue | ARQ (async Redis-based) |
| Containerization | Docker + Docker Compose (dev) / ECS Fargate (prod) |
| Secrets Management | AWS Secrets Manager |
| Monitoring | AWS CloudWatch |

---

*Document version: 1.1 — Last updated: 2026-02-24*
