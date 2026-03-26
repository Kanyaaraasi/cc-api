# Known Bugs

## 1. Agent uses default patient name instead of selected patient

**Symptom:** Agent always greets with "Am I speaking with Sarah Johnson?" regardless of which patient is selected in the UI dropdown.

**Root cause:** Room metadata is empty when the agent reads it.

**Flow:**
1. UI selects patient (e.g., "Daniel Robinson")
2. `POST /api/v1/calls` → creates room via `CreateRoomRequest(metadata=room_metadata)` + dispatches agent via `create_dispatch(metadata=room_metadata)`
3. Agent receives job, runs `_parse_metadata(ctx)`
4. `ctx.room.metadata` is `""` — empty
5. `ctx.job.accept_arguments.metadata` — untested, may also be empty
6. `ctx.job.job.metadata` — crashed with `AttributeError` earlier, now wrapped in try/except
7. Falls back to `DEFAULT_PATIENT` → "Sarah Johnson"

**Why metadata is empty:**
- The room is created server-side with metadata via `CreateRoomRequest`
- The agent is dispatched immediately after
- The agent joins the room but `ctx.room.metadata` hasn't synced yet (LiveKit timing issue)
- The dispatch metadata (`CreateAgentDispatchRequest(metadata=...)`) should be available via `ctx.job` but the exact attribute path is unclear in LiveKit Agents v1.5

**Attempted fixes:**
- `ctx.room.metadata` → empty at read time
- `ctx.job.job.metadata` → `AttributeError: job` (v1.5 API changed)
- `ctx.job.accept_arguments.metadata` → untested
- `wait_for_participant()` before reading → agent didn't receive job at all
- `RoomConfiguration(metadata=...)` in token → room metadata empty when agent reads it

**Possible solutions:**
1. **Debug `ctx.job` structure** — log every attribute of `ctx.job` to find where dispatch metadata actually lives in v1.5
2. **Poll room metadata** — wait a few seconds after joining, then read `ctx.room.metadata`
3. **Use participant attributes** — pass patient data as user participant attributes instead of room metadata
4. **Direct API call** — agent fetches patient data from FastAPI using the room name as key

## 2. Transcript shows all messages as "user" role

**Symptom:** In the UI, both agent and user speech appear with "USER" label.

**Root cause:** `LivekitClient.ParticipantKind.AGENT` may not exist in the CDN build, and identity-based detection (`startsWith('agent')`) doesn't match the agent's actual identity.

**Current fix (untested):** Compare `seg.participant?.identity` against `localIdentity` — if it's not the local user, it's the agent.

**Status:** Fix is in code but needs live testing.

## 3. UI doesn't reflect call end

**Symptom:** When agent ends the call (via `end_call` tool), the UI stays in "CONNECTED" state.

**Root cause:** The `Disconnected` event only fires when the room closes. When only the agent disconnects, the room stays open with the user still in it.

**Current fix (untested):** Added `ParticipantDisconnected` listener that detects when the agent leaves and triggers `handleDisconnect()`.

**Status:** Fix is in code but needs live testing.

## 4. Agent says "end call" verbally after call ends

**Symptom:** After the agent says goodbye and calls `end_call`, it speaks again saying something about ending the call.

**Root cause:** The old `end_call` tool called `session.generate_reply(instructions="Say goodbye")` which made the LLM speak AFTER the tool call.

**Fix applied:** Removed `generate_reply` from `end_call`. Prompt updated to tell LLM: say goodbye first, then call `set_call_outcome`, then call `end_call` (which disconnects silently).

**Status:** Fixed.
