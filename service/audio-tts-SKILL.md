---
name: audio-tts
description: Convierte texto a audio y lo manda como voice note. Backend parametrizado via env `TTS_URL` (default gemini-tts con voz Aoede rioplatense). Usala cuando el modo audio esta ON (respondes cada turno con audio), cuando Carlos pida "respondeme en audio", "mandame un audio con X", o para mandar confirmaciones cortas auditivas. Tambien cuando otra skill (ej. `/audio-mode`) necesite emitir una respuesta hablada.
---

## Que hace

Genera un `.ogg` Opus con el texto usando el backend TTS configurado en el pod (`$TTS_URL`), le agrega 1s de silencio al inicio (evita que Telegram corte la primera silaba) y lo envia como voice note.

El backend es intercambiable sin editar esta skill — cambia las env del pod `claude` y hace rollout restart (ver "Switchear backend" al final).

## Pasos

1. **Pedi la sintesis al endpoint TTS**:
   ```bash
   RESP=$(curl -s -X POST "${TTS_URL:-http://gemini-tts.claude.svc.cluster.local:8000/tts}" \
     -H 'Content-Type: application/json' \
     -d '{"text": "TEXTO_AQUI"}')
   FNAME=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['audio_path'].rsplit('/',1)[-1])")
   ```
   La respuesta JSON tiene `audio_path` con la ruta *dentro del container del svc*; usa el basename.

2. **Descarga el .ogg**:
   ```bash
   curl -s -o /tmp/tts_raw.ogg "${TTS_FILES_URL:-http://gemini-tts.claude.svc.cluster.local:8000/files}/$FNAME"
   ```

3. **Prepende 1s de silencio** (workaround a corte de primera silaba en Telegram):
   ```bash
   ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a libopus /tmp/silence.ogg 2>/dev/null
   ffmpeg -y -i /tmp/silence.ogg -i /tmp/tts_raw.ogg \
     -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1" \
     -c:a libopus /tmp/tts_out.ogg 2>/dev/null
   ```

4. **Envia el audio** segun el canal (el mismo que del mensaje entrante):
   - **Telegram**: responde con `MEDIA:/tmp/tts_out.ogg` en el texto — gateway.py lo detecta, lee el archivo del FS local y lo manda como voice note.
   - **WhatsApp**: subi el archivo al message-fileserver y responde con `MEDIA:<url-publica>` (el ws-router hace el fetch). Ver skill `messaging` para el upload.

## Backends soportados

| Backend | TTS_URL                                                          | Voz          | Notas |
|---------|------------------------------------------------------------------|--------------|-------|
| **gemini-tts** (default) | `http://gemini-tts.claude.svc.cluster.local:8000/tts` | Aoede | Gemini 2.5 Flash TTS, acento rioplatense natural |
| whisper-tts (fallback)   | `http://192.168.0.101:8000/tts`                                  | Daniela Piper | Local en AI Server, mas rapido, voz mas plana |

Ambos exponen el mismo contrato HTTP (`/tts` + `/files/{name}`). La skill no necesita saber cual esta activo.

## Switchear backend (operativa)

```bash
# A gemini-tts (default):
kubectl set env deploy/claude -n claude \
  TTS_URL=http://gemini-tts.claude.svc.cluster.local:8000/tts \
  TTS_FILES_URL=http://gemini-tts.claude.svc.cluster.local:8000/files

# A whisper-tts (fallback local, si el gasto de Gemini se dispara):
kubectl set env deploy/claude -n claude \
  TTS_URL=http://192.168.0.101:8000/tts \
  TTS_FILES_URL=http://192.168.0.101:8000/files

# Rollout para tomar el env nuevo:
kubectl rollout restart deploy/claude -n claude
```

Esta skill NO cambia al switchear. Copia de referencia en `service/audio-tts-SKILL.md` del repo gemini-tts; vive en el claupod en `/workspace/.claude/skills/audio-tts/SKILL.md`.
