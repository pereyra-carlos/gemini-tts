"""
Benchmark: Gemini 3.1 Flash TTS (Aoede) vs whisper-tts local (es_AR-daniela-high).

3 frases (corta / media / larga) × N runs × 2 backends.
Métricas: latencia e2e (wall clock), duración del audio generado, tokens (Gemini),
costo estimado (Gemini). whisper-tts corre local en AI Server 3090 -> costo marginal.

Pricing Gemini 3.1 Flash TTS Preview (abr 2026):
  Input:  $ 1 / M tokens
  Output: $20 / M tokens
"""
import os
import sys
import time
import wave
import json
import statistics as stats
import urllib.request
from pathlib import Path
from io import BytesIO

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
GEMINI_VOICE = "Aoede"
WHISPER_BASE = "http://192.168.0.101:8000"

N_RUNS = 3

PHRASES = {
    "corta":  "Che Carlos, ¿estás ahí? Decime algo.",
    "media":  ("Dale, te paso el resumen: el deploy salió bien, los pods están healthy "
               "y la métrica de latencia bajó un veinte por ciento desde ayer."),
    "larga":  ("Mirá, te cuento cómo quedó todo. El cluster K3s está estable, los tres "
               "workers con el kubelet al día, y el Ingress NGINX ya tiene los "
               "certificados renovados hasta septiembre. Del lado de las apps, migré "
               "clau al nuevo namespace y el RAG multimodal sigue sirviendo sin downtime. "
               "Lo único pendiente es revisar el backup de Qdrant, pero lo dejo para "
               "mañana que no es urgente."),
}

OUT_DIR = Path(__file__).parent / "out" / "benchmark"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def pcm_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def wav_duration(wav_bytes: bytes) -> float:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def ogg_duration_via_header(ogg_bytes: bytes) -> float:
    # Para OGG/Opus preferiría ffprobe, pero evitar dep externa:
    # whisper-tts reporta tts_time_s en la respuesta; la duración del audio
    # la pedimos con una pasada rápida de wave si fuera wav. Para ogg usamos
    # un aprox por ratio (ogg opus ~ 32 kbps -> 4 KB/s). Aprox no crítico.
    return len(ogg_bytes) / 4000.0


class GeminiClient:
    def __init__(self):
        self.c = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def synth(self, text: str):
        t0 = time.perf_counter()
        resp = self.c.models.generate_content(
            model=GEMINI_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_VOICE,
                        )
                    )
                ),
            ),
        )
        latency = time.perf_counter() - t0
        pcm = resp.candidates[0].content.parts[0].inline_data.data
        wav = pcm_to_wav(pcm)
        um = resp.usage_metadata
        return {
            "latency_s": latency,
            "audio_bytes": wav,
            "audio_dur_s": wav_duration(wav),
            "ext": "wav",
            "in_tokens": um.prompt_token_count or 0,
            "out_tokens": (um.candidates_token_count or 0),
            "total_tokens": um.total_token_count or 0,
        }


class WhisperClient:
    def __init__(self, base=WHISPER_BASE):
        self.base = base

    def synth(self, text: str):
        t0 = time.perf_counter()
        req = urllib.request.Request(
            f"{self.base}/tts",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            meta = json.loads(r.read())
        fname = Path(meta["audio_path"]).name
        with urllib.request.urlopen(f"{self.base}/files/{fname}", timeout=30) as r:
            audio = r.read()
        latency = time.perf_counter() - t0
        return {
            "latency_s": latency,
            "tts_time_s_gpu": meta.get("tts_time_s"),
            "audio_bytes": audio,
            "audio_dur_s": ogg_duration_via_header(audio),
            "ext": "ogg",
            "chars": meta.get("characters"),
        }


def cost_gemini(in_tok: int, out_tok: int) -> float:
    return in_tok * 1.0 / 1_000_000 + out_tok * 20.0 / 1_000_000


def run():
    g = GeminiClient()
    w = WhisperClient()

    results = {}  # {phrase: {backend: [runs]}}

    for name, text in PHRASES.items():
        print(f"\n=== Frase '{name}' ({len(text)} chars) ===")
        print(f"  {text[:100]}{'...' if len(text) > 100 else ''}")
        results[name] = {"gemini": [], "whisper": []}

        for i in range(N_RUNS):
            for label, cli in (("gemini", g), ("whisper", w)):
                try:
                    r = cli.synth(text)
                    results[name][label].append(r)
                    if i == 0:  # guardar muestra solo del primer run
                        (OUT_DIR / f"{name}_{label}.{r['ext']}").write_bytes(r["audio_bytes"])
                    extra = ""
                    if label == "gemini":
                        extra = f" tok={r['in_tokens']}+{r['out_tokens']}"
                    elif r.get("tts_time_s_gpu") is not None:
                        extra = f" gpu={r['tts_time_s_gpu']:.2f}s"
                    print(f"  run {i+1} {label:<8} e2e={r['latency_s']:5.2f}s "
                          f"audio={r['audio_dur_s']:4.1f}s{extra}")
                except Exception as e:
                    print(f"  run {i+1} {label:<8} ERROR: {type(e).__name__}: {e}")

    # Resumen
    print("\n\n=== RESUMEN (medianas) ===\n")
    hdr = f"{'Frase':<7} {'Backend':<9} {'e2e':>7} {'audio':>7} {'RTF':>6} {'tok in/out':>14} {'$/1k reqs':>11}"
    print(hdr); print("-" * len(hdr))
    for name, per in results.items():
        for label in ("gemini", "whisper"):
            runs = per[label]
            if not runs:
                print(f"{name:<7} {label:<9} ERROR en todos los runs"); continue
            e2e_med = stats.median(r["latency_s"] for r in runs)
            dur_med = stats.median(r["audio_dur_s"] for r in runs)
            rtf = e2e_med / dur_med if dur_med else 0
            if label == "gemini":
                in_tok = stats.median(r["in_tokens"] for r in runs)
                out_tok = stats.median(r["out_tokens"] for r in runs)
                cost_per_1k = cost_gemini(in_tok, out_tok) * 1000
                tok_str = f"{int(in_tok)}/{int(out_tok)}"
                cost_str = f"${cost_per_1k:>8.3f}"
            else:
                tok_str = "-"; cost_str = "local/~0"
            print(f"{name:<7} {label:<9} {e2e_med:>6.2f}s {dur_med:>6.1f}s {rtf:>5.2f}x {tok_str:>14} {cost_str:>11}")

    print(f"\nMuestras de audio: {OUT_DIR}")
    print("RTF = real-time factor (tiempo de síntesis / duración del audio). <1x = más rápido que tiempo real.")


if __name__ == "__main__":
    run()
