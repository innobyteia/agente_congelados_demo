from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os, requests, openai, json, time, logging, random, re
from typing import Dict, List, Optional
from datetime import datetime

# ==== Setup ====
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VendedorInteligente")

# ==== Datos ====
PRODUCTOS = {
    "empanadas": {"nombre": "Empanadas", "precio": 1500, "descripcion": "Crujientes rellenas de carne o pollo"},
    "pasteles de pollo": {"nombre": "Pasteles de pollo", "precio": 2500, "descripcion": "Suaves y con verduras frescas"},
    "pizza personal": {"nombre": "Pizza personal", "precio": 5900, "descripcion": "Deliciosa pizza individual"},
}

PROMOCIONES = ["🎉 Compra 10 empanadas y lleva 2 GRATIS!", "🔥 Pizza + deditos por $9,900"]
SALUDOS = ["¡Hola! 😊 Bienvenido a Congelados Deliciosos. Soy tu Vendedor Inteligente.", "¡Qué gusto verte por aquí! 👋 Soy tu Vendedor Inteligente, listo para ayudarte."]
DESPEDIDAS = ["¡Gracias por tu visita! Hasta pronto 😊", "¡Fue un placer ayudarte!"]
ESTADOS: Dict[str, Dict] = {}

# ==== Utilidades ====
def get_time_emoji():
    hour = datetime.now().hour
    if hour < 12: return "☀️"
    if hour < 18: return "🌤️"
    return "🌙"

def formatear_respuesta_web(mensaje: str):
    return mensaje.replace("\n", "<br>")

def extraer_productos_y_cantidades(texto: str) -> List[Dict]:
    items = []
    for producto in PRODUCTOS:
        if producto in texto:
            match = re.search(r"(\d+)\s+" + re.escape(producto), texto)
            cantidad = int(match.group(1)) if match else 1
            items.append({"producto": producto, "cantidad": cantidad})
    return items

# ==== LLM fallback para intenciones complejas ====
def interpretar_mensaje_con_LLM(texto_usuario: str, estado_actual=None):
    resumen = "\n".join([f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']}" for i in estado_actual.get("items", [])]) if estado_actual else "Ninguno."
    prompt = f"""
Eres Tu Vendedor Inteligente, un asistente amable y profesional de congelados. Detecta la intención:
Usuario dice: "{texto_usuario}"
Pedido actual:
{resumen}
Devuelve solo JSON válido con:
{{"intencion": "menu|pedido|saludo|despedida|pago|entrega|detalles_producto|recomendacion|no_entendido", "respuesta": "Texto conversacional con emojis."}}
"""
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error("LLM fallback error", exc_info=e)
        return {"intencion": "no_entendido", "respuesta": "Lo siento 😅 ¿Puedes repetirlo?"}

# ==== Endpoints ====
class MensajeWeb(BaseModel):
    texto: str
    usuario_id: str

@app.post("/webhook/demo")
async def webhook_demo(mensaje: MensajeWeb):
    uid = mensaje.usuario_id
    texto = mensaje.texto.strip().lower()
    if uid not in ESTADOS:
        ESTADOS[uid] = {"items": [], "historia": [], "timestamp": time.time(), "metodo": None, "entrega": None}
    estado = ESTADOS[uid]

    if texto in ["hola", "buenos días", "buenas", "hey"]:
        respuesta = random.choice(SALUDOS) + f" {random.choice(PROMOCIONES)}"
        return {"respuesta": formatear_respuesta_web(respuesta), "estado": "saludo"}

    if "menú" in texto or "productos" in texto:
        productos = "\n".join([f"• {p['nombre']} - ${p['precio']:,}" for p in PRODUCTOS.values()])
        return {"respuesta": formatear_respuesta_web(f"Aquí va nuestro menú 🧊:\n\n{productos}"), "estado": "menu"}

    if "gracias" in texto or "chao" in texto:
        return {"respuesta": formatear_respuesta_web(random.choice(DESPEDIDAS)), "estado": "despedida"}

    items = extraer_productos_y_cantidades(texto)
    if items:
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in items)
        estado["items"].extend(items)
        respuesta = "🛒 Pedido actualizado:\n" + "\n".join([f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}" for i in items])
        return {"respuesta": formatear_respuesta_web(respuesta + f"\nTotal: ${total:,}\n¿Deseas algo más?"), "estado": "pedido"}

    resultado = interpretar_mensaje_con_LLM(texto, estado_actual=estado)
    intencion = resultado.get("intencion")

    if intencion == "entrega":
        estado["entrega"] = "domicilio"
        link_politica = "https://congelados-demo.com/politica-datos"
        return {"respuesta": formatear_respuesta_web(
            f"📦 Perfecto. Para envío a domicilio, protegemos tus datos según nuestra política: {link_politica}\nAlguien del equipo se pondrá en contacto para confirmar y despachar tu pedido. ¡Gracias por tu compra! 🎉"),
            "estado": "entrega_confirmada"}

    if intencion == "pago":
        estado["metodo"] = "transferencia"
        return {"respuesta": formatear_respuesta_web("💳 Puedes pagar por transferencia o en efectivo. ¿Qué prefieres?"), "estado": "pago"}

    estado["historia"].append(f"Cliente: {texto}")
    estado["historia"].append(f"Bot: {resultado.get('respuesta')}")
    return {"respuesta": formatear_respuesta_web(resultado["respuesta"]), "estado": intencion or "no_entendido"}

@app.post("/webhook/demo/reset")
async def reset(uid: str):
    ESTADOS.pop(uid, None)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Tu Vendedor Inteligente está activo 🤖"}

