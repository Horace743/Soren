"""
Module Fusionneur (étape 4).

Comme discuté au tout début du projet : plutôt que de coder à la main la
détection de doublons/contradictions entre plusieurs réponses IA, on
délègue cette tâche à un LLM qui joue le rôle de "juge" — il reçoit les
réponses candidates et produit une synthèse finale unique.

Ce module ne fait AUCUN appel réseau lui-même : il construit juste le
prompt de fusion. L'appel effectif est fait depuis ai_client.py, en
réutilisant l'une des fonctions provider existantes (ask_groq, etc.) comme
juge — pas de dépendance circulaire.
"""

FUSION_SYSTEM_PROMPT = """Tu es un synthétiseur de réponses IA.

Tu reçois plusieurs réponses candidates, générées par différents modèles, à la même question d'un utilisateur.

Ta tâche :
- Produis UNE SEULE réponse finale, qui combine les meilleures idées des candidates.
- Élimine les répétitions et redondances entre les candidates.
- Si les candidates se contredisent sur un fait, tranche en faveur de la version la plus précise et cohérente — ne laisse jamais une contradiction non résolue dans ta réponse finale.
- Les candidates ont déjà un ton chambreur, direct et plein de caractère (personnage "Soren"). Conserve ce ton dans ta synthèse — ne le réécris JAMAIS dans un style neutre ou corporate.
- Ne mentionne JAMAIS explicitement qu'il s'agit d'une fusion de plusieurs réponses, ni le nombre de candidates, ni le nom d'un quelconque modèle. L'utilisateur ne doit jamais savoir qu'il y a plusieurs IA derrière — pour lui, il n'y a qu'une seule voix : Soren.
- Réponds uniquement avec le texte final. Pas de préambule ("Voici la synthèse :", "Après analyse..."), pas de balises, pas de méta-commentaire sur ta tâche.
"""


def build_fusion_messages(user_message: str, candidates: list[str]) -> list[dict]:
    candidate_block = "\n\n".join(
        f"--- Réponse candidate {i + 1} ---\n{c}" for i, c in enumerate(candidates)
    )
    user_content = (
        f"Question originale de l'utilisateur :\n{user_message}\n\n"
        f"Réponses candidates à fusionner :\n\n{candidate_block}"
    )
    return [
        {"role": "system", "content": FUSION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
