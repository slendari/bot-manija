import requests
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import http.server
import socketserver
import threading

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8750533607:AAFsxyeQfVo_ca_ehJ8T2zeJ92u9wPhSkAA'
API_KEY_TMDB = '32f474f4af44c8db3dce402ff78408d7'

# --- SERVIDOR SIMPLE PARA RENDER ---
def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()

def buscar_en_tmdb(nombre):
    url = f"https://api.themoviedb.org/3/search/tv?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES"
    res = requests.get(url).json()
    return res['results'][0] if res.get('results') else None

async def start(update, context):
    await update.message.reply_text("¡El Manija TV vivo en Render! Tirame un /ver [serie]")

async def ver(update, context):
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("Pasame el nombre.")
        return
    serie = buscar_en_tmdb(nombre)
    if not serie:
        await update.message.reply_text("No la encontré.")
        return
    
    det = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
    prox = det.get('next_episode_to_air')
    if prox:
        await update.message.reply_text(f"📺 {serie['name']}\n📅 Estreno: {prox['air_date']}\n🎞️ Cap {prox['episode_number']}: {prox['name']}")
    else:
        await update.message.reply_text(f"De {serie['name']} no hay fechas.")

if __name__ == '__main__':
    # Hilo para que Render no mate el proceso
    threading.Thread(target=keep_alive, daemon=True).start()
    
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    
    print("Bot activo...")
    app.run_polling()
