from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, JobContext, Agent, RunContext, function_tool
from livekit.plugins import deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import DEFAULT_PATIENT
from prompts import GREETING_PROMPT, SYSTEM_PROMPT

load_dotenv(".env.local")


class CareCaller(Agent):
    def __init__(self, patient: dict) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT.format(**patient),
        )
        self.patient = patient

    @function_tool()
    async def end_call(self, ctx: RunContext) -> None:
        """End the call. Use this when the conversation is complete, the patient opts out,
        it's a wrong number, or the patient wants to hang up."""
        # Say goodbye first, then disconnect
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

    await session.start(
        room=ctx.room,
        agent=CareCaller(patient=patient),
    )

    await session.generate_reply(
        instructions=GREETING_PROMPT.format(**patient)
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
