import asyncio
import json
import logging
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

from agent.config import HEALTH_QUESTIONS
from agent.prompts import GREETING_PROMPT, SYSTEM_PROMPT
from db.database import async_session
from db.repositories import CallRepository

load_dotenv(".env.local")

# Configure colorful logging — intercept stdlib logging into loguru


class _LoguruHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logger.remove()
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan> | "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
)

# Route all stdlib logging through loguru
logging.basicConfig(handlers=[_LoguruHandler()], level=logging.INFO, force=True)

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


async def _load_patient_from_db(ctx: JobContext) -> tuple[dict, str]:
    """Look up patient info from the database using the room name."""
    room_name = ctx.room.name
    prefix = "call-"
    if not room_name.startswith(prefix):
        raise ValueError(f"Room name '{room_name}' doesn't match expected 'call-<uuid>' format")

    call_id = room_name[len(prefix):]
    logger.info("Looking up call {call_id} from DB", call_id=call_id)

    async with async_session() as session:
        repo = CallRepository(session)
        record = await repo.get_call(call_id)

    if not record:
        raise LookupError(f"Call {call_id} not found in database")

    patient = {
        "patient_name": record.patient_name,
        "medication": record.medication,
        "dosage": record.dosage,
    }
    logger.info("Loaded patient: {name}", name=patient["patient_name"])
    return patient, call_id


server = agents.AgentServer()


@server.rtc_session(agent_name="carecaller")
async def handle_session(ctx: JobContext):
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=groq.LLM(model="openai/gpt-oss-120b"),
        tts=deepgram.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    patient, call_id = await _load_patient_from_db(ctx)
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
