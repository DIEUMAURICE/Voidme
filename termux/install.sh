#!/data/data/com.termux/files/usr/bin/bash
# Script d'installation légère pour Voidme sur Termux
# Ne nécessite pas de compilateurs lourds

set -e

echo "📦 Installation de Voidme (version légère)"

# 1. Mise à jour des paquets système (uniquement essentiels)
pkg update -y && pkg upgrade -y

# 2. Installer Python, Git et les dépendances système minimales
pkg install python git -y

# 3. Nettoyer les caches pour économiser de l'espace
apt clean

# 4. Créer l'environnement virtuel Python
echo "🐍 Création de l'environnement virtuel..."
python -m venv venv
source venv/bin/activate

# 5. Mettre à jour pip et installer les dépendances Python (requirements.txt déjà léger)
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

# 6. Créer le fichier .env à partir de l'exemple s'il n'existe pas
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Édite le fichier .env pour y mettre ta clé API OpenRouter et ton token Telegram."
fi

echo "✅ Installation terminée !"
echo "➡️  Lance l'application avec : ./termux/run.sh"