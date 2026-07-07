from flask import Flask, request, jsonify, render_template_string
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from core.agent import VoidmeAgent  # Correction du chemin
import os
import threading
from dotenv import load_dotenv

load_dotenv()

# Initialisation de l'agent
agent = VoidmeAgent()

# --- Interface Web (Flask) ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voidme - Assistant Codeur</title>
    <style>
        body { background: #111; color: #0f0; font-family: monospace; padding: 20px; }
        #chat { height: 400px; overflow-y: scroll; border: 1px solid #0f0; padding: 10px; margin-bottom: 10px; }
        input { width: 80%; background: #222; color: #0f0; border: 1px solid #0f0; padding: 10px; }
        button { background: #0f0; color: #000; padding: 10px 20px; border: none; cursor: pointer; }
    </style>
</head>
<body>
    <h1>⚡ Voidme - Assistant Codeur</h1>
    <div id="chat"></div>
    <input type="text" id="input" placeholder="Pose ta question...">
    <button onclick="send()">Envoyer</button>
    <script>
        async function send() {
            let inp = document.getElementById('input');
            let msg = inp.value.trim();
            if (!msg) return;
            inp.value = '';
            let chat = document.getElementById('chat');
            chat.innerHTML += '<br><b>Moi :</b> ' + msg;
            try {
                let res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ msg: msg })
                });
                let data = await res.json();
                chat.innerHTML += '<br><b>IA :</b> ' + data.response;
                chat.scrollTop = chat.scrollHeight;
            } catch (e) {
                chat.innerHTML += '<br><b>Erreur :</b> ' + e.message;
            }
        }
        // Permet d'envoyer avec la touche Entrée
        document.getElementById('input').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') send();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    msg = request.json.get('msg')
    try:
        response = agent.process_query(msg)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'response': f"❌ Erreur : {str(e)}"}), 500

# --- Bot Telegram ---
async def tg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    try:
        response = agent.process_query(user_msg)
        await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {str(e)}")

def run_telegram():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("⚠️  TELEGRAM_TOKEN manquant dans .env – le bot Telegram ne démarre pas.")
        return
    app_tg = Application.builder().token(token).build()
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handler))
    app_tg.run_polling()

# --- Lancement simultané ---
if __name__ == '__main__':
    # Démarrer le bot Telegram dans un thread séparé
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    # Lancer le serveur Flask (interface web)
    app.run(host='0.0.0.0', port=5000, debug=False)