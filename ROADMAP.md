# CareCaller Voice Agent — Roadmap

## Stack

| Component | Choice |
|-----------|--------|
| Transport | LiveKit Cloud (free tier) |
| VAD | Silero (local) |
| STT | Deepgram Nova-2 ($200 free credits) |
| LLM | Groq — Llama 4 Scout 17B |
| TTS | Deepgram Aura |
| Backend | FastAPI (room tokens, call data API) |
| Agent | LiveKit Agents SDK (Python) |

---

## Phase 1: Project Setup & Credentials

- [x] Install dependencies: `livekit-agents`, `livekit-plugins-deepgram`, `livekit-plugins-silero`, `livekit-plugins-groq`
- [x] Create LiveKit Cloud account → get `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- [x] Create Deepgram account → get `DEEPGRAM_API_KEY`
- [x] Set up LLM API key (Groq)
- [x] Create `.env` file with all keys
- [x] Verify basic "hello world" agent connects to LiveKit playground

**How:** Sign up at livekit.io/cloud and deepgram.com. Install packages via `uv add`. Run minimal agent, test with `agents-playground.livekit.io`.

---

## Phase 2: Basic Voice Agent (Hardcoded Flow)

- [x] Build a minimal `VoicePipelineAgent` that greets and responds
- [x] Write the system prompt — agent persona "Jessica from TrimRX"
- [x] Hardcode a single patient profile (name, medication, dosage) for testing
- [x] Agent should: greet → confirm identity → ask if interested in refill → ask if they have 2 mins
- [x] Test with LiveKit playground — verify voice in/out works end to end

**How:** Create `agent.py` with LiveKit agent entrypoint. System prompt based on transcript samples. Use `before_llm_cb` or prompt injection to feed patient context.

---

## Phase 3: State Tracking & Response Extraction

Combines questionnaire state tracking with structured data capture — they're tightly coupled.

- [x] Define the 14 health questions as a structured list (`config.py`)
- [x] System prompt guides the LLM through the call flow (prompt-based)
- [x] Add `record_answer` function tool — LLM calls it after each patient answer with `{question_index, answer}`
- [x] Track call state in code: responses dict, call outcome on agent instance
- [x] Accumulate responses in a session dict as the call progresses
- [x] Output final structured JSON matching the hackathon format (14 Q&A pairs)
- [x] Handle partial responses (incomplete calls — return what we got, empty string for unanswered)
- [x] Add `set_call_outcome` function tool — LLM sets outcome (completed, incomplete, opted_out, scheduled, escalated, wrong_number, voicemail)
- [x] Log/print structured results when call ends (loguru + session close handler)
- [x] Text-based simulation tests for 6 scenarios (happy path, opted_out, wrong_number, incomplete, escalation, reschedule) — all passing

**How:** Use `@function_tool` decorator on `CareCaller` class. LLM calls `record_answer` as a side effect during conversation. Call state stored as instance variables on the agent. Use shutdown callback to dump final JSON.

---

## Phase 5: Edge Case Handling

- [x] **Opt-out:** Patient says "no thanks" / "not interested" → agent thanks them, ends call gracefully (tested)
- [x] **Wrong number:** "Who? I don't know any [name]" → agent apologizes, marks as wrong_number (tested)
- [x] **Reschedule:** "Can you call back later?" → agent offers to schedule, captures preferred time (tested)
- [x] **Escalation:** Patient reports serious side effects / medical emergency → agent escalates to human (tested)
- [x] **Off-script:** Patient asks about pricing, dosage concerns, shipping → handled in system prompt
- [x] **Medical advice guardrail:** Agent must NOT give medical guidance — handled in system prompt
- [ ] **Voicemail:** No answer → agent leaves brief message (needs voice test)

**How:** Edge cases handled via system prompt instructions + tested with text simulation.

---

## Phase 6: FastAPI Integration

- [ ] Endpoint to generate LiveKit room tokens (`POST /token`)
- [ ] Endpoint to start a call with a specific patient profile (`POST /calls`)
- [ ] Endpoint to get call results — structured responses, outcome, metadata (`GET /calls/{call_id}`)
- [ ] Load patient profiles from hackathon dataset (train/val data)
- [ ] Agent worker reads patient context from API when joining a room

**How:** Use `livekit-api` package for token generation. Agent worker connects to FastAPI to fetch patient data on call start. Store call results in memory (or SQLite).

---

## Phase 7: Testing & Tuning

- [ ] Test against 35 transcript samples — does our agent produce similar conversation flow?
- [ ] Compare structured output format against training data `responses` field
- [ ] Tune system prompt for natural conversation quality
- [ ] Tune for response accuracy — are all 14 answers captured correctly?
- [ ] Test all 7 outcome types: completed, incomplete, opted_out, scheduled, escalated, wrong_number, voicemail
- [ ] Measure latency — agent should respond within 1-2 seconds

**How:** Run simulated calls via playground. Compare output JSON against expected format. Iterate on prompt.

---

## Phase 8: Web UI & Demo (Later)

- [ ] Custom web frontend with mic/speaker controls
- [ ] Live transcript display during call
- [ ] Structured response panel — shows Q&A filling in real-time
- [ ] Call outcome display
- [ ] Polish for 5-minute live demo

**How:** TBD — React or plain HTML/JS with LiveKit client SDK.

---

## Current Status

**Phase:** Phases 1-3 and 5 complete. Next: Phase 6 (FastAPI Integration) or Phase 7 (Testing & Tuning).
