import requests
import os
import threading
import http.server
import socketserver
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient

# --- CONFIGURACIÓN (Segura mediante variables de entorno) ---
TOKEN_TELEGRAM = os.environ.get('TOKEN_TELEGRAM')
API_KEY_TMDB = os.environ.get('API_KEY_TMDB')
MONGO_URI = os.environ.get('MONGO_URI')

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
    tz = pytz.timezone('Asia/Jerusalem')
    return datetime.now(tz).strftime("%Y-%m-%d")

def obtener_poster_temporada(serie_id, num_temp, poster_default):
    try:
        url = f"https://api.themoviedb.org/3/tv/{serie_id}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES"
        res = requests.get(url).json()
        poster = res.get('poster_path') or poster_default
        return f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
    except:
        return f"https://image.tmdb.org/t/p/w500{poster_default}" if poster_default else None

# --- FUNCIÓN DE AVISO AUTOMÁTICO (9 AM) ---
async def tarea_diaria(context: ContextTypes.DEFAULT_TYPE):
    hoy = hoy_local()
    usuarios = coleccion.find()
    
    for user_data in usuarios:
        u_id = user_data['user_id']
        for s in user_data.get('series', []):
            det = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
            prox = det.get('next_episode_to_air')
            
            if prox and prox['air_date'] == hoy:
                num_t = prox['season_number']
                temp_data = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}/season/{num_t}?api_key={API_KEY_TMDB}&language=es-ES").json()
                caps_hoy = [ep for ep in temp_data.get('episodes', []) if ep['air_date'] == hoy]
                
                det_estreno = f"Nueva temporada {num_t}" if len(caps_hoy) > 3 else ", ".join([f"Cap {ep['episode_number']}" for ep in caps_hoy]) + f", Temporada {num_t}"
                img_url = obtener_poster_temporada(s['id'], num_t, det.get('poster_path'))
                msg = f"📺 {s['name']}\n🔔 Hoy hay estrenos!\n🔢 {det_estreno}"

                if img_url: await context.bot.send_photo(chat_id=u_id, photo=img_url, caption=msg)
                else: await context.bot.send_message(chat_id=u_id, text=msg)

# --- COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Qué hacés bebé! Acá El ManijaTV 🍿. \n\n"
        "/ver [serie] - Info del próximo estreno.\n"
        "/seguir [serie] - Guardar serie en tu lista.\n"
        "/borrar [serie] - Dejar de seguir una serie.\n"
        "/revisar - Ver si hoy se estrena algo de tu lista.\n"
        "/lista - Ver todas las series que seguís."
    )

async def ver(update, context):
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("Decime qué serie buscar.")
        return
    serie = buscar_en_tmdb(nombre)
    if not serie:
        await update.message.reply_text("No encontré esa serie.")
        return

    det = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
    hoy = hoy_local()
    prox_tmdb = det.get('next_episode_to_air')
    ult_tmdb = det.get('last_episode_to_air')
    num_temp = prox_tmdb['season_number'] if prox_tmdb else (ult_tmdb['season_number'] if ult_tmdb else None)

    if num_temp is not None:
        temp_data = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES").json()
        episodes = temp_data.get('episodes', [])
        eps_pendientes = [ep for ep in episodes if ep.get('air_date') and ep['air_date'] >= hoy]
        
        if eps_pendientes:
            fecha_prox = eps_pendientes[0]['air_date']
            caps_dia = [ep for ep in eps_pendientes if ep['air_date'] == fecha_prox]
            caps_sig = [ep for ep in eps_pendientes if ep['air_date'] > fecha_prox]
            
            if fecha_prox == hoy:
                det_estreno = f"Nueva temporada {num_temp}" if len(caps_dia) > 3 else ", ".join([f"Cap {ep['episode_number']}" for ep in caps_dia]) + f", Temporada {num_temp}"
                img_url = obtener_poster_temporada(serie['id'], num_temp, det.get('poster_path'))
                msg = f"📺 {serie['name']}\n🔔 Hoy hay estrenos!\n🔢 {det_estreno}"
                if img_url: await update.message.reply_photo(photo=img_url, caption=msg)
                else: await update.message.reply_text(msg)
            else:
                msg = f"📺 {serie['name']}\n❌ Hoy no hay estrenos.\n\n📅 Próximos estrenos:\n🔢 Temporada {num_temp}\n"
                for ep in (caps_dia + caps_sig)[:3]:
                    msg += f"- Cap {ep['episode_number']}: {formatear_fecha(ep['air_date'])}\n"
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text(f"📺 {serie['name']}\n❌ No hay fechas confirmadas.")
    else:
        await update.message.reply_text(f"📺 {serie['name']}\n❌ No hay fechas confirmadas.")

async def seguir(update, context):
    try:
        nombre = " ".join(context.args)
        if not nombre: return
        serie = buscar_en_tmdb(nombre)
        if serie:
            u_id = str(update.effective_user.id)
            user_data = coleccion.find_one({"user_id": u_id})
            series_lista = user_data['series'] if user_data else []
            if serie['id'] not in [s['id'] for s in series_lista]:
                series_lista.append({'id': serie['id'], 'name': serie['name']})
                coleccion.update_one({"user_id": u_id}, {"$set": {"series": series_lista}}, upsert=True)
                
                det = requests.get(f"https://api.themoviedb.org/3/tv/{serie['id']}?api_key={API_KEY_TMDB}&language=es-ES").json()
                prox = det.get('next_episode_to_air') or det.get('last_episode_to_air')
                num_t = prox['season_number'] if prox else 1
                img_url = obtener_poster_temporada(serie['id'], num_t, det.get('poster_path'))

                msg = f"📺 {serie['name']}\n✅ Añadido a tu lista."
                if img_url: await update.message.reply_photo(photo=img_url, caption=msg)
                else: await update.message.reply_text(msg)
            else:
                await update.message.reply_text(f"Esa serie ya está en tu lista.")
    except:
        await update.message.reply_text("Error con la base de datos.")

async def borrar(update, context):
    nombre = " ".join(context.args)
    if not nombre: return
    u_id = str(update.effective_user.id)
    user_data = coleccion.find_one({"user_id": u_id})
    if not user_data or not user_data.get('series'): return
    
    serie_tmdb = buscar_en_tmdb(nombre)
    if serie_tmdb:
        id_b = serie_tmdb['id']
        nueva = [s for s in user_data['series'] if s['id'] != id_b]
        if len(nueva) < len(user_data['series']):
            coleccion.update_one({"user_id": u_id}, {"$set": {"series": nueva}})
            await update.message.reply_text(f"📺 {serie_tmdb['name']}\n🗑️ Eliminado de tu lista.")
            return

    nueva = [s for s in user_data['series'] if nombre.lower() in s['name'].lower()]
    if len(nueva) < len(user_data['series']):
        nombre_real = nueva[0]['name'] if len(nueva) == 1 else nombre.capitalize()
        coleccion.update_one({"user_id": u_id}, {"$set": {"series": [s for s in user_data['series'] if nombre.lower() not in s['name'].lower()]}})
        await update.message.reply_text(f"📺 {nombre_real}\n🗑️ Eliminado de tu lista.")
    else:
        await update.message.reply_text("No está esa serie en tu lista.")

async def revisar_estrenos(update, context):
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
            num_t = prox['season_number']
            temp_data = requests.get(f"https://api.themoviedb.org/3/tv/{s['id']}/season/{num_t}?api_key={API_KEY_TMDB}&language=es-ES").json()
            caps_hoy = [ep for ep in temp_data.get('episodes', []) if ep['air_date'] == hoy]
            
            det_estreno = f"Nueva temporada {num_t}" if len(caps_hoy) > 3 else ", ".join([f"Cap {ep['episode_number']}" for ep in caps_hoy]) + f", Temporada {num_t}"
            img_url = obtener_poster_temporada(s['id'], num_t, det.get('poster_path'))
            msg = f"📺 {s['name']}\n🔔 Hoy hay estrenos!\n🔢 {det_estreno}"
            
            if img_url: await update.message.reply_photo(photo=img_url, caption=msg)
            else: await update.message.reply_text(msg)
                
    if not encontrado:
        await update.message.reply_text("❌ Hoy no hay estrenos de tus series.")

async def lista_seguimiento(update, context):
    u_id = str(update.effective_user.id)
    user_data = coleccion.find_one({"user_id": u_id})
    if not user_data or not user_data.get('series'):
        await update.message.reply_text("No hay ninguna serie en tu lista.")
        return
    msg = "📋 **Tu lista de series:**\n\n" + "\n".join([f"• {s['name']}" for s in user_data['series']])
    await update.message.reply_text(msg, parse_mode='Markdown')

async def desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.startswith('/'):
        await update.message.reply_text('No te entendí 🤷.\nUsá un comando del botón "Menú".')

if __name__ == '__main__':
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(TOKEN_TELEGRAM).build()
    
    tz_israel = pytz.timezone('Asia/Jerusalem')
    app.job_queue.run_daily(tarea_diaria, time=time(9, 0, 0, tzinfo=tz_israel))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    app.add_handler(CommandHandler("seguir", seguir))
    app.add_handler(CommandHandler("borrar", borrar))
    app.add_handler(CommandHandler("revisar", revisar_estrenos))
    app.add_handler(CommandHandler("lista", lista_seguimiento))
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, desconocido))
    app.run_polling()
