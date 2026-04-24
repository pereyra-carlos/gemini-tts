# gemini-tts

Lab para probar **Gemini 3.1 Flash TTS Preview** (`gemini-3.1-flash-tts-preview`).

Modelo nuevo de Google (release abr 2026): low-latency speech generation, steerable prompts, expressive audio tags.
Pricing: input $1/M tok, output $20/M tok.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # pegar la GOOGLE_API_KEY del rag (k8s secret rag-secrets/rag-multimodal)
```

Para reusar la key del RAG:
```bash
kubectl get secret rag-secrets -n rag-multimodal -o jsonpath='{.data.GOOGLE_API_KEY}' | base64 -d
```

## Scripts

- `list_models.py` — lista modelos disponibles, filtra los TTS. Sanity check primero.
- `test_tts.py` — genera audio de un texto rioplatense con voz femenina (default `Aoede`).
  - Override voz: `VOICE=Kore python test_tts.py`
  - Output: `out/<voice>_<ts>.wav` (PCM 24kHz mono 16-bit)

## Voces femeninas prebuilt de Gemini TTS

Aoede, Kore, Leda, Zephyr, Autonoe, Callirhoe, Despina.
(El acento rioplatense se induce con prompt — no hay voz "es-AR" específica.)

## Microservicio (service/)

Drop-in replacement de `whisper-tts` para clau. Mismo contrato HTTP, distinto backend.

- Imagen: `sauay/gemini-tts:0.1.0`
- K3s: ns `claude`, Deployment `gemini-tts` + Service ClusterIP
- DNS interno: `http://gemini-tts.claude.svc.cluster.local:8000` (desde mismo ns: `http://gemini-tts:8000`)
- Backend: `gemini-2.5-flash-preview-tts` + voz `Aoede` (overrides por env)
- Formato: OGG Opus mono 24kHz (idéntico a whisper-tts, compatible con WA voice notes)

### Deploy

```bash
# Build + push
cd service/
docker build -t sauay/gemini-tts:0.1.0 -t sauay/gemini-tts:latest .
docker push sauay/gemini-tts:0.1.0 && docker push sauay/gemini-tts:latest

# Secret (reusa la key del RAG)
KEY=$(kubectl get secret rag-secrets -n rag-multimodal -o jsonpath='{.data.GOOGLE_API_KEY}' | base64 -d)
kubectl create secret generic gemini-tts-secret -n claude \
  --from-literal=GOOGLE_API_KEY="$KEY" --dry-run=client -o yaml | kubectl apply -f -

# Manifests
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
```

### Cómo clau usa el TTS

El TTS saliente de clau NO pasa por `/tts` del ws-router: lo genera el propio pod `claude` (claupod) vía la skill `audio-tts` (en NFS `/workspace/.claude/skills/audio-tts/SKILL.md`). La skill hace `curl` contra `$TTS_URL` y `$TTS_FILES_URL`, env vars seteadas en el deployment `claude`.

Copia de referencia de la skill en este repo: `service/audio-tts-SKILL.md`.

### Switchear backend

Un solo comando, sin tocar la skill:

```bash
# Activar gemini-tts (default actual, voz Aoede rioplatense):
kubectl set env deploy/claude -n claude \
  TTS_URL=http://gemini-tts.claude.svc.cluster.local:8000/tts \
  TTS_FILES_URL=http://gemini-tts.claude.svc.cluster.local:8000/files

# Rollback a whisper-tts (voz Daniela Piper, local en AI Server):
kubectl set env deploy/claude -n claude \
  TTS_URL=http://192.168.0.101:8000/tts \
  TTS_FILES_URL=http://192.168.0.101:8000/files

# Rollout en cualquier caso:
kubectl rollout restart deploy/claude -n claude
```

### Test rápido

```bash
kubectl port-forward -n claude svc/gemini-tts 8002:8000 &
curl -s http://127.0.0.1:8002/health
curl -s -X POST http://127.0.0.1:8002/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"hola carlos"}'
```

## Estado

- [x] Confirmar nombre exacto del modelo en `list_models.py`
- [x] Generar primer audio rioplatense
- [x] Comparar voces femeninas (Aoede/Autonoe preferidas)
- [x] Microservicio drop-in deployado en K3s (ns claude)
- [ ] Activar switch en ws-router (pendiente decisión de Carlos)
- [ ] Monitoreo semanal de gasto en panel AI Studio
