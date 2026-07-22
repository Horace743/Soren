"""
Couche de persistance Postgres, via Supabase (étape déploiement).

Remplace la version SQLite : les hébergeurs gratuits pour le backend
(Render, Railway, etc.) ont typiquement un disque éphémère — un fichier
SQLite local risque d'être effacé à chaque redéploiement. Supabase donne
une base Postgres gérée et gratuite, qui vit indépendamment du serveur
applicatif : l'historique survit à tous les redéploiements.

Utilise asyncpg avec un pool de connexions partagé, créé une fois au
démarrage de l'app (voir le `lifespan` dans main.py) et réutilisé pour
chaque requête — adapté à FastAPI (async natif), contrairement au pattern
"une connexion par opération" qu'on utilisait avec SQLite, qui serait ici
trop coûteux en latence réseau (chaque connexion = un aller-retour TCP/TLS
vers un serveur distant, pas un fichier local).

Connexion : utilise l'URI de connexion DIRECTE de Supabase (port 5432,
PAS le pooler PgBouncer sur le port 6543). La distinction compte : le
pooler Supavisor est fait pour les environnements serverless qui ouvrent
plein de connexions courtes (Vercel functions, etc.) ; nous, on est un
process persistant (Render) qui gère déjà son propre pool en interne côté
appli — la connexion directe est donc le bon choix ici, plus simple et
sans couche d'indirection en trop.

IMPORTANT — confidentialité (inchangé depuis la version SQLite) :
Toujours aucun endpoint qui liste toutes les conversations, tous
utilisateurs confondus. Le session_id reste la seule clé d'accès à une
conversation.
"""

import os
import asyncpg
from datetime import datetime, timezone

_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """À appeler une fois, au démarrage de l'app (voir lifespan dans main.py)."""
    global _pool

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL manquante. Ajoute la chaîne de connexion Postgres de ton "
            "projet Supabase dans backend/.env — Project Settings -> Database -> "
            "Connection string -> URI (connexion directe, port 5432, pas le pooler)."
        )

    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'Nouvelle conversation',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
        )


async def close_db() -> None:
    """À appeler à l'arrêt de l'app (voir lifespan dans main.py)."""
    if _pool is not None:
        await _pool.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_conversation(session_id: str, first_message: str | None = None) -> None:
    """Crée la conversation si elle n'existe pas encore. Le titre vient du
    premier message utilisateur, tronqué à 60 caractères."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id FROM conversations WHERE session_id = $1", session_id
        )
        if row is None:
            title = "Nouvelle conversation"
            if first_message:
                cleaned = first_message.strip().replace("\n", " ")
                title = cleaned[:60] + ("…" if len(cleaned) > 60 else "")
            now = _now()
            await conn.execute(
                "INSERT INTO conversations (session_id, title, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4)",
                session_id, title, now, now,
            )


async def add_message(session_id: str, role: str, content: str) -> None:
    async with _pool.acquire() as conn:
        now = _now()
        await conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
            session_id, role, content, now,
        )
        await conn.execute(
            "UPDATE conversations SET updated_at = $1 WHERE session_id = $2", now, session_id
        )


async def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Les `limit` derniers messages, dans l'ordre chronologique, prêts à
    être envoyés au LLM comme contexte de conversation."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE session_id = $1
                ORDER BY id DESC
                LIMIT $2
            ) sub ORDER BY id ASC
            """,
            session_id, limit,
        )
        return [{"role": r["role"], "content": r["content"]} for r in rows]


async def get_full_conversation(session_id: str) -> dict | None:
    """Infos + TOUS les messages d'une conversation (pour l'affichage
    complet côté frontend quand on rouvre une conversation)."""
    async with _pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT session_id, title, created_at, updated_at FROM conversations WHERE session_id = $1",
            session_id,
        )
        if conv is None:
            return None
        messages = await conn.fetch(
            "SELECT role, content, created_at FROM messages WHERE session_id = $1 ORDER BY id ASC",
            session_id,
        )
        return {
            "session_id": conv["session_id"],
            "title": conv["title"],
            "created_at": conv["created_at"].isoformat(),
            "updated_at": conv["updated_at"].isoformat(),
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m["created_at"].isoformat(),
                }
                for m in messages
            ],
        }


async def get_conversation_meta(session_id: str) -> dict | None:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id, title, created_at, updated_at FROM conversations WHERE session_id = $1",
            session_id,
        )
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }


async def delete_conversation(session_id: str) -> bool:
    async with _pool.acquire() as conn:
        await conn.execute("DELETE FROM messages WHERE session_id = $1", session_id)
        result = await conn.execute("DELETE FROM conversations WHERE session_id = $1", session_id)
        # asyncpg retourne une chaîne du type "DELETE 1" ou "DELETE 0"
        deleted_count = int(result.split()[-1])
        return deleted_count > 0
