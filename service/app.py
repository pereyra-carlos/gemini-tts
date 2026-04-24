"""
gemini-tts — microservicio TTS drop-in compatible con whisper-tts.

Contrato emulado (el ws-router no tiene que cambiar nada):
  POST /tts     JSON {text, voice?, speed?}  -> JSON {audio_path, characters, tts_time_s, ...}
  GET  /files/{filename}                     -> binary OGG
  GET  /health                               -> liveness

Backend: Gemini 2.5 Flash Preview TTS (default), voz Aoede (default).
Conversión PCM 24kHz/16-bit/mono -> OGG Opus via ffmpeg (mismo formato que whisper-tts).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from google import genai
from google.genai import types


# ── Settings ─────────────────────────────────────────────────────────────────
MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICE_DEFAULT = os.getenv("GEMINI_TTS_VOICE", "Aoede")
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "/audio"))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Voces prebuilt conocidas de Gemini TTS (subset femeninas validadas).
# Si el client pide algo que no está en esta lista (ej. 'es_AR-daniela-high'
# de whisper-tts), caemos al default sin romper.
KNOWN_VOICES = {"Aoede", "Kore", "Leda", "Zephyr", "Autonoe", "Despina",
                "Puck", "Charon", "Fenrir", "Orus"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemini-tts")

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY no configurada")
        _client = genai.Client(api_key=api_key)
    return _client


# ── Schemas (emulan whisper-tts) ─────────────────────────────────────────────
class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None           # whisper-tts manda "es_AR-daniela-high" (ignorado)
    speed: Optional[float] = None         # idem, ignorado por ahora
    voice_profile_id: Optional[str] = None  # compatibilidad whisper-tts nuevo
    speaking_rate: Optional[float] = None
    output_name: Optional[str] = None


class TTSResponse(BaseModel):
    request_id: str
    audio_path: str
    characters: int
    tts_time_s: float
    voice_profile_id: str
    speaking_rate: float


# ── Core ─────────────────────────────────────────────────────────────────────
def pick_voice(req: TTSRequest) -> str:
    """Si el cliente pide una voz válida de Gemini la usamos, si no default."""
    for candidate in (req.voice_profile_id, req.voice):
        if candidate and candidate in KNOWN_VOICES:
            return candidate
    return VOICE_DEFAULT


def synth_pcm(text: str, voice: str) -> bytes:
    """Llama Gemini TTS y devuelve PCM raw 24kHz/16-bit/mono."""
    client = get_client()
    resp = client.models.generate_content(
        model=MODEL,
        contents=text,
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
    return resp.candidates[0].content.parts[0].inline_data.data


def pcm_to_ogg(pcm: bytes, out_path: Path) -> None:
    """Convierte PCM 24kHz s16le mono -> OGG Opus usando ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
        "-c:a", "libopus", "-b:a", "32k",
        "-f", "ogg", str(out_path),
    ]
    p = subprocess.run(cmd, input=pcm, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.decode(errors='ignore')[:300]}")


def _sanitize_name(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    return safe or fallback


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="gemini-tts", version="0.1.0")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:8]
    return await call_next(request)


@app.get("/health")
def health():
    ok = "GOOGLE_API_KEY" in os.environ
    return {
        "status": "ok" if ok else "missing_api_key",
        "backend": "gemini",
        "model": MODEL,
        "voice_default": VOICE_DEFAULT,
        "audio_dir": str(AUDIO_DIR),
        "audio_dir_exists": AUDIO_DIR.exists(),
        "api_key_configured": ok,
    }


@app.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest, request: Request):
    rid = request.state.request_id
    voice = pick_voice(req)
    out_name = _sanitize_name(req.output_name, fallback=f"tts_{rid}")
    out_path = AUDIO_DIR / f"{out_name}.ogg"

    log.info("[%s] /tts chars=%d voice=%s model=%s",
             rid, len(req.text), voice, MODEL)

    t0 = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        pcm = await loop.run_in_executor(None, synth_pcm, req.text, voice)
        await loop.run_in_executor(None, pcm_to_ogg, pcm, out_path)
    except Exception as e:
        log.exception("[%s] TTS error", rid)
        raise HTTPException(500, f"{type(e).__name__}: {e}")

    elapsed = round(time.perf_counter() - t0, 2)
    log.info("[%s] TTS done in %.2fs -> %s (%d bytes)",
             rid, elapsed, out_path, out_path.stat().st_size)

    return TTSResponse(
        request_id=rid,
        audio_path=str(out_path),
        characters=len(req.text),
        tts_time_s=elapsed,
        voice_profile_id=voice,
        speaking_rate=req.speaking_rate or req.speed or 1.0,
    )


@app.get("/files/{filename}")
def download_file(filename: str):
    """Sirve OGG desde AUDIO_DIR con guardas anti-traversal."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400, "Invalid filename")
    file_path = (AUDIO_DIR / filename).resolve()
    try:
        file_path.relative_to(AUDIO_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Path outside allowed directory")
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )
