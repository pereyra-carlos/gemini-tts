"""Lista los modelos disponibles en la cuenta AI Studio, filtrando los TTS."""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

print("=== Modelos con 'tts' en el nombre ===")
for m in client.models.list():
    name = m.name.replace("models/", "")
    if "tts" in name.lower():
        methods = ",".join(getattr(m, "supported_actions", []) or [])
        print(f"  {name:<45} methods=[{methods}]")

print("\n=== Todos los modelos (nombre solo) ===")
for m in client.models.list():
    print(" ", m.name.replace("models/", ""))
