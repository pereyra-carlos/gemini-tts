"""
Compara 3 modelos TTS de Gemini con la misma voz (Aoede) y frase:
- gemini-3.1-flash-tts-preview    (baseline, el que venimos usando)
- gemini-2.5-flash-preview-tts    (candidato barato)
- gemini-2.5-pro-preview-tts      (candidato calidad)

Output: out/models_<ts>/<modelo>.wav + tabla de tokens/latencia.
"""
import os
import time
import wave
import datetime as dt
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
]
VOICE = "Aoede"
TEXT = ("Dale, te paso el resumen: el deploy salió bien, los pods están healthy "
        "y la métrica de latencia bajó un veinte por ciento desde ayer.")

N_RUNS = 2  # reducido para no bancar mucho


def synth(client, model, text):
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)
                )
            ),
        ),
    )
    latency = time.perf_counter() - t0
    pcm = resp.candidates[0].content.parts[0].inline_data.data
    um = resp.usage_metadata
    return {
        "latency": latency,
        "pcm": pcm,
        "in_tok": um.prompt_token_count or 0,
        "out_tok": um.candidates_token_count or 0,
    }


def save_wav(pcm: bytes, path: Path):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
        wf.writeframes(pcm)


def main():
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent / "out" / f"models_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"voz={VOICE} texto={len(TEXT)} chars, {N_RUNS} runs c/u -> {out_dir}\n")
    print(f"{'modelo':<35} {'run':>3} {'e2e':>7} {'in/out tok':>12}")
    print("-" * 62)

    results = {}
    for model in MODELS:
        results[model] = []
        for i in range(N_RUNS):
            try:
                r = synth(client, model, TEXT)
                results[model].append(r)
                if i == 0:
                    save_wav(r["pcm"], out_dir / f"{model}.wav")
                print(f"{model:<35} {i+1:>3} {r['latency']:>6.2f}s {r['in_tok']:>5}/{r['out_tok']:<5}")
            except Exception as e:
                print(f"{model:<35} {i+1:>3} ERROR: {type(e).__name__}: {e}")

    print("\n=== Medianas ===")
    print(f"{'modelo':<35} {'e2e':>7} {'tok in/out':>12}")
    for model, runs in results.items():
        if not runs:
            print(f"{model:<35} sin resultados"); continue
        runs_ok = runs
        e2e = sum(r["latency"] for r in runs_ok) / len(runs_ok)
        in_t = runs_ok[0]["in_tok"]
        out_t = sum(r["out_tok"] for r in runs_ok) // len(runs_ok)
        print(f"{model:<35} {e2e:>6.2f}s {in_t:>5}/{out_t:<5}")

    print(f"\nAudios: {out_dir}")


if __name__ == "__main__":
    main()
