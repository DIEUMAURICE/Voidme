#!/bin/bash

# 1. Créer le dossier common s'il n'existe pas
mkdir -p common

# 2. Générer le fichier config.yaml avec les variables d'environnement
cat > common/config.yaml << EOF
telegram_token: ${TELEGRAM_BOT_TOKEN}
bot_username: ${BOT_USERNAME}
# Ajoutez d'autres paramètres par défaut si besoin
log_level: INFO
EOF

# 3. Lancer l'agent (la bonne commande !)
python3 -m core.agent
