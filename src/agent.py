import json

from dotenv import load_dotenv
from loguru import logger
from livekit import agents
from livekit.agents import AgentSession, JobContext, Agent, RunContext, function_tool
from livekit.plugins import deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import DEFAULT_PATIENT, HEALTH_QUESTIONS
from prompts import GREETING_PROMPT, SYSTEM_PROMPT

load_dotenv(".env.local")

VALID_OUTCOMES = {
    "completed", "incomplete", "opted_out",
    "scheduled", "escalated", "wrong_number", "voicemail",
}


class CareCaller(Agent):
    def __init__(self, patient: dict) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT.format(**patient),
        )
        self.patient = patient
        self.responses: dict[int, str] = {i: "" for i in range(len(HEALTH_QUESTIONS))}
        self.outcome: str | None = None

    def _build_call_summary(self) -> dict:
        return {
            "patient_name": self.patient["patient_name"],
            "outcome": self.outcome or "incomplete",
            "responses": [
                {"question": HEALTH_QUESTIONS[i], "answer": self.responses[i]}
                for i in range(len(HEALTH_QUESTIONS))
            ],
        }

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
        return f"Recorded answer for question {question_index + 1}/{len(HEALTH_QUESTIONS)}."

    @function_tool()
    async def set_call_outcome(self, ctx: RunContext, outcome: str) -> str:
        """Set the final outcome of this call. Call this BEFORE ending the call.
        outcome must be one of: completed, incomplete, opted_out, scheduled, escalated, wrong_number, voicemail."""
        if outcome not in VALID_OUTCOMES:
            return f"Invalid outcome '{outcome}'. Must be one of: {', '.join(sorted(VALID_OUTCOMES))}."
        self.outcome = outcome
        logger.info("Call outcome set: {outcome}", outcome=outcome)
        return f"Outcome set to '{outcome}'."

    @function_tool()
    async def end_call(self, ctx: RunContext) -> None:
        """End the call. Use this when the conversation is complete, the patient opts out,
        it's a wrong number, or the patient wants to hang up.
        IMPORTANT: Always call set_call_outcome BEFORE calling end_call."""
        summary = self._build_call_summary()
        logger.info("Call ended. Summary:\n{summary}", summary=json.dumps(summary, indent=2))
        self.session.generate_reply(
            instructions="Say a brief, warm goodbye to end the call."
        )
        await ctx.wait_for_playout()
        self.session.shutdown()


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

    patient = DEFAULT_PATIENT
    agent = CareCaller(patient=patient)

    await session.start(
        room=ctx.room,
        agent=agent,
    )

    @session.on("close")
    def on_close(*args):
        summary = agent._build_call_summary()
        logger.info("Session closed. Final summary:\n{summary}", summary=json.dumps(summary, indent=2))

    await session.generate_reply(
        instructions=GREETING_PROMPT.format(**patient)
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
