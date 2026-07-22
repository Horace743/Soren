"""
AI Orchestrator - Backend principal
Persistance Postgres (Supabase) — les conversations survivent aux
redémarrages ET aux redéploiements (contrairement à SQLite sur un disque
éphémère d'hébergeur gratuit).

Architecture :
- `db.py` isole la persistance (Postgres / asyncpg)
- `ai_client.py` isole les appels aux providers + fallback + fusion
- `personality.py` isole le system prompt ("dictionnaire de personnalité")
- `rate_limit.py` isole la protection contre le spam / l'abus de quota
- `main.py` ne fait que router les requêtes HTTP
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from pathlib import Path
from dotenv import load_dotenv

from ai_client import ask_ai, ask_ai_fused
from personality import build_system_prompt
from rate_limit import SlidingWindowLimiter
import db

# Chemin explicite vers .env, à côté de ce fichier — fonctionne peu importe
# le dossier depuis lequel `uvicorn main:app` est lancé. En production
# (Render, etc.), les variables viennent du dashboard de l'hébergeur, pas
# de ce fichier — load_dotenv() ne fait rien si .env n'existe pas, donc
# c'est sans danger de le garder ici pour le dev local ET la prod.
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# "parallel" (défaut) : appelle tous les providers en parallèle + fusion via LLM-juge.
#   Meilleure qualité, mais 3-4 appels API par message (consomme les quotas gratuits plus vite).
# "fallback" : un seul provider répond, les autres ne servent que de secours.
#   Plus rapide, plus économe en quota, qualité légèrement moindre.
FUSION_MODE = os.getenv("FUSION_MODE", "parallel").lower()

# CORS : liste blanche des origines autorisées. En local, le frontend tourne
# sur un port quelconque (live-server, python -m http.server, etc.) donc on
# garde une liste souple ; en prod, ajoute l'URL Vercel exacte dans .env
# (ALLOWED_ORIGINS, séparées par des virgules) pour resserrer.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else ["*"]
)

# Rate limiting (étape 8) : protège les quotas gratuits, surtout en mode
# "parallel" où 1 message = jusqu'à 4 appels API réels (3 providers + juge).
SESSION_RATE_LIMIT = SlidingWindowLimiter(max_requests=8, window_seconds=60)
GLOBAL_RATE_LIMIT = SlidingWindowLimiter(max_requests=15, window_seconds=60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Démarrage ---
    print(f"[startup] .env chargé depuis {ENV_PATH}")
    for key_name in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN"):
        value = os.getenv(key_name)
        if value:
            print(f"[startup]   {key_name} : OK ({value[:6]}...{value[-4:]})")
        else:
            print(f"[startup]   {key_name} : absente (provider ignoré, fallback sur le suivant)")
    if not os.getenv("GROQ_API_KEY"):
        print("[startup] ATTENTION: aucun provider n'a de clé configurée. Le chat ne fonctionnera pas.")
    print(f"[startup] FUSION_MODE = {FUSION_MODE}")
    print(f"[startup] CORS autorisé pour : {ALLOWED_ORIGINS}")
    print(f"[startup] Rate limit : {SESSION_RATE_LIMIT.max_requests}/min par session, "
          f"{GLOBAL_RATE_LIMIT.max_requests}/min au total")

    await db.init_db()
    print("[startup] Base de données Postgres (Supabase) connectée")

    yield

    # --- Arrêt propre ---
    await db.close_db()
    print("[shutdown] Pool de connexions Postgres fermé")


app = FastAPI(title="AI Orchestrator", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    title: str


@app.get("/")
def health_check():
    return {"status": "ok", "service": "ai-orchestrator-backend"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message vide.")

    if not GLOBAL_RATE_LIMIT.allow("global"):
        raise HTTPException(
            status_code=429,
            detail="Soren a besoin d'une pause, trop de monde lui parle en même temps. Réessaie dans quelques secondes.",
        )

    if not SESSION_RATE_LIMIT.allow(req.session_id):
        wait = int(SESSION_RATE_LIMIT.seconds_until_next_slot(req.session_id)) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Doucement. Laisse-moi souffler {wait}s avant le prochain message.",
        )

    # Crée la conversation en DB si c'est le premier message de cette session
    # (le titre est dérivé de ce premier message).
    await db.ensure_conversation(req.session_id, first_message=req.message)

    # Contexte envoyé au LLM : les 20 derniers messages de CETTE conversation.
    history = await db.get_history(req.session_id, limit=20)
    messages = [{"role": "system", "content": build_system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": req.message})

    try:
        if FUSION_MODE == "fallback":
            reply = await ask_ai(messages)
        else:
            reply = await ask_ai_fused(messages, req.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur IA: {str(e)}")

    await db.add_message(req.session_id, "user", req.message)
    await db.add_message(req.session_id, "assistant", reply)

    meta = await db.get_conversation_meta(req.session_id)
    title = meta["title"] if meta else "Nouvelle conversation"

    return ChatResponse(reply=reply, session_id=req.session_id, title=title)


@app.get("/conversations/{session_id}")
async def get_conversation(session_id: str):
    """
    Récupère une conversation complète (titre + tous les messages), pour la
    réafficher côté frontend. Pas de "liste toutes les conversations" ici
    volontairement — voir la note de confidentialité dans db.py.
    """
    conv = await db.get_full_conversation(session_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return conv


@app.delete("/conversations/{session_id}")
async def remove_conversation(session_id: str):
    deleted = await db.delete_conversation(session_id)
    return {"status": "deleted" if deleted else "not_found", "session_id": session_id}
