"""
Genera audio con Gemini 3.1 Flash TTS Preview.

Voz femenina, acento rioplatense (vía steerable prompt).
Output: out/<voice>_<timestamp>.wav (PCM 24kHz mono 16-bit)
"""
import os
import sys
import wave
import datetime as dt
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL = "gemini-3.1-flash-tts-preview"

# Voces femeninas prebuilt de Gemini TTS — Aoede suele ser la más neutra/cálida.
# Otras femeninas para probar: Kore, Leda, Zephyr, Autonoe, Callirhoe, Despina.
VOICE = os.environ.get("VOICE", "Aoede")

# Steerable prompt: el modelo 3.1 acepta instrucciones de estilo en el propio texto.
TEXT = """Decilo con acento rioplatense argentino, voz femenina natural, tono cálido y relajado, como charlando con un amigo:

Hola Carlos, ¿qué tal? Acá estoy, probando Gemini 3.1 Flash TTS desde el laboratorio. A ver qué tal me sale el porteño, viste. Si suena bien, después armamos algo más copado."""


def main():
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    print(f"[gemini-tts] modelo={MODEL} voz={VOICE}")
    print(f"[gemini-tts] texto ({len(TEXT)} chars):\n  {TEXT[:120]}...\n")

    response = client.models.generate_content(
        model=MODEL,
        contents=TEXT,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE,
                    )
                )
            ),
        ),
    )

    audio = response.candidates[0].content.parts[0].inline_data.data
    print(f"[gemini-tts] recibidos {len(audio)} bytes de PCM")

    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{VOICE.lower()}_{ts}.wav"

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(24000)
        wf.writeframes(audio)

    dur = len(audio) / (24000 * 2)
    print(f"[gemini-tts] OK -> {out_path} ({dur:.1f}s)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[gemini-tts] ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
