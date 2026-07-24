"""
Génération de titres de conversation courts, via un appel LLM léger.

Remplace le titre par défaut (premier message tronqué) par un vrai résumé,
comme le fait Claude.ai — plutôt qu'une simple troncature de texte.

Appelé UNE SEULE FOIS par conversation, juste après le tout premier
échange (voir main.py) — jamais sur les messages suivants. Pas de coût
récurrent, juste un petit surcoût à la création de chaque nouvelle
conversation.
"""

from ai_client import ask_groq

TITLE_SYSTEM_PROMPT = (
    "Tu résumes une conversation en un titre court et clair, 3 à 6 mots, "
    "en français, sans guillemets, sans point final, sans préambule "
    "('Voici le titre :' etc). Réponds UNIQUEMENT avec le titre, rien d'autre."
)


async def generate_title(user_message: str, assistant_reply: str) -> str:
    messages = [
        {"role": "system", "content": TITLE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Message : {user_message}\n\nRéponse : {assistant_reply[:300]}",
        },
    ]
    title = await ask_groq(messages, temperature=0.3)
    # Nettoyage défensif : au cas où le modèle ajoute des guillemets ou un point.
    title = title.strip().strip('"').strip("«»").strip().rstrip(".")
    return title[:60]
