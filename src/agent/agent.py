import asyncio
import json
import sys
from pathlib import Path

# Ensure src/ is on the path so package imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RunContext, function_tool
from livekit.plugins import deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from loguru import logger

from agent.config import DEFAULT_PATIENT, HEALTH_QUESTIONS
from agent.prompts import GREETING_PROMPT, SYSTEM_PROMPT
from db.database import async_session
from db.repositories import CallRepository

load_dotenv(".env.local")

VALID_OUTCOMES = {
    "completed",
    "incomplete",
    "opted_out",
    "scheduled",
    "escalated",
    "wrong_number",
    "voicemail",
}


class CareCaller(Agent):
    def __init__(self, patient: dict, call_id: str | None = None) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT.format(**patient),
        )
        self.patient = patient
        self.call_id = call_id
        self.responses: dict[int, str] = {i: "" for i in range(len(HEALTH_QUESTIONS))}
        self.outcome: str | None = None

    def _build_call_summary(self) -> dict:
        return {
            "call_id": self.call_id,
            "patient_name": self.patient["patient_name"],
            "outcome": self.outcome or "incomplete",
            "responses": [
                {"question": HEALTH_QUESTIONS[i], "answer": self.responses[i]}
                for i in range(len(HEALTH_QUESTIONS))
            ],
        }

    async def _persist_response(self, question_index: int, answer: str) -> None:
        if not self.call_id:
            return
        try:
            async with async_session() as session:
                repo = CallRepository(session)
                await repo.update_response(self.call_id, question_index, answer)
        except Exception as e:
            logger.error("Failed to persist response: {e}", e=e)

    async def _persist_outcome(self, outcome: str) -> None:
        if not self.call_id:
            return
        try:
            async with async_session() as session:
                repo = CallRepository(session)
                await repo.set_outcome(self.call_id, outcome)
        except Exception as e:
            logger.error("Failed to persist outcome: {e}", e=e)

    @function_tool()
    async def record_answer(self, ctx: RunContext, question_index: int, answer: str) -> str:
        """Record the patient's answer to a health questionnaire question.
        Call this IMMEDIATELY after the patient answers each health question.
        question_index: 0-13 matching the question order in the questionnaire.
        answer: The patient's answer summarized concisely."""
        if not (0 <= question_index < len(HEALTH_QUESTIONS)):
            return f"Invalid question_index. Must be 0-{len(HEALTH_QUESTIONS) - 1}."
        self.responses[question_index] = answer
        logger.info(
            "Recorded answer | Q{idx}: {q} -> {a}",
            idx=question_index,
            q=HEALTH_QUESTIONS[question_index],
            a=answer,
        )
        await self._persist_response(question_index, answer)
        return f"Recorded answer for question {question_index + 1}/{len(HEALTH_QUESTIONS)}."

    @function_tool()
    async def set_call_outcome(self, ctx: RunContext, outcome: str) -> str:
        """Set the final outcome of this call. Call this BEFORE ending the call.

        outcome must be one of: completed, incomplete, opted_out,
        scheduled, escalated, wrong_number, voicemail."""
        if outcome not in VALID_OUTCOMES:
            return (
                f"Invalid outcome '{outcome}'. Must be one of: {', '.join(sorted(VALID_OUTCOMES))}."
            )
        self.outcome = outcome
        logger.info("Call outcome set: {outcome}", outcome=outcome)
        await self._persist_outcome(outcome)
        return f"Outcome set to '{outcome}'."

    @function_tool()
    async def end_call(self, ctx: RunContext) -> None:
        """End the call and disconnect silently.
        Use this AFTER you have already said your goodbye to the patient.
        Do NOT say anything after calling this — just end the call.
        IMPORTANT: Always call set_call_outcome BEFORE calling end_call."""
        summary = self._build_call_summary()
        logger.info(
            "Call ended. Summary:\n{summary}",
            summary=json.dumps(summary, indent=2),
        )
        self.session.shutdown()


def _parse_metadata(ctx: JobContext) -> tuple[dict, str | None]:
    """Extract patient info from dispatch metadata or room metadata."""
    # 1. Try dispatch metadata via accept_arguments
    raw = ""
    try:
        raw = ctx.job.accept_arguments.metadata or ""
        if raw:
            logger.info("Got metadata from accept_arguments")
    except AttributeError:
        pass

    # 2. Try job.job (protobuf Job object)
    if not raw:
        try:
            raw = ctx.job.job.metadata or ""
            if raw:
                logger.info("Got metadata from job.job")
        except AttributeError:
            pass

    # 3. Fallback to room metadata
    if not raw:
        raw = ctx.room.metadata or ""
        if raw:
            logger.info("Got metadata from room")

    logger.info("Metadata raw: {raw}", raw=repr(raw[:200] if raw else ""))

    try:
        metadata = json.loads(raw) if raw else {}
        if "patient_name" in metadata:
            patient = {
                "patient_name": metadata["patient_name"],
                "medication": metadata["medication"],
                "dosage": metadata["dosage"],
            }
            call_id = metadata.get("call_id")
            logger.info("Patient: {name}", name=patient["patient_name"])
            return patient, call_id
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse metadata: {e}", e=e)

    logger.warning("Using default patient profile")
    return DEFAULT_PATIENT, None


server = agents.AgentServer()


@server.rtc_session(agent_name="carecaller")
async def handle_session(ctx: JobContext):
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=groq.LLM(model="meta-llama/llama-4-scout-17b-16e-instruct"),
        tts=deepgram.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    patient, call_id = _parse_metadata(ctx)
    agent = CareCaller(patient=patient, call_id=call_id)

    await session.start(
        room=ctx.room,
        agent=agent,
    )

    @session.on("close")
    def on_close(*args):
        summary = agent._build_call_summary()
        logger.info(
            "Session closed. Final summary:\n{summary}",
            summary=json.dumps(summary, indent=2),
        )
        if agent.call_id and not agent.outcome:
            asyncio.create_task(agent._persist_outcome("incomplete"))

    await session.generate_reply(instructions=GREETING_PROMPT.format(**patient))


if __name__ == "__main__":
    agents.cli.run_app(server)
