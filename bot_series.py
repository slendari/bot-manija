import requests
import os
import threading
import logging
from datetime import datetime, time, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, TypeHandler, filters, ContextTypes
from pymongo import MongoClient
from flask import Flask

# --- LOGGING (para ver qué pasa en Render sin adivinar) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- CONFIGURACIÓN (Segura mediante variables de entorno) ---
TOKEN_TELEGRAM = os.environ.get('TOKEN_TELEGRAM')
API_KEY_TMDB = os.environ.get('API_KEY_TMDB')
MONGO_URI = os.environ.get('MONGO_URI')

client = MongoClient(MONGO_URI)
db = client['el_manija_db']
coleccion = db['usuarios_series']

# --- SERVIDOR WEB ESTABLE CON FLASK ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "El Manija TV sigue vivo!", 200

def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

def tmdb_json(url):
    """GET a TMDB con timeout, para que una respuesta colgada no congele el bot."""
    return requests.get(url, timeout=10).json()

def buscar_en_tmdb(nombre):
    res = tmdb_json(f"https://api.themoviedb.org/3/search/tv?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES")
    return res['results'][0] if res.get('results') else None

def formatear_fecha(fecha_str):
    if not fecha_str: return "Sin fecha"
    meses = {"01":"Enero", "02":"Febrero", "03":"Marzo", "04":"Abril", "05":"Mayo", "06":"Junio", "07":"Julio", "08":"Agosto", "09":"Septiembre", "10":"Octubre", "11":"Noviembre", "12":"Diciembre"}
    y, m, d = fecha_str.split('-')
    return f"{int(d)} de {meses[m]}, {y}"

def hoy_local():
    tz = pytz.timezone('Asia/Jerusalem')
    return datetime.now(tz).strftime("%Y-%m-%d")

def manana_local():
    tz = pytz.timezone('Asia/Jerusalem')
    return (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")

def descripcion_estreno(caps, num_temp):
    """Más de 3 capítulos el mismo día = se estrena la temporada completa."""
    if len(caps) > 3:
        return f"Nueva temporada {num_temp}"
    return ", ".join([f"Cap {ep['episode_number']}" for ep in caps]) + f", Temporada {num_temp}"

def obtener_poster_temporada(serie_id, num_temp, poster_default):
    try:
        url = f"https://api.themoviedb.org/3/tv/{serie_id}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES"
        res = tmdb_json(url)
        poster = res.get('poster_path') or poster_default
        return f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
    except:
        return f"https://image.tmdb.org/t/p/w500{poster_default}" if poster_default else None

# --- FUNCIÓN DE AVISO AUTOMÁTICO (12 AM): estrenos de hoy y de mañana ---
async def tarea_diaria(context: ContextTypes.DEFAULT_TYPE):
    hoy = hoy_local()
    manana = manana_local()
    try:
        usuarios = list(coleccion.find())
    except Exception:
        logger.exception("Error al conectar con Mongo en la tarea diaria")
        return

    for user_data in usuarios:
        u_id = user_data['user_id']
        for s in user_data.get('series', []):
            try:
                det = tmdb_json(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES")
                prox = det.get('next_episode_to_air')

                # Si el próximo episodio no es hoy ni mañana, no hay nada que avisar
                if not prox or prox.get('air_date') not in (hoy, manana):
                    continue

                num_t = prox['season_number']
                temp_data = tmdb_json(f"https://api.themoviedb.org/3/tv/{s['id']}/season/{num_t}?api_key={API_KEY_TMDB}&language=es-ES")
                episodios = temp_data.get('episodes', [])
                caps_hoy = [ep for ep in episodios if ep.get('air_date') == hoy]
                caps_manana = [ep for ep in episodios if ep.get('air_date') == manana]

                avisos = []
                if caps_hoy:
                    avisos.append(f"📺 {s['name']}\n🔔 Hoy hay estrenos!\n🔢 {descripcion_estreno(caps_hoy, num_t)}")
                if caps_manana:
                    avisos.append(f"📺 {s['name']}\n⏰ Mañana hay estrenos!\n🔢 {descripcion_estreno(caps_manana, num_t)}")
                if not avisos:
                    continue

                img_url = obtener_poster_temporada(s['id'], num_t, det.get('poster_path'))
                for texto in avisos:
                    if img_url: await context.bot.send_photo(chat_id=u_id, photo=img_url, caption=texto)
                    else: await context.bot.send_message(chat_id=u_id, text=texto)
            except Exception:
                logger.exception(f"Error revisando estrenos de {s.get('name')} para el usuario {u_id}")

# --- COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = str(update.effective_user.id)
    nombre_user = update.effective_user.first_name

    user_data = coleccion.find_one({"user_id": u_id})

    if not user_data:
        coleccion.insert_one({"user_id": u_id, "nombre": nombre_user, "series": []})
    else:
        coleccion.update_one({"user_id": u_id}, {"$set": {"nombre": nombre_user}})

    await update.message.reply_text(
        f"¡Qué hacés {nombre_user}! Acá El ManijaTV 🍿.\n\n"
        "• /ver [serie] - Info del próximo estreno.\n"
        "• /seguir [serie] - Guardar serie en tu lista.\n"
        "• /borrar [serie] - Dejar de seguir una serie.\n"
        "• /revisar - Ver si hoy se estrena algo de tu lista.\n"
        "• /lista - Ver todas las series que seguís.\n"
        "• /sinopsis [serie] - Leer una sinopsis de cualquier serie."
    )

# --- ELECCIÓN DE SERIE CON BOTONES ---
def buscar_opciones(nombre, incluir_peliculas=False, maximo=5):
    """Devuelve hasta `maximo` resultados de TMDB para que el usuario elija."""
    endpoint = "multi" if incluir_peliculas else "tv"
    res = tmdb_json(f"https://api.themoviedb.org/3/search/{endpoint}?api_key={API_KEY_TMDB}&query={nombre}&language=es-ES")
    resultados = []
    for r in res.get('results', []):
        tipo = r.get('media_type', 'tv')  # /search/tv no trae media_type
        if tipo in ('tv', 'movie'):
            r['media_type'] = tipo
            resultados.append(r)
    return resultados[:maximo]

def etiqueta_opcion(r):
    nombre = r.get('name') or r.get('title') or "Sin nombre"
    fecha = r.get('first_air_date') or r.get('release_date') or ""
    anio = f" ({fecha[:4]})" if fecha else ""
    icono = "🎬" if r['media_type'] == 'movie' else "📺"
    return f"{icono} {nombre}{anio}"

async def mostrar_opciones(update, accion, nombre, incluir_peliculas=False):
    """Si hay un solo resultado lo ejecuta directo; si hay varios, muestra botones."""
    resultados = buscar_opciones(nombre, incluir_peliculas)
    if not resultados:
        await update.message.reply_text("No encontré nada con ese nombre.")
        return
    if len(resultados) == 1:
        r = resultados[0]
        await ejecutar_accion(update.message, str(update.effective_user.id), accion, r['media_type'], r['id'])
        return
    botones = [
        [InlineKeyboardButton(etiqueta_opcion(r), callback_data=f"{accion}:{r['media_type']}:{r['id']}")]
        for r in resultados
    ]
    await update.message.reply_text("Encontré varias, elegí cuál:", reply_markup=InlineKeyboardMarkup(botones))

async def elegir_opcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    accion, tipo, id_str = query.data.split(":")
    try:
        await query.edit_message_reply_markup(reply_markup=None)  # saca los botones para no tocar dos veces
    except Exception:
        pass
    await ejecutar_accion(query.message, str(query.from_user.id), accion, tipo, int(id_str))

async def ejecutar_accion(msg, u_id, accion, tipo, id_tmdb):
    if accion == "ver":
        await ver_serie(msg, id_tmdb)
    elif accion == "seg":
        await seguir_serie(msg, u_id, id_tmdb)
    elif accion == "sin":
        await sinopsis_titulo(msg, tipo, id_tmdb)

# --- /ver ---
async def ver(update, context):
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("Decime qué serie buscar.")
        return
    await mostrar_opciones(update, "ver", nombre)

async def ver_serie(msg, serie_id):
    det = tmdb_json(f"https://api.themoviedb.org/3/tv/{serie_id}?api_key={API_KEY_TMDB}&language=es-ES")
    nombre = det.get('name', 'Sin nombre')
    hoy = hoy_local()
    prox_tmdb = det.get('next_episode_to_air')
    ult_tmdb = det.get('last_episode_to_air')
    num_temp = prox_tmdb['season_number'] if prox_tmdb else (ult_tmdb['season_number'] if ult_tmdb else None)

    if num_temp is not None:
        temp_data = tmdb_json(f"https://api.themoviedb.org/3/tv/{serie_id}/season/{num_temp}?api_key={API_KEY_TMDB}&language=es-ES")
        episodes = temp_data.get('episodes', [])
        eps_pendientes = [ep for ep in episodes if ep.get('air_date') and ep['air_date'] >= hoy]

        if eps_pendientes:
            fecha_prox = eps_pendientes[0]['air_date']
            caps_dia = [ep for ep in eps_pendientes if ep['air_date'] == fecha_prox]
            caps_sig = [ep for ep in eps_pendientes if ep['air_date'] > fecha_prox]

            if fecha_prox == hoy:
                det_estreno = f"Nueva temporada {num_temp}" if len(caps_dia) > 3 else ", ".join([f"Cap {ep['episode_number']}" for ep in caps_dia]) + f", Temporada {num_temp}"
                img_url = obtener_poster_temporada(serie_id, num_temp, det.get('poster_path'))
                texto = f"📺 {nombre}\n🔔 Hoy hay estrenos!\n🔢 {det_estreno}"
                if img_url: await msg.reply_photo(photo=img_url, caption=texto)
                else: await msg.reply_text(texto)
            else:
                texto = f"📺 {nombre}\n❌ Hoy no hay estrenos.\n\n📅 Próximos estrenos:\n🔢 Temporada {num_temp}\n"
                for ep in (caps_dia + caps_sig)[:3]:
                    texto += f"- Cap {ep['episode_number']}: {formatear_fecha(ep['air_date'])}\n"
                await msg.reply_text(texto)
        else:
            await msg.reply_text(f"📺 {nombre}\n❌ No hay fechas confirmadas.")
    else:
        await msg.reply_text(f"📺 {nombre}\n❌ No hay fechas confirmadas.")

# --- /seguir ---
async def seguir(update, context):
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("Decime qué serie querés seguir.")
        return
    await mostrar_opciones(update, "seg", nombre)

async def seguir_serie(msg, u_id, serie_id):
    det = tmdb_json(f"https://api.themoviedb.org/3/tv/{serie_id}?api_key={API_KEY_TMDB}&language=es-ES")
    nombre = det.get('name', 'Sin nombre')

    user_data = coleccion.find_one({"user_id": u_id})
    series_lista = user_data['series'] if user_data else []
    if serie_id in [s['id'] for s in series_lista]:
        await msg.reply_text(f"📺 {nombre}\nEsa serie ya está en tu lista.")
        return

    series_lista.append({'id': serie_id, 'name': nombre})
    coleccion.update_one({"user_id": u_id}, {"$set": {"series": series_lista}}, upsert=True)

    prox = det.get('next_episode_to_air') or det.get('last_episode_to_air')
    num_t = prox['season_number'] if prox else 1
    img_url = obtener_poster_temporada(serie_id, num_t, det.get('poster_path'))

    texto = f"📺 {nombre}\n✅ Añadido a tu lista."
    if img_url: await msg.reply_photo(photo=img_url, caption=texto)
    else: await msg.reply_text(texto)

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
        det = tmdb_json(f"https://api.themoviedb.org/3/tv/{s['id']}?api_key={API_KEY_TMDB}&language=es-ES")
        prox = det.get('next_episode_to_air')
        if prox and prox['air_date'] == hoy:
            encontrado = True
            num_t = prox['season_number']
            temp_data = tmdb_json(f"https://api.themoviedb.org/3/tv/{s['id']}/season/{num_t}?api_key={API_KEY_TMDB}&language=es-ES")
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
    await update.message.reply_text(
        'No te entendí 🤷.\n'
        'Usá un comando del botón "Menú" para interactuar conmigo.'
    )

async def sinopsis(update, context):
    nombre = " ".join(context.args)
    if not nombre:
        await update.message.reply_text("Decime de qué serie o peli querés la sinopsis.")
        return
    await mostrar_opciones(update, "sin", nombre, incluir_peliculas=True)

async def sinopsis_titulo(msg, tipo, id_tmdb):
    det = tmdb_json(f"https://api.themoviedb.org/3/{tipo}/{id_tmdb}?api_key={API_KEY_TMDB}&language=es-ES")

    nombre_final = det.get('name') or det.get('title')
    resumen = det.get('overview') or "No hay sinopsis disponible en español por ahora."
    poster = det.get('poster_path')
    img_url = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None

    texto = f"📖 **{nombre_final}**\n\n{resumen}"

    if img_url:
        await msg.reply_photo(photo=img_url, caption=texto, parse_mode='Markdown')
    else:
        await msg.reply_text(texto, parse_mode='Markdown')

ADMIN_ID = os.environ.get('ADMIN_ID')

async def difundir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if user_id != ADMIN_ID:
        await update.message.reply_text("No tenés permiso para hacer esto, fiera.")
        return

    mensaje = " ".join(context.args)
    if not mensaje:
        await update.message.reply_text("Che, escribí algo para mandar.")
        return

    usuarios = coleccion.find()
    exitos = 0
    errores = 0

    for u in usuarios:
        try:
            await context.bot.send_message(
                chat_id=u['user_id'],
                text=f"📢 **MENSAJE IMPORTANTE**\n\n{mensaje}",
                parse_mode='Markdown'
            )
            exitos += 1
        except Exception:
            errores += 1

    await update.message.reply_text(f"✅ Difusión terminada.\nEnviados: {exitos}\nFallidos (bloqueados): {errores}")

async def ver_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        await update.message.reply_text("¿Qué hacés chusmeando? No tenés permiso.")
        return

    usuarios = coleccion.find()
    lista_msg = "👥 **Usuarios registrados:**\n\n"

    contador = 0
    for u in usuarios:
        contador += 1
        nombre = u.get('nombre', 'Anónimo (debe poner /start)')
        u_id = u['user_id']
        cant = len(u.get('series', []))

        lista_msg += f"{contador}. **{nombre}** (ID: `{u_id}`) - Series: {cant}\n"

    if contador == 0:
        await update.message.reply_text("No hay nadie todavía.")
    else:
        await update.message.reply_text(lista_msg, parse_mode='Markdown')

# --- MANEJADOR GLOBAL DE ERRORES ---
# Atrapa cualquier excepción no controlada que salte en un handler.
# Antes: el bot se quedaba mudo y el error solo se veía escarbando en los logs.
# Ahora: se loguea igual, pero además el usuario recibe un aviso.
async def manejador_errores(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Excepción no controlada procesando un update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Uy, tuve un problema procesando eso. Probá de nuevo en un ratito 🛠️"
            )
        except Exception:
            logger.exception("No pude ni siquiera avisarle al usuario del error")

# Deja una línea en los logs por cada mensaje o botón que le llega al bot.
# Sirve para saber si Telegram está entregando los toques de botones.
async def registrar_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        logger.info("Update recibido: botón tocado (%s)", update.callback_query.data)
    elif update.message:
        logger.info("Update recibido: mensaje")
    else:
        logger.info("Update recibido: otro tipo")

if __name__ == '__main__':
    threading.Thread(target=keep_alive, daemon=True).start()

    app = Application.builder().token(TOKEN_TELEGRAM).build()

    tz_israel = pytz.timezone('Asia/Jerusalem')
    app.job_queue.run_daily(tarea_diaria, time=time(0, 0, 0, tzinfo=tz_israel))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ver", ver))
    app.add_handler(CommandHandler("seguir", seguir))
    app.add_handler(CommandHandler("borrar", borrar))
    app.add_handler(CommandHandler("revisar", revisar_estrenos))
    app.add_handler(CommandHandler("lista", lista_seguimiento))
    app.add_handler(CommandHandler("sinopsis", sinopsis))
    app.add_handler(CommandHandler("difundir", difundir))
    app.add_handler(CommandHandler("usuarios", ver_usuarios))

    app.add_handler(CallbackQueryHandler(elegir_opcion, pattern=r"^(ver|seg|sin):(tv|movie):\d+$"))

    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, desconocido))

    app.add_handler(TypeHandler(Update, registrar_update), group=-1)

    app.add_error_handler(manejador_errores)

    app.run_polling(allowed_updates=Update.ALL_TYPES)
