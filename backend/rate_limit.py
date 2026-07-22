"""
Rate limiting simple, en mémoire (étape 8).

Objectif : protéger les quotas gratuits des providers (Groq/OpenRouter/HF)
contre un usage abusif ou un bug côté client qui spammerait l'API — surtout
une fois le projet partagé avec plusieurs amis en simultané.

Design volontairement simple (fenêtre glissante en mémoire, pas de Redis) :
suffisant pour un seul process backend et un petit groupe d'utilisateurs.
Si le backend tourne un jour sur plusieurs instances (plusieurs workers,
load balancer...), il faudra un store partagé (Redis) — l'interface
ci-dessous resterait identique côté appelant.
"""

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """True si la requête est autorisée (et l'enregistre). False sinon."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True

    def seconds_until_next_slot(self, key: str) -> float:
        """Combien de temps attendre avant qu'une nouvelle requête soit acceptée."""
        hits = self._hits[key]
        if len(hits) < self.max_requests:
            return 0.0
        return max(0.0, self.window_seconds - (time.monotonic() - hits[0]))
