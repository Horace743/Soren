"""
Génération d'images, via Hugging Face Inference Providers.

Contrairement au chat texte (une simple API OpenAI-compatible), la
génération d'image chez HF est routée vers différents fournisseurs
(fal-ai, Replicate...) selon le modèle, avec des formats de réponse qui
varient. Plutôt que deviner ce format à la main comme pour le chat, on
utilise ici la librairie officielle `huggingface_hub`, qui abstrait ça
proprement — plus robuste, maintenue directement par HF.

Déclenchement : commande explicite `/image <description>` tapée par
l'utilisateur (voir main.py) — pas de détection automatique d'intention,
pour rester prévisible et contrôlable, comme décidé.
"""

import os
import base64
from io import BytesIO
from huggingface_hub import AsyncInferenceClient

# FLUX.1-schnell : rapide (1 à 4 étapes d'inférence), licence Apache 2.0,
# bien adapté à un usage gratuit et rate-limité comme le nôtre.
# FLUX.1-dev est plus qualitatif mais nettement plus lent et sous licence
# non-commerciale — pas le bon choix ici.
IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell"

# Préfixe qui marque un message comme étant une image (data URL base64)
# plutôt que du texte normal. Utilisé à la fois pour le stockage en DB et
# pour la détection côté frontend (voir app.js).
IMAGE_MARKER = "@@SOREN_IMAGE@@"


async def generate_image(prompt: str) -> str:
    """Génère une image et retourne une data URL base64 (utilisable
    directement dans un <img src="...">, pas de stockage de fichier séparé
    nécessaire — l'image vit entièrement dans la base Postgres)."""
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise RuntimeError(
            "HF_TOKEN manquante. La génération d'image nécessite un token "
            "Hugging Face (huggingface.co/settings/tokens)."
        )

    client = AsyncInferenceClient(api_key=hf_token)
    image = await client.text_to_image(prompt, model=IMAGE_MODEL)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"
