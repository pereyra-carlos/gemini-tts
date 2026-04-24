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

## Estado

- [ ] Confirmar nombre exacto del modelo en `list_models.py`
- [ ] Generar primer audio rioplatense
- [ ] Comparar voces femeninas
- [ ] (futuro) integrar como alternativa a `whisper-tts` en `clau`
