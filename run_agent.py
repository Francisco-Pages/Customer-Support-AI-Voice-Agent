"""
LiveKit agent worker entry point.

Run this file to start the agent worker process. It connects to the
LiveKit server and waits for dispatched jobs (one per inbound/outbound call).

Usage (from project root, with .env populated):

    # Development — auto-reloads on file change, verbose logging
    python run_agent.py dev

    # Production
    python run_agent.py start

    # Download required model files (silero VAD, turn-detector) on first run
    python run_agent.py download-files

Environment variables required (see .env.example):
    LIVEKIT_URL          wss://your-livekit-server.com
    LIVEKIT_API_KEY      your LiveKit API key
    LIVEKIT_API_SECRET   your LiveKit API secret
    OPENAI_API_KEY       your OpenAI API key
    DEEPGRAM_API_KEY     your Deepgram API key
"""

from dotenv import load_dotenv

load_dotenv()  # Load .env before importing agent modules that read settings

from livekit import agents
from agent.core import server

if __name__ == "__main__":
    agents.cli.run_app(server)
