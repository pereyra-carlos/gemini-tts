---
name: audio-tts
description: Convierte texto a audio y lo envía como voice note por el canal actual (Telegram o WhatsApp). Backend parametrizado via env `TTS_URL` (default gemini-tts con voz Aoede rioplatense). Usala cuando el modo audio esta ON (respondes cada turno con audio), cuando Carlos pida "respondeme en audio", "mandame un audio con X", o para confirmaciones cortas auditivas. Tambien cuando otra skill (ej. `/audio-mode`) necesite emitir una respuesta hablada.
---

## Que hace

Genera un `.ogg` Opus con el texto usando el backend TTS configurado (`$TTS_URL`), le agrega 1s de silencio al inicio (workaround corte de Telegram), lo sube al message-fileserver y responde con `MEDIA:<url>` para que el canal (TG o WA) descargue y envie como voice note.

**Un solo patron para los dos canales** — la skill no distingue TG vs WA. Tanto gateway.py (TG) como ws-router (WA) aceptan URLs http en `MEDIA:<url>` y hacen el fetch del archivo.

## Pasos (todos obligatorios, en orden)

```bash
# 1. TTS (pega al backend configurado en el pod)
RESP=$(curl -s -X POST "${TTS_URL:-http://gemini-tts.claude.svc.cluster.local:8000/tts}" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "TEXTO_AQUI")")
FNAME=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['audio_path'].rsplit('/',1)[-1])")

# 2. Descarga el .ogg generado
curl -s -o /tmp/tts_raw.ogg "${TTS_FILES_URL:-http://gemini-tts.claude.svc.cluster.local:8000/files}/$FNAME"

# 3. Prepend 1s de silencio (evita que Telegram corte la primera silaba)
ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a libopus /tmp/silence.ogg 2>/dev/null
ffmpeg -y -i /tmp/silence.ogg -i /tmp/tts_raw.ogg \
  -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1" \
  -c:a libopus /tmp/tts_out.ogg 2>/dev/null

# 4. Upload al message-fileserver
UP=$(curl -s -F "file=@/tmp/tts_out.ogg" http://message-fileserver.claude.svc.cluster.local:8100/upload)
UP_FNAME=$(echo "$UP" | python3 -c "import sys,json; print(json.load(sys.stdin)['filename'])")

# 5. Construi la URL publica (NodePort 30815 del fileserver)
echo "http://192.168.0.101:30815/media/$UP_FNAME"
```

## Como responder

Al final de tu respuesta de texto, agrega **en una linea aparte** el marker:

```
MEDIA:http://192.168.0.101:30815/media/<UP_FNAME>
```

Ejemplo de respuesta completa:
```
Acá va el resumen!

MEDIA:http://192.168.0.101:30815/media/a3f5b8.ogg
```

- gateway.py (Telegram) y ws-router (WhatsApp) detectan `MEDIA:<url>`, descargan el archivo y lo mandan como voice note.
- **NUNCA** uses `MEDIA:/tmp/...` (path local) — no funciona en WA y ahora tampoco es necesario en TG.

## Backends soportados

| Backend | TTS_URL | Voz | Notas |
|---------|---------|-----|-------|
| **gemini-tts** (default) | `http://gemini-tts.claude.svc.cluster.local:8000/tts` | Aoede | Gemini 2.5 Flash TTS, acento rioplatense natural |
| whisper-tts (fallback) | `http://192.168.0.101:8000/tts` | Daniela Piper | Local en AI Server, más rápido, más barato |

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

# Rollout:
kubectl rollout restart deploy/claude -n claude
```

## Estilo del texto

- **Frases cortas**, naturales. Evitar listas, markdown, headers.
- Voseo y muletillas rioplatenses ("che", "viste", "dale", "mira") inducen mejor acento porteño en Gemini.
- Si el texto tiene codigo o link, reemplazalo por una referencia hablada ("te mande el link aparte") y mandalo en texto separado.
- Maximo ~300 palabras por audio; si es mas, partilo en 2-3 mensajes.

## Cuando NO usarla

- Contenido estructurado (codigo, JSON, tablas) — texto es mejor.
- Carlos esta en lugar sin audio (chequea si dijo "estoy en reunion").
- Dentro de una respuesta de texto como complemento — elegi uno solo.
