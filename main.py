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
    # Resumen del pedido para contexto
    resumen = "\n".join([
        f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']}"
        for i in (estado_actual.get("items", []) if estado_actual else [])
    ]) or "Ninguno."

    catalogo = "\n".join([
        f"{p['nombre']} - ${p['precio']} ({p['descripcion']})"
        for p in PRODUCTOS.values()
    ])
    nombres_disponibles = ", ".join(PRODUCTOS.keys())

    prompt = f"""
Actúas como "Tu Vendedor Inteligente", un asistente conversacional cálido y profesional para una tienda de productos congelados "Congelados Deliciosos".
Objetivo: interpretar el mensaje y responder de forma humana (amable, clara y CTA).

CATÁLOGO:
{catalogo}

PEDIDO ACTUAL:
{resumen}

MENSAJE DEL CLIENTE:
"{texto_usuario}"

REGLAS IMPORTANTES (aplícalas SIEMPRE):
- Si preguntan “¿qué vendes?”, “¿qué tienes?”, “¿tienes más productos?” → intención "menu" y ofrece el catálogo.
- Si piden algo que NO está en catálogo (p. ej. “bebidas”, “postres” que no tengas), responde con intención "no_disponible": explica con amabilidad que no lo manejas y sugiere 1-3 productos del catálogo.
- Si piden recomendaciones (reunión, niños, algo rápido), usa intención "recomendacion" con propuestas reales del catálogo.
- Si el mensaje es ambiguo, usa intención "no_entendido", reformula y pregunta con calidez.
- Siempre termina con una PREGUNTA amable que invite a continuar.

Devuelve SOLO JSON válido con esta estructura (usa solo los campos necesarios):
{{
  "intencion": "menu|pedido|saludo|despedida|pago|entrega|detalles_producto|recomendacion|no_disponible|no_entendido|confirmar",
  "items": [{{"producto":"empanadas","cantidad":2}}],        # si aplica
  "metodo": "transferencia|efectivo|",                        # si aplica (pago)
  "modo": "domicilio|tienda|",                                # si aplica (entrega)
  "tema": "empanadas|pizza|...",                              # si aplica (detalles_producto o no_disponible)
  "respuesta": "Texto conversacional con emojis (máx 150 palabras)"
}}
"""

    try:
        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Responde solo con JSON válido y conversacional. No incluyas explicaciones fuera del JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error("LLM fallback error", exc_info=e)
        return {
            "intencion": "no_entendido",
            "respuesta": "Lo siento 😅 no logré entender bien. ¿Podrías decirlo de otra forma?"
        }


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

    # Saludo simple
    if texto in ["hola", "buenos días", "buenas", "hey", "hola!"]:
        respuesta = random.choice(SALUDOS) + f" {random.choice(PROMOCIONES)}"
        return {"respuesta": formatear_respuesta_web(respuesta), "estado": "saludo"}

    # Menú directo por keyword
    if any(k in texto for k in ["menú", "menu", "productos", "qué vendes", "que vendes", "qué tienes", "que tienes"]):
        productos = "\n".join([f"• {p['nombre']} - ${p['precio']:,}" for p in PRODUCTOS.values()])
        return {"respuesta": formatear_respuesta_web(f"Aquí va nuestro menú 🧊:\n\n{productos}\n\n¿Te antoja algo? 😋"), "estado": "menu"}

    # Despedida
    if any(k in texto for k in ["gracias", "chao", "adiós", "adios", "hasta luego"]):
        return {"respuesta": formatear_respuesta_web(random.choice(DESPEDIDAS)), "estado": "despedida"}

    # Extracción rápida de items (num + producto en el texto)
    items_detectados = extraer_productos_y_cantidades(texto)
    if items_detectados:
        estado["items"].extend(items_detectados)
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
        desglose = "\n".join([f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}" for i in estado["items"]])
        respuesta = f"🛒 ¡Perfecto! He actualizado tu pedido:\n{desglose}\n\nTotal: ${total:,}\n¿Quieres agregar algo más o pasamos al pago? 💳"
        return {"respuesta": formatear_respuesta_web(respuesta), "estado": "pedido"}

    # === LLM conversacional ===
    resultado = interpretar_mensaje_con_LLM(texto, estado_actual=estado)
    intencion = resultado.get("intencion")
    respuesta_llm = resultado.get("respuesta", "")

    # Guarda historia
    estado["historia"].append(f"Cliente: {texto}")
    estado["historia"].append(f"Bot: {respuesta_llm}")

    # ----- Manejo por intención -----
    if intencion == "menu":
        # Muestra menú (aunque el LLM ya respondió algo amable)
        productos = "\n".join([f"• {p['nombre']} - ${p['precio']:,}" for p in PRODUCTOS.values()])
        resp = respuesta_llm or f"Aquí va nuestro menú 🧊:\n\n{productos}\n\n¿Te antoja algo? 😋"
        return {"respuesta": formatear_respuesta_web(resp), "estado": "menu"}

    if intencion == "pedido":
        nuevos = resultado.get("items", [])
        if nuevos:
            # suma/merge al carrito
            for n in nuevos:
                if not n or "producto" not in n or n["producto"] not in PRODUCTOS:
                    continue
                ya = next((i for i in estado["items"] if i["producto"] == n["producto"]), None)
                if ya: ya["cantidad"] += n.get("cantidad", 1)
                else:  estado["items"].append({"producto": n["producto"], "cantidad": n.get("cantidad", 1)})
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
        desglose = "\n".join([f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}" for i in estado["items"]]) or "— vacío —"
        texto_resp = respuesta_llm or f"🛒 Pedido actualizado:\n{desglose}\n\nTotal: ${total:,}\n¿Deseas algo más o pasamos al pago? 💳"
        return {"respuesta": formatear_respuesta_web(texto_resp), "estado": "pedido"}

    if intencion == "pago":
        # Respeta lo que diga el LLM si trae 'metodo'
        metodo = resultado.get("metodo")
        if metodo:
            estado["metodo"] = metodo
            return {"respuesta": formatear_respuesta_web(f"💳 Perfecto, registré *{metodo}*. ¿Confirmamos el pedido? ✅"), "estado": "pago"}
        # Si no vino método, usa respuesta LLM como guía
        return {"respuesta": formatear_respuesta_web(respuesta_llm or "💳 Aceptamos transferencia o efectivo. ¿Cuál prefieres?"), "estado": "pago"}

    if intencion == "entrega":
        # Ahora soporta 'modo': domicilio | tienda
        modo = resultado.get("modo")
        if modo == "domicilio":
            estado["entrega"] = "domicilio"
            link_politica = "https://congelados-demo.com/politica-datos"
            txt = (
                f"📦 ¡Listo! Enviaremos tu pedido a domicilio. "
                f"Tus datos serán tratados según nuestras [Políticas de Datos]({link_politica}). "
                f"Un asesor te contactará para coordinar el despacho. ¿Deseas confirmar ahora? ✅"
            )
            return {"respuesta": formatear_respuesta_web(txt), "estado": "entrega_confirmada"}
        elif modo == "tienda":
            estado["entrega"] = "tienda"
            txt = "🏪 Perfecto, lo prepararemos para *recoger en tienda*. ¿Quieres confirmar tu pedido ahora? ✅"
            return {"respuesta": formatear_respuesta_web(txt), "estado": "entrega_confirmada"}
        else:
            # Si no especifica, preguntamos
            return {"respuesta": formatear_respuesta_web("¿Prefieres *recoger en tienda* o *envío a domicilio*? 🏪🚚"), "estado": "entrega_pendiente"}

    if intencion == "detalles_producto":
        # El LLM ya trae una respuesta explicativa
        return {"respuesta": formatear_respuesta_web(respuesta_llm), "estado": "detalles_producto"}

    if intencion == "recomendacion":
        return {"respuesta": formatear_respuesta_web(respuesta_llm), "estado": "recomendacion"}

    if intencion == "no_disponible":
        # Caso “bebidas” y similares
        return {"respuesta": formatear_respuesta_web(respuesta_llm), "estado": "no_disponible"}

    if intencion == "confirmar":
        # Confirmación final de compra (demo)
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
        ESTADOS.pop(uid, None)
        cierre = (
            f"🎉 ¡Pedido confirmado! Total: ${total:,}\n"
            f"En breve un asesor finalizará el proceso. Gracias por elegirnos 🙌\n\n"
            f"PS: Este es un *demo* de Tu Vendedor Inteligente. ¿Te gustaría tener uno así en tu empresa por WhatsApp, web o IG? 😉"
        )
        return {"respuesta": formatear_respuesta_web(cierre), "estado": "confirmado"}

    # Fallback amable del LLM (no_entendido u otros)
    return {"respuesta": formatear_respuesta_web(respuesta_llm or "No te entendí bien 😅 ¿Podrías decirlo de otra forma?"), "estado": intencion or "no_entendido"}


@app.post("/webhook/demo/reset")
async def reset(uid: str):
    ESTADOS.pop(uid, None)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Tu Vendedor Inteligente está activo 🤖"}

