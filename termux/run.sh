#!/data/data/com.termux/files/usr/bin/bash
# Lancement de Voidme

cd "$(dirname "$0")/.."  # Se place à la racine du projet
source venv/bin/activate
python main.py