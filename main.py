import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from core.agent import VoidmeAgent
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialisation de l'agent (version mémoire vectorielle avec NumPy)
agent = VoidmeAgent()

# --- Gestionnaire Telegram ---
async def tg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    try:
        response = agent.process_query(user_msg)
        await update.message.reply_text(response)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {str(e)}")

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    
    # Si le token Telegram est présent, on lance le bot
    if token:
        print("🚀 Bot Telegram en cours d'exécution...")
        app_tg = Application.builder().token(token).build()
        app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handler))
        app_tg.run_polling()
    else:
        # Sinon, on lance un mode CLI (terminal)
        print("⚠️  TELEGRAM_TOKEN manquant dans .env")
        print("💻 Mode CLI activé. Tape 'exit' pour quitter.")
        while True:
            user_input = input("\n🧑 Vous : ")
            if user_input.lower() in ["exit", "quit", "q"]:
                break
            response = agent.process_query(user_input)
            print(f"🤖 : {response}")

if __name__ == '__main__':
    main()    token = os.getenv("TELEGRAM_TOKEN")
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
