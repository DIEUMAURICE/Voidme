import os
import re
import yaml
import logging
import requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Import de nos modules maison
from solid_memory import SolidMemory
from tools import read_file, write_file, append_file, list_files, delete_file, get_file_info

load_dotenv()  # Charge les variables depuis .env
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoidmeAgent:
    """
    Agent central : 
    - Appelle une API LLM (OpenRouter/Groq) à la place d'Ollama.
    - Utilise SolidMemory pour le contexte.
    - Exécute des commandes fichiers via tools.py.
    """

    def __init__(self, config_path: str = "config.yaml"):
        # Chargement de la configuration
        self.config = self._load_config(config_path)
        
        # Récupération de la clé API (priorité .env)
        self.api_key = os.getenv("OPENROUTER_API_KEY") or self.config.get("api_key")
        if not self.api_key:
            raise ValueError("❌ Clé API OpenRouter manquante. Mets-la dans .env ou config.yaml")

        # Modèles (par défaut, Gemini Flash car très rapide et peu cher)
        self.llm_model = os.getenv("LLM_MODEL") or self.config.get("llm_model", "google/gemini-flash-1.5")
        self.embedding_model = os.getenv("EMBEDDING_MODEL") or self.config.get("embedding_model", "openai/text-embedding-3-small")
        
        # URL de l'API OpenRouter
        self.llm_url = "https://openrouter.ai/api/v1/chat/completions"
        
        # Initialisation de la mémoire
        self.memory = SolidMemory(
            api_key=self.api_key,
            embedding_model=self.embedding_model,
            db_path=self.config.get("memory_db", "memory.db")
        )
        
        # Système de base (modifiable via config)
        self.base_system_prompt = self.config.get("system_prompt", 
            "Tu es un assistant codeur et idéaliste. Tu aides à coder, analyser et organiser des projets. "
            "Tu peux lire et écrire des fichiers. Utilise les balises suivantes pour interagir avec le système de fichiers :\n"
            "- [FILE_READ:chemin/vers/fichier]\n"
            "- [FILE_WRITE:chemin/vers/fichier] contenu du fichier\n"
            "- [FILE_APPEND:chemin/vers/fichier] contenu à ajouter\n"
            "- [FILE_LIST:dossier] (ou [FILE_LIST:dossier|*.py] pour filtrer)\n"
            "- [FILE_DELETE:chemin/vers/fichier]\n"
            "- [FILE_INFO:chemin/vers/fichier]\n"
            "Réponds toujours en français, avec le code bien formaté."
        )
        
        logger.info(f"🚀 Agent initialisé avec le modèle {self.llm_model}")

    def _load_config(self, path: str) -> Dict[str, Any]:
        """Charge le fichier config.yaml s'il existe."""
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Impossible de charger {path} : {e}")
        return {}

    def _call_llm(self, user_message: str, system_prompt: str) -> str:
        """Appelle l'API LLM (OpenRouter)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 4096
        }
        
        try:
            response = requests.post(self.llm_url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            return "⏰ Délai dépassé. L'API met trop de temps à répondre."
        except Exception as e:
            logger.error(f"Erreur LLM : {e}")
            return f"❌ Erreur lors de l'appel à l'IA : {str(e)}"

    def _execute_file_commands(self, text: str) -> str:
        """
        Détecte et exécute les balises [FILE_XXX:...] dans le texte.
        Retourne le texte avec les résultats des commandes insérés.
        """
        # Pattern pour capturer les commandes
        pattern = r'\[FILE_(READ|WRITE|APPEND|LIST|DELETE|INFO):(.*?)\](?:\s*(.*?))?(?=\n\[FILE_|$)'
        matches = re.findall(pattern, text, re.DOTALL)
        
        if not matches:
            return text
        
        result_text = text
        for cmd, path, content in matches:
            cmd = cmd.strip()
            path = path.strip()
            content = content.strip() if content else ""
            output = ""
            
            if cmd == "READ":
                output = read_file(path)
            elif cmd == "WRITE":
                output = write_file(path, content)
            elif cmd == "APPEND":
                output = append_file(path, content)
            elif cmd == "LIST":
                # Gérer le pattern optionnel (ex: dossier|*.py)
                parts = path.split('|')
                dir_path = parts[0].strip()
                pattern_glob = parts[1].strip() if len(parts) > 1 else "*"
                output = list_files(dir_path, pattern_glob)
            elif cmd == "DELETE":
                output = delete_file(path)
            elif cmd == "INFO":
                output = get_file_info(path)
            else:
                continue
            
            # Remplacer la balise par le résultat
            # On cherche la balise exacte dans le texte original pour la remplacer
            full_match = f"[FILE_{cmd}:{path}]"
            if content:
                full_match += f" {content}"
            result_text = result_text.replace(full_match, f"\n📁 **Résultat de la commande `{cmd}`** :\n{output}\n")
        
        return result_text

    def process_query(self, user_input: str) -> str:
        """
        Point d'entrée principal.
        """
        # 1. Recherche dans la mémoire
        memories = self.memory.search(user_input, top_k=4)
        context_str = "\n".join([f"- {m}" for m in memories]) if memories else "Aucun souvenir pertinent."

        # 2. Construction du prompt système
        system_prompt = f"""{self.base_system_prompt}

        **Contexte des conversations précédentes** (souvenirs) :
        {context_str}

        **Règles importantes** :
        - Pour manipuler des fichiers, utilise OBLIGATOIREMENT les balises [FILE_XXX:...].
        - N'écris JAMAIS de code dans les balises, seulement dans le contenu qui suit.
        - Si tu crées un fichier, explique ce que tu fais puis utilise [FILE_WRITE:...].
        - Si tu proposes des modifications, utilise [FILE_READ:...] pour voir le fichier d'abord.
        """

        # 3. Appel à l'IA
        raw_response = self._call_llm(user_input, system_prompt)
        
        # 4. Exécution des commandes fichiers
        final_response = self._execute_file_commands(raw_response)
        
        # 5. Sauvegarder l'échange dans la mémoire (pour le contexte futur)
        memory_entry = f"User: {user_input[:200]}\nAssistant: {final_response[:200]}"
        self.memory.add(memory_entry)
        
        return final_response

# ====================================================
# Pour une utilisation directe en CLI (test rapide)
# ====================================================
if __name__ == "__main__":
    agent = VoidmeAgent()
    print("🤖 Assistant Voidme prêt. Tape 'exit' pour quitter.")
    while True:
        user_msg = input("\n🧑 Vous : ")
        if user_msg.lower() in ["exit", "quit", "q"]:
            break
        response = agent.process_query(user_msg)
        print(f"\n🤖 IA : {response}")