import requests
import os
import threading
import http.server
import socketserver
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from pymongo import MongoClient

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8750533607:AAFsxyeQfVo_ca_ehJ8T2zeJ92u9wPhSkAA'
API_KEY_TMDB = '32f474f4af44c8db3dce402ff78408d7'
MONGO_URI = 'mongodb+srv://slendari:<*4r1_Y3d*>@cluster0.k8m8vid.mongodb.net/?appName=Cluster0' # <--- PEGA TU LINK ACÁ

# Conexión a MongoDB
client = MongoClient(MONGO_URI)
db = client['el_manija_db']
coleccion = db['usuarios_series']

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()

def buscar_en_tmdb(nombre):
    url = f"https://api.themoviedb.org/3/search/tv?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES"
    res = requests.get(url).json()
    return res['results'][0] if res.get('results') else None

def formatear_fecha(fecha_str):
    if not fecha_str: return "Sin fecha confirmada"
    meses = {"01":"Enero", "02":"Febrero", "03":"Marzo", "04":"Abril", "05":"Mayo", "06":"Junio", "07":"Julio", "08":"Agosto", "09":"Septiembre", "10":"Octubre", "11":"Noviembre", "12":"Diciembre"}
    y, m, d = fecha_str.split('-')
    return f"{int(d)} de {meses[m]}, {y}"

# --- COMANDOS ---

async def start(update, context):
    await update.message.reply_text(
        "¡Qué hacés! Acá el gordo Manija TV. Mis comandos:\n"
        "🔍 /ver [nombre] - Info del próximo estreno.\n"
        "✅ /seguir [nombre] - Guardar serie en tu lista.\n"
        "🗑️ /borrar [nombre] - Dejar de seguir una serie.\n"
        "🔔 /revisar - Ver si hoy se estrena algo de tu lista."
    )

async def ver(update, context):
    nombre = " ".join(context.args)
    serie = buscar_en_tmdb(nombre)
    if not serie:
        await update.message.reply_text("No la encontré.")
        return

    det = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
    proximo = det.get('next_episode_to_air')
    img_url = f"https://image.tmdb.org/t/p/w500{serie.get('poster_path')}" if serie.get('poster_path') else None

    if proximo:
        fecha_linda = formatear_fecha(proximo['air_date'])
        msg = f"📺 **{serie['name']}**\n📅 **Próximo:** {fecha_linda}\n🎞️ **Cap {proximo['episode_number']}:** {proximo['name']}"
        if img_url: await update.message.reply_photo(photo=img_url, caption=msg, parse_mode='Markdown')
        else: await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"De {serie['name']} no hay fechas confirmadas.")

async def seguir(update, context):
    nombre = " ".join(context.args)
    serie = buscar_en_tmdb(nombre)
    if serie:
        u_id = str(update.effective_user.id)
        # Buscamos al usuario en la DB
        user_data = coleccion.find_one({"user_id": u_id})
        series_lista = user_data['series'] if user_data else []
        
        if serie['id'] not in [s['id'] for s in series_lista]:
            series_lista.append({'id': serie['id'], 'name': serie['name']})
            coleccion.update_one({"user_id": u_id}, {"$set": {"series": series_lista}}, upsert=True)
            await update.message.reply_text(f"✅ Agregada: {serie['name']}")
        else:
            await update.message.reply_text(f"Ya la seguís.")

async def revisar_estrenos(update, context):
    u_id = str(update.effective_user.id)
    user_data = coleccion.find_one({"user_id": u_id})
    if not user_data or not user_data['series']:
        await update.message.reply_text("No seguís nada todavía.")
        return

    hoy = datetime.now().strftime("%Y-%m-%d")
    encontrado = False
    for s in user_data['series']:
        det = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
        prox = det.get('next_episode_to_air')
        if prox and prox['air_date'] == hoy:
            encontrado = True
            await update.message.reply_text(f"🚨 **¡HOY ESTRENA!** 🚨\n📺 **{s['name']}**\n🎞️ Cap {prox['episode_number']}: {prox['name']}", parse_mode='Markdown')
    
    if not encontrado: await update.message.reply_text("Hoy no hay nada.")

if __name__ == '__main__':
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    app.add_handler(CommandHandler("seguir", seguir))
    app.add_handler(CommandHandler("revisar", revisar_estrenos))
    app.run_polling()
