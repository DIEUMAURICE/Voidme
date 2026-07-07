import sqlite3
import numpy as np
import requests
import os
import json
import logging
from typing import List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SolidMemory:
    """
    Mémoire persistante avec SQLite et embeddings via API externe.
    Ne stocke que 5000 entrées max pour rester sous 2 Go.
    """
    def __init__(self, api_key: str, embedding_model: str = "openai/text-embedding-3-small", 
                 db_path: str = "memory.db"):
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.db_path = db_path
        self.embedding_url = "https://openrouter.ai/api/v1/embeddings"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS memories
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      text TEXT UNIQUE,
                      embedding BLOB)''')
        # Nettoyer les éventuelles entrées trop longues
        c.execute("DELETE FROM memories WHERE LENGTH(text) > 2000")
        conn.commit()
        conn.close()
        logger.info(f"Base de données mémoire initialisée : {self.db_path}")

    def _get_embedding(self, text: str) -> np.ndarray:
        """Convertit un texte en vecteur via OpenRouter."""
        # Tronquer pour ne pas dépasser les limites de l'API (8000 caractères)
        truncated = text[:8000]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.embedding_model,
            "input": truncated
        }
        try:
            response = requests.post(self.embedding_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            # Gérer le format de réponse OpenRouter (et compatible OpenAI)
            if "data" in data and len(data["data"]) > 0:
                return np.array(data["data"][0]["embedding"], dtype=np.float32)
            else:
                raise ValueError("Format de réponse inattendu")
        except Exception as e:
            logger.error(f"Erreur embedding : {e}. Retourne un vecteur nul.")
            # Fallback : vecteur de 1536 dimensions (taille standard) rempli de 0
            return np.zeros(1536, dtype=np.float32)

    def add(self, text: str):
        """Ajoute un texte à la mémoire (ou le met à jour)."""
        if not text or len(text) < 5:
            return
        embedding = self._get_embedding(text)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Suppression de l'ancien si le texte existe déjà (pour mise à jour)
        c.execute("DELETE FROM memories WHERE text = ?", (text[:500],))
        c.execute("INSERT INTO memories (text, embedding) VALUES (?, ?)", 
                  (text[:500], embedding.tobytes()))
        # Limiter à 5000 entrées (les plus récentes)
        c.execute("DELETE FROM memories WHERE id NOT IN (SELECT id FROM memories ORDER BY id DESC LIMIT 5000)")
        conn.commit()
        conn.close()
        logger.debug(f"Mémoire ajoutée : {text[:50]}...")

    def search(self, query: str, top_k: int = 5) -> List[str]:
        """Recherche les textes les plus similaires à la requête."""
        query_vec = self._get_embedding(query)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Récupère les 5000 dernières entrées pour la recherche
        c.execute("SELECT text, embedding FROM memories ORDER BY id DESC LIMIT 5000")
        rows = c.fetchall()
        conn.close()

        if not rows:
            return []

        similarities = []
        for text, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            # Éviter les vecteurs nuls
            if np.linalg.norm(query_vec) == 0 or np.linalg.norm(vec) == 0:
                sim = 0.0
            else:
                sim = np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec))
            similarities.append((sim, text))

        # Trier par similarité décroissante
        similarities.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in similarities[:top_k]]