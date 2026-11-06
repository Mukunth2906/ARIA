"""
backend/utils/stt.py — Speech-to-Text (STT) Engine for ARIA
Provides voice transcription using Whisper STT with Gemini audio fallback.

Supported providers:
  1. OpenAI Whisper API (model: whisper-1) via OPENAI_API_KEY
  2. Google Gemini Audio Transcription via GEMINI_API_KEY
"""
import logging
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """
    Transcribes audio bytes into text.

    Parameters
    ----------
    audio_bytes : bytes
        Raw binary data of the audio file.
    filename : str
        Original filename or a placeholder with correct extension (.wav, .mp3, etc.)

    Returns
    -------
    str
        Transcribed plain text of the spoken words.
    """
    if not audio_bytes:
        raise ValueError("Audio data is empty.")

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    # ── 1. OpenAI Whisper STT (Primary) ─────────────────────────────────────────
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)

            ext = os.path.splitext(filename)[1] or ".wav"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                with open(tmp_path, "rb") as f:
                    transcription = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                    )
                text = transcription.text.strip()
                logger.info(f"Whisper STT transcription successful: {text[:60]}...")
                return text
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as e:
            logger.warning(f"OpenAI Whisper transcription failed: {e}. Trying fallback if available.")
            if not gemini_key:
                raise e

    # ── 2. Google Gemini Multimodal Audio (Fallback) ───────────────────────────
    if gemini_key:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gemini_key)

        mime_type = "audio/wav"
        lower_name = filename.lower()
        if lower_name.endswith(".mp3"):
            mime_type = "audio/mp3"
        elif lower_name.endswith(".m4a"):
            mime_type = "audio/m4a"
        elif lower_name.endswith(".ogg") or lower_name.endswith(".webm"):
            mime_type = "audio/ogg"

        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=mime_type,
                ),
                (
                    "You are a Speech-to-Text transcriber. Transcribe this audio recording "
                    "accurately word-for-word. Return ONLY the transcribed text without any "
                    "commentary, markdown backticks, or preamble."
                )
            ],
        )
        text = response.text.strip() if response.text else ""
        logger.info(f"Gemini Audio transcription successful: {text[:60]}...")
        return text

    raise EnvironmentError(
        "No STT API key configured in .env!\n"
        "Please configure at least one of:\n"
        "  - OPENAI_API_KEY (for Whisper STT)\n"
        "  - GEMINI_API_KEY (for Gemini audio transcription)"
    )

