import requests
import os
import threading
import http.server
import socketserver
from datetime import datetime, timedelta, time
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from pymongo import MongoClient

# --- CONFIGURACIÓN ---
TOKEN_TELEGRAM = '8750533607:AAFsxyeQfVo_ca_ehJ8T2zeJ92u9wPhSkAA'
API_KEY_TMDB = '32f474f4af44c8db3dce402ff78408d7'
MONGO_URI = 'mongodb+srv://slendari:*4r1_Y3d*@cluster0.k8m8vid.mongodb.net/?appName=Cluster0'

client = MongoClient(MONGO_URI)
db = client['el_manija_db']
coleccion = db['usuarios_series']

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()

def buscar_en_tmdb(nombre):
    res = requests.get(f"https://api.themoviedb.org/3/search/tv?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES").json()
    return res['results'][0] if res.get('results') else None

def formatear_fecha(fecha_str):
    if not fecha_str: return "Sin fecha"
    meses = {"01":"Enero", "02":"Febrero", "03":"Marzo", "04":"Abril", "05":"Mayo", "06":"Junio", "07":"Julio", "08":"Agosto", "09":"Septiembre", "10":"Octubre", "11":"Noviembre", "12":"Diciembre"}
    y, m, d = fecha_str.split('-')
    return f"{int(d)} de {meses[m]}, {y}"

def hoy_local():
    # Sincronizado exacto con tu zona horaria
    tz = pytz.timezone('Asia/Jerusalem')
    return datetime.now(tz).strftime("%Y-%m-%d")

# --- FUNCIÓN DE AVISO AUTOMÁTICO ---
async def tarea_diaria(context: ContextTypes.DEFAULT_TYPE):
    hoy = hoy_local()
    usuarios = coleccion.find()
    
    for user_data in usuarios:
        u_id = user_data['user_id']
        for s in user_data.get('series', []):
            det = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
            prox = det.get('next_episode_to_air')
            
            if prox and prox['air_date'] == hoy:
                num_temp = prox['season_number']
                msg = f"🚨 **¡AVISO AUTOMÁTICO!** 🚨\n\n📺 **{s['name']}** estrena el capítulo {prox['episode_number']} de la temporada {num_temp} HOY."
                await context.bot.send_message(chat_id=u_id, text=msg, parse_mode='Markdown')

# --- COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Qué hacés bebé! Acá El ManijaTV 🍿. \n\n"
        "Con los siguientes comandos podés averiguar novedades de tus series favoritas:\n"
        "/ver [serie] - Info del próximo estreno.\n"
        "/seguir [serie] - Guardar serie en tu lista.\n"
        "/borrar [serie] - Dejar de seguir una serie.\n"
        "/revisar - Ver si hoy se estrena algo de tu lista.\n"
        "/lista - Ver todas las series que seguís."
    )

async def ver(update, context):
    nombre = " ".join(context.args)
    serie = buscar_en_tmdb(nombre)
    if not serie:
        await update.message.reply_text("No encontré esa serie.")
        return

    det = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
    prox = det.get('next_episode_to_air')
    img_url = f"https://image.tmdb.org/t/p/w500{serie.get('poster_path')}" if serie.get('poster_path') else None

    if prox:
        fecha_estreno = prox['air_date']
        hoy = hoy_local()
        num_temp = prox['season_number']
        
        temp_data = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES").json()
        episodes = temp_data.get('episodes', [])
        
        caps_hoy = [ep for ep in episodes if ep['air_date'] == fecha_estreno]
        caps_futuros = [ep for ep in episodes if ep['air_date'] > fecha_estreno]
        
        if fecha_estreno == hoy:
            dia_texto = "🚨 **¡HOY SE ESTRENA!** 🚨"
        else:
            dia_texto = f"📅 **Próximo estreno:** {formatear_fecha(fecha_estreno)}"
        
        msg = f"📺 **{serie['name']}**\n{dia_texto}\n🔢 Temporada {num_temp}\n\n"
        
        if len(caps_hoy) > 1:
            msg += f"✨ **Se estrenan {len(caps_hoy)} capítulos hoy:**\n"
            for ep in caps_hoy: msg += f"• Cap {ep['episode_number']}: {ep['name']}\n"
        else:
            msg += f"🎞️ **Capítulo {prox['episode_number']}:** {prox['name']}\n"
            
        if caps_futuros:
            msg += "\n🚀 **Cronograma de próximos estrenos:**\n"
            for ep in caps_futuros[:5]:
                msg += f"• {formatear_fecha(ep['air_date'])} - Cap {ep['episode_number']}\n"

        if img_url: 
            await update.message.reply_photo(photo=img_url, caption=msg, parse_mode='Markdown')
        else: 
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        text_no_hay = f"De '{serie['name']}' no hay fechas confirmadas por ahora."
        if img_url: await update.message.reply_photo(photo=img_url, caption=text_no_hay)
        else: await update.message.reply_text(text_no_hay)
            
async def seguir(update, context):
    try:
        nombre = " ".join(context.args)
        if not nombre:
            await update.message.reply_text("Decime qué serie seguir.")
            return
            
        serie = buscar_en_tmdb(nombre)
        if serie:
            u_id = str(update.effective_user.id)
            user_data = coleccion.find_one({"user_id": u_id})
            series_lista = user_data['series'] if user_data else []
            
            if serie['id'] not in [s['id'] for s in series_lista]:
                series_lista.append({'id': serie['id'], 'name': serie['name']})
                coleccion.update_one({"user_id": u_id}, {"$set": {"series": series_lista}}, upsert=True)
                await update.message.reply_text(f"Siguiendo {serie['name']} ✅.")
            else:
                await update.message.reply_text(f"Ya seguís a {serie['name']}.")
        else:
            await update.message.reply_text("No encontré esa serie.")
    except Exception as e:
        await update.message.reply_text("Error con la base de datos.")

async def borrar(update, context):
    nombre = " ".join(context.args).lower()
    u_id = str(update.effective_user.id)
    user_data = coleccion.find_one({"user_id": u_id})
    if user_data:
        nueva = [s for s in user_data['series'] if nombre not in s['name'].lower()]
        if len(nueva) < len(user_data['series']):
            coleccion.update_one({"user_id": u_id}, {"$set": {"series": nueva}})
            await update.message.reply_text("🗑️ Eliminada de tu lista.")
            return
    await update.message.reply_text("No encontré esa serie en tu lista.")

async def revisar_estrenos(update, context):
    try:
        u_id = str(update.effective_user.id)
        user_data = coleccion.find_one({"user_id": u_id})
        
        if not user_data or not user_data.get('series'):
            await update.message.reply_text("No seguís ninguna serie.")
            return

        hoy = hoy_local()
        encontrado = False
        
        for s in user_data['series']:
            det = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
            prox = det.get('next_episode_to_air')
            
            if prox and prox['air_date'] == hoy:
                encontrado = True
                num_temp = prox['season_number']
                temp_data = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES").json()
                
                poster = temp_data.get('poster_path') or det.get('poster_path')
                img_url = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
                caps_hoy = [ep for ep in temp_data.get('episodes', []) if ep['air_date'] == hoy]
                
                if len(caps_hoy) > 1:
                    lista = "\n".join([f"• Cap {ep['episode_number']}: {ep['name']}" for ep in caps_hoy])
                    msg = f"🚨 **¡HOY ESTRENAN {len(caps_hoy)} CAPÍTULOS!** 🚨\n\n📺 **{s['name']}**\n🔢 Temporada {num_temp}\n{lista}"
                else:
                    msg = f"🚨 **¡HOY ESTRENA CAPÍTULO!** 🚨\n\n📺 **{s['name']}**\n🔢 Temporada {num_temp}\n🎞️ Cap {prox['episode_number']}: {prox['name']}"
                
                if img_url: await update.message.reply_photo(photo=img_url, caption=msg, parse_mode='Markdown')
                else: await update.message.reply_text(msg, parse_mode='Markdown')
                
        if not encontrado:
            await update.message.reply_text("❌ Hoy no hay estrenos de tus series.")
            
    except Exception as e:
        await update.message.reply_text("Error consultando la base de datos.")

async def lista_seguimiento(update, context):
    try:
        u_id = str(update.effective_user.id)
        user_data = coleccion.find_one({"user_id": u_id})
        
        if not user_data or not user_data.get('series'):
            await update.message.reply_text("No seguís ninguna serie.")
            return

        msg = "📋 **Tus series seguidas:**\n\n"
        for s in user_data['series']:
            msg += f"• {s['name']}\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text("Error al leer la lista.")

if __name__ == '__main__':
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    
    # --- CONFIGURACIÓN DE TAREA DIARIA ---
    tz_israel = pytz.timezone('Asia/Jerusalem')
    app.job_queue.run_daily(tarea_diaria, time=time(9, 0, 0, tzinfo=tz_israel))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    app.add_handler(CommandHandler("seguir", seguir))
    app.add_handler(CommandHandler("borrar", borrar))
    app.add_handler(CommandHandler("revisar", revisar_estrenos))
    app.add_handler(CommandHandler("lista", lista_seguimiento))
    app.run_polling()
