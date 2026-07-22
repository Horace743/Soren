# AI Orchestrator — Étapes 1 & 2

Interface de chat connectée à Groq (Llama 3.3 70B, gratuit), avec la personnalité
"pote exigeant" déjà branchée via system prompt.

## Structure

```
ai-orchestrator/
├── backend/
│   ├── main.py           # routes FastAPI (/chat, /chat/{id})
│   ├── ai_client.py       # appel Groq — à dupliquer pour OpenRouter/HF (étape 3)
│   ├── personality.py     # system prompt — deviendra le dictionnaire (étape 5-6)
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

## Lancer en local (Ubuntu)

### 1. Backend

```bash
cd ai-orchestrator/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Édite .env et colle ta clé Groq (gratuite sur https://console.groq.com/keys)

uvicorn main:app --reload --port 8000
```

Vérifie que ça tourne : http://127.0.0.1:8000 doit répondre `{"status":"ok",...}`.
Doc interactive auto-générée : http://127.0.0.1:8000/docs

### 2. Frontend

Pas besoin de build. Ouvre simplement `frontend/index.html` dans le navigateur,
ou sers-le avec un serveur statique léger pour éviter les soucis de CORS/file:// :

```bash
cd ai-orchestrator/frontend
python3 -m http.server 5500
```

Puis va sur http://127.0.0.1:5500

## Ce qui est déjà fait

- Chat fonctionnel avec mémoire de conversation (RAM, par session_id, limité aux 20 derniers messages)
- Personnalité "pote taquin mais utile" appliquée via system prompt (pas de règles codées à la main, comme discuté)
- Architecture prête pour la suite sans refactor : `ai_client.py` attend juste d'autres fonctions `ask_openrouter()`, `ask_huggingface()` à côté de `ask_groq()`
- Frontend v2 : statut de connexion en direct (ping du backend toutes les 15s), indicateur de frappe animé, timestamps façon logs, bouton copier sur les réponses, textarea auto-resize, Entrée pour envoyer / Maj+Entrée pour une ligne, séquence de boot au chargement

## Prochaines étapes (dans l'ordre qu'on a validé)

1. **Étape 3** — ajouter OpenRouter + HuggingFace dans `ai_client.py`, appelés en parallèle avec `asyncio.gather`
2. **Étape 4** — fusionneur : au lieu de règles de dédoublonnage codées à la main, un appel LLM supplémentaire en mode "juge" qui reçoit les réponses brutes et produit la version finale
3. **Étape 5-6** — affiner `personality.py` avec plus de cas si le comportement actuel ne suffit pas (corrections orthographiques, contradictions)
4. **Étape 7** — remplacer le dict RAM par SQLite pour la mémoire persistante
5. **Étape 8** — cache de réponses + fallback si un provider timeout

## Notes techniques

- CORS ouvert (`allow_origins=["*"]`) — à restreindre avant toute mise en prod
- Pas d'authentification pour l'instant — normal à ce stade, à ajouter avant tout déploiement public
- `GROQ_MODEL` dans `ai_client.py` est en dur — facile à rendre configurable via `.env` si tu veux tester plusieurs modèles Groq
