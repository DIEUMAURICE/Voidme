import os
import glob
import shutil
import json
from datetime import datetime
from typing import Union, Optional

# =========================================================
# AUCUNE dépendance lourde ici (plus de yt-dlp, openpyxl, etc.)
# =========================================================

def read_file(filepath: str) -> str:
    """Lit le contenu d'un fichier texte."""
    if not os.path.exists(filepath):
        return f"❌ Erreur : Le fichier '{filepath}' n'existe pas."
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Limiter l'affichage pour éviter le spam
            if len(content) > 5000:
                return content[:5000] + f"\n... (fichier tronqué, {len(content)} caractères au total)"
            return content
    except Exception as e:
        return f"❌ Erreur de lecture : {str(e)}"

def write_file(filepath: str, content: str) -> str:
    """Écrit ou écrase un fichier avec le contenu donné."""
    try:
        # Créer les dossiers parents si nécessaires
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"✅ Fichier créé/mis à jour : '{filepath}' ({len(content)} caractères)"
    except Exception as e:
        return f"❌ Erreur d'écriture : {str(e)}"

def append_file(filepath: str, content: str) -> str:
    """Ajoute du contenu à la fin d'un fichier."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(content + "\n")
        return f"✅ Contenu ajouté à '{filepath}'"
    except Exception as e:
        return f"❌ Erreur d'ajout : {str(e)}"

def list_files(directory: str = ".", pattern: str = "*", max_display: int = 30) -> str:
    """Liste les fichiers dans un dossier avec un motif (glob)."""
    if not os.path.exists(directory):
        return f"❌ Dossier '{directory}' introuvable."
    
    full_pattern = os.path.join(directory, pattern)
    files = glob.glob(full_pattern)
    files = [f for f in files if os.path.isfile(f)]
    
    if not files:
        return f"📁 Aucun fichier trouvé dans '{directory}' avec le motif '{pattern}'."
    
    # Trier par date de modification (récent en premier)
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    result = [f"📂 {directory} ({len(files)} fichiers) :"]
    for f in files[:max_display]:
        size = os.path.getsize(f)
        if size < 1024:
            size_str = f"{size} o"
        elif size < 1024*1024:
            size_str = f"{size/1024:.1f} Ko"
        else:
            size_str = f"{size/(1024*1024):.1f} Mo"
        result.append(f"  - {os.path.basename(f)} ({size_str})")
    
    if len(files) > max_display:
        result.append(f"... et {len(files) - max_display} autres fichiers.")
    
    return "\n".join(result)

def delete_file(filepath: str) -> str:
    """Supprime un fichier (attention, définitif)."""
    if not os.path.exists(filepath):
        return f"❌ Le fichier '{filepath}' n'existe pas."
    try:
        os.remove(filepath)
        return f"🗑️ Fichier supprimé : '{filepath}'"
    except Exception as e:
        return f"❌ Erreur suppression : {str(e)}"

def get_file_info(filepath: str) -> str:
    """Retourne des métadonnées sur un fichier."""
    if not os.path.exists(filepath):
        return f"❌ Le fichier '{filepath}' n'existe pas."
    try:
        stat = os.stat(filepath)
        info = {
            "Nom": os.path.basename(filepath),
            "Chemin": filepath,
            "Taille": f"{stat.st_size} octets",
            "Dernière modification": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "Dernier accès": datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"❌ Erreur info : {str(e)}"