from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, JobContext, Agent
from livekit.plugins import deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(".env.local")


class CareCaller(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are Jessica, a friendly healthcare check-in agent from TrimRX. "
                "You make outbound calls to patients for medication refill check-ins. "
                "Be warm, professional, and concise. "
                "For now, just greet the user and have a brief conversation."
            ),
        )


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

    await session.start(
        room=ctx.room,
        agent=CareCaller(),
    )

    await session.generate_reply(
        instructions="Greet the user. Say: Hi there, this is Jessica from TrimRX. How are you doing today?"
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
