"""
Client d'appel aux LLM. Étape 3 : plusieurs providers connectés
(Groq, OpenRouter, Hugging Face), avec fallback automatique.

IMPORTANT — volatilité des modèles gratuits :
Les IDs de modèles gratuits (":free" sur OpenRouter, catalogue Hugging Face)
changent fréquemment, parfois sans préavis (on l'a déjà vécu avec Groq).
Chaque fonction ci-dessous lève une erreur explicite avec le nom du provider
si l'appel échoue — regarde le message d'erreur en premier si un provider
tombe en panne, il te dira lequel et pourquoi. Les modèles ci-dessous sont
vérifiés en juillet 2026 ; si l'un d'eux disparaît, il suffit de changer la
constante correspondante (GROQ_MODEL, OPENROUTER_MODEL, HF_MODEL).

`ask_ai()` en bas de fichier essaie les providers dans l'ordre et bascule
automatiquement sur le suivant en cas d'échec — c'est la fonction que le
reste du backend doit utiliser (pas les fonctions individuelles, sauf besoin
spécifique).
"""

import os
import asyncio
import httpx

from fusion import build_fusion_messages

# ============================================================
# Groq — le plus rapide, testé et fiable, en premier dans la chaîne
# ============================================================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq a déprécié llama-3.3-70b-versatile (annonce du 17 juin 2026).
GROQ_MODEL = "openai/gpt-oss-120b"


async def ask_groq(messages: list[dict], temperature: float = 0.8) -> str:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise RuntimeError(
            "[groq] GROQ_API_KEY manquante. Ajoute-la dans backend/.env "
            "(clé gratuite sur console.groq.com/keys)"
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GROQ_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"[groq] a répondu {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"]


# ============================================================
# OpenRouter — gateway vers ~28 modèles gratuits (rotation fréquente)
# ============================================================
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Vérifié gratuit en juillet 2026. Si 404/400 "model not found" : va sur
# openrouter.ai/models, filtre par "free", et remplace ci-dessous.
OPENROUTER_MODEL = "openai/gpt-oss-20b:free"


async def ask_openrouter(messages: list[dict], temperature: float = 0.8) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "[openrouter] OPENROUTER_API_KEY manquante. Ajoute-la dans backend/.env "
            "(clé gratuite sur openrouter.ai/keys, aucune carte requise)"
        )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(OPENROUTER_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"[openrouter] a répondu {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"]


# ============================================================
# Hugging Face — router unifié compatible OpenAI (Inference Providers)
# ============================================================
HF_URL = "https://router.huggingface.co/v1/chat/completions"
# Modèle conversationnel généraliste, sans balises de raisonnement <think>
# (contrairement à DeepSeek-R1 ou Qwen3-Thinking, à éviter ici).
HF_MODEL = "Qwen/Qwen2.5-7B-Instruct-1M"


async def ask_huggingface(messages: list[dict], temperature: float = 0.8) -> str:
    api_key = os.getenv("HF_TOKEN")
    if not api_key:
        raise RuntimeError(
            "[huggingface] HF_TOKEN manquante. Ajoute-la dans backend/.env "
            "(token gratuit sur huggingface.co/settings/tokens, coche "
            "'Make calls to Inference Providers')"
        )

    payload = {
        "model": HF_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(HF_URL, json=payload, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"[huggingface] a répondu {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"]


# ============================================================
# Routeur avec fallback automatique — LE point d'entrée à utiliser
# ============================================================
# Ordre : Groq (rapide, fiable) -> OpenRouter -> Hugging Face.
# Si un provider échoue (clé manquante, modèle disparu, rate limit,
# timeout...), le suivant prend le relais automatiquement. L'utilisateur
# ne voit une erreur que si LES TROIS ont échoué.
PROVIDER_CHAIN = [
    ("groq", ask_groq),
    ("openrouter", ask_openrouter),
    ("huggingface", ask_huggingface),
]


async def ask_ai(messages: list[dict], temperature: float = 0.8) -> str:
    errors = []

    for name, provider_fn in PROVIDER_CHAIN:
        try:
            return await provider_fn(messages, temperature)
        except Exception as e:
            errors.append(str(e))
            continue

    details = " | ".join(errors)
    raise RuntimeError(
        f"Les {len(PROVIDER_CHAIN)} providers IA ont échoué. Détails : {details}"
    )


# ============================================================
# Fusion (étape 4) — appelle tous les providers en parallèle,
# fusionne leurs réponses via un LLM-juge si plusieurs ont réussi.
# ============================================================
PROVIDERS_BY_NAME = dict(PROVIDER_CHAIN)


async def _call_provider_safe(name: str, provider_fn, messages: list[dict], temperature: float):
    """Ne lève jamais d'exception : retourne (name, texte, None) ou (name, None, erreur)."""
    try:
        result = await provider_fn(messages, temperature)
        return name, result, None
    except Exception as e:
        return name, None, str(e)


async def ask_ai_fused(messages: list[dict], user_message: str, temperature: float = 0.8) -> str:
    """
    Appelle tous les providers disponibles EN PARALLÈLE (pas en séquence comme
    ask_ai). Si plusieurs répondent avec succès, un LLM-juge fusionne leurs
    réponses en une seule. Si un seul répond, on le retourne directement (pas
    besoin de fusionner une seule candidate). Si aucun ne répond, on lève une
    erreur, comme ask_ai.
    """
    results = await asyncio.gather(
        *(_call_provider_safe(name, fn, messages, temperature) for name, fn in PROVIDER_CHAIN)
    )

    successes = [(name, text) for name, text, err in results if text is not None]
    errors = [(name, err) for name, text, err in results if err is not None]

    if not successes:
        details = " | ".join(f"{name}: {err}" for name, err in errors)
        raise RuntimeError(
            f"Les {len(PROVIDER_CHAIN)} providers IA ont échoué. Détails : {details}"
        )

    if len(successes) == 1:
        return successes[0][1]

    # Plusieurs candidates : on fusionne. Le juge est de préférence Groq
    # (le plus rapide), sinon le premier provider qui a réussi.
    candidates = [text for _, text in successes]
    success_names = [name for name, _ in successes]
    judge_name = "groq" if "groq" in success_names else success_names[0]
    judge_fn = PROVIDERS_BY_NAME[judge_name]

    fusion_messages = build_fusion_messages(user_message, candidates)

    try:
        return await judge_fn(fusion_messages, 0.6)
    except Exception:
        # Le juge lui-même a échoué (rare, vu qu'il vient de répondre) :
        # on retombe sur la première candidate plutôt que de tout perdre.
        return candidates[0]
