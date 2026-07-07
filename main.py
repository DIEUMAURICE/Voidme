from flask import Flask, request, jsonify, render_template_string
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from agent import VoidmeAgent
import os
import threading
from dotenv import load_dotenv

load_dotenv()

# Initialisation de l'agent (une seule fois)
agent = VoidmeAgent()

# --- Flask (Dashboard local) ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html><head><title>Voidme Codeur</title></head>
<body style="background:#111; color:#0f0; font-family:monospace; padding:20px;">
<h1>⚡ Voidme - Assistant Codeur</h1>
<div id="chat" style="height:400px; overflow-y:scroll; border:1px solid #0f0; padding:10px;"></div>
<input type="text" id="input" style="width:80%; background:#222; color:#0f0; border:1px solid #0f0; padding:10px;">
<button onclick="send()" style="background:#0f0; color:#000;">Envoyer</button>
<script>
async function send() {
    let input = document.getElementById('input');
    let msg = input.value; if(!msg) return;
    input.value = '';
    document.getElementById('chat').innerHTML += '<br><b>Moi :</b> ' + msg;
    let res = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({msg:msg})});
    let data = await res.json();
    document.getElementById('chat').innerHTML += '<br><b>IA :</b> ' + data.response;
}
</script>
</body></html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chat', methods=['POST'])
def chat():
    msg = request.json.get('msg')
    response = agent.process_query(msg)
    return jsonify({'response': response})

# --- Telegram ---
async def tg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    response = agent.process_query(msg)
    await update.message.reply_text(response)

def run_telegram():
    bot = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handler))
    bot.run_polling()

# --- Lancement simultané ---
if __name__ == '__main__':
    threading.Thread(target=run_telegram, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)