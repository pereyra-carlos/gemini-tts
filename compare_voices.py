"""
Compara las 7 voces femeninas prebuilt de Gemini 3.1 Flash TTS con el mismo texto.

Diferencias vs test_tts.py:
- Sin instrucción de estilo textual (el TTS no soporta system_instruction).
  El voseo y las muletillas rioplatenses ("dale", "viste", "che") inducen el
  acento porteño por sí solas.
- El texto a leer usa audio tags expresivos del 3.1: [amused], [laughs], [sigh], etc.

Output: out/compare_<ts>/<voice>.wav (PCM 24kHz mono 16-bit)
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

# Voces femeninas prebuilt de Gemini TTS.
VOICES = ["Aoede", "Kore", "Leda", "Zephyr", "Autonoe", "Callirhoe", "Despina"]

TEXT = (
    "[amused] ¡Eeeh, hola Carlos! ¿Cómo andás, che? [laughs] "
    "Mirá, acá estoy probando Gemini 3.1 Flash TTS con las siete voces, "
    "a ver cuál te gusta más, viste. [thoughtful] "
    "Vos escuchalas de a una y elegí la que mejor te pinte para clau. "
    "[excited] ¡Dale que va, esto está buenísimo!"
)


def synth(client: genai.Client, voice: str, out_path: Path) -> float:
    response = client.models.generate_content(
        model=MODEL,
        contents=TEXT,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice,
                    )
                )
            ),
        ),
    )
    audio = response.candidates[0].content.parts[0].inline_data.data
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio)
    return len(audio) / (24000 * 2)


def main():
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent / "out" / f"compare_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[compare] modelo={MODEL} voces={len(VOICES)} -> {out_dir}")
    print(f"[compare] texto: {TEXT[:90]}...\n")

    for i, voice in enumerate(VOICES, 1):
        out_path = out_dir / f"{i:02d}_{voice.lower()}.wav"
        try:
            dur = synth(client, voice, out_path)
            print(f"  [{i}/{len(VOICES)}] {voice:<12} -> {out_path.name} ({dur:.1f}s)")
        except Exception as e:
            print(f"  [{i}/{len(VOICES)}] {voice:<12} ERROR: {type(e).__name__}: {e}")

    print(f"\n[compare] listo. Reproducí con:")
    print(f"  for f in {out_dir}/*.wav; do echo \"== $f ==\"; ffplay -nodisp -autoexit -loglevel quiet \"$f\"; done")


if __name__ == "__main__":
    main()
