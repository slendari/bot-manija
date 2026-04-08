import requests
import json
import os
import threading
import http.server
import socketserver
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8750533607:AAFsxyeQfVo_ca_ehJ8T2zeJ92u9wPhSkAA'
API_KEY_TMDB = '32f474f4af44c8db3dce402ff78408d7'
DB_FILE = 'mis_series.json'

# --- TRUCO PARA RENDER (Mantiene el servicio vivo) ---
def start_server():
    PORT = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        httpd.serve_forever()

def cargar_series():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def guardar_series(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def buscar_en_tmdb(nombre):
    url = f"https://api.themoviedb.org/3/search/tv?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES"
    res = requests.get(url).json()
    return res['results'][0] if res.get('results') else None

# --- COMANDOS (Iguales a los anteriores) ---
async def start(update, context):
    await update.message.reply_text("¡El Manija TV en Render! /ver, /seguir, /borrar o /revisar.")

async def ver(update, context):
    nombre = " ".join(context.args)
    serie = buscar_en_tmdb(nombre)
    if not serie: return
    detalles = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
    proximo = detalles.get('next_episode_to_air')
    if proximo:
        msg = f"📺 **{serie['name']}**\n📅 Próximo: {proximo['air_date']}\n🎞️ Cap {proximo['episode_number']}: {proximo['name']}"
        await update.message.reply_text(msg, parse_mode='Markdown')

async def seguir(update, context):
    nombre = " ".join(context.args)
    serie = buscar_en_tmdb(nombre)
    if serie:
        data = cargar_series()
        u_id = str(update.effective_user.id)
        if u_id not in data: data[u_id] = []
        if serie['id'] not in [s['id'] for s in data[u_id]]:
            data[u_id].append({'id': serie['id'], 'name': serie['name']})
            guardar_series(data)
            await update.message.reply_text(f"✅ Seguida: {serie['name']}")

async def revisar_estrenos(update, context):
    data = cargar_series()
    u_id = str(update.effective_user.id)
    hoy = datetime.now().strftime("%Y-%m-%d")
    encontrado = False
    for s in data.get(u_id, []):
        det = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
        prox = det.get('next_episode_to_air')
        if prox and prox['air_date'] == hoy:
            encontrado = True
            await update.message.reply_text(f"🚨 **¡HOY ESTRENA!** 🚨\n📺 {s['name']}\n🎞️ {prox['name']}", parse_mode='Markdown')
    if not encontrado: await update.message.reply_text("Nada por hoy.")

if __name__ == '__main__':
    # Lanzar servidor en segundo plano para Render
    threading.Thread(target=start_server, daemon=True).start()
    
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    app.add_handler(CommandHandler("seguir", seguir))
    app.add_handler(CommandHandler("revisar", revisar_estrenos))
    
    print("El Manija TV arrancando en Render...")
    app.run_polling()