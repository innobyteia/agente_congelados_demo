from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import requests
import openai
import json
import unicodedata
import time

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://innobytedevelop.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
openai.api_key = os.getenv("OPENAI_API_KEY")
PHONE_NUMBER_ID = "700653199793289"

PRODUCTOS = {
    "empanadas": {"nombre": "Empanadas", "precio": 1500},
    "pasteles de pollo": {"nombre": "Pasteles de pollo", "precio": 2500},
    "pasteles de arequipe": {"nombre": "Pasteles de arequipe", "precio": 2700},
    "palitos de queso": {"nombre": "Palitos de queso", "precio": 1800},
    "arepas rellenas": {"nombre": "Arepas rellenas", "precio": 2200},
    "deditos de mozzarella": {"nombre": "Deditos de mozzarella", "precio": 2600},
    "pizza personal": {"nombre": "Pizza personal", "precio": 5900},
}

ESTADOS = {}

class MensajeWeb(BaseModel):
    texto: str
    usuario_id: str

def limpiar_estados_antiguos():
    ahora = time.time()
    usuarios_a_eliminar = [k for k, v in ESTADOS.items() if ahora - v.get("timestamp", 0) > 3600]
    for k in usuarios_a_eliminar:
        ESTADOS.pop(k, None)

def formatear_respuesta_web(mensaje):
    return mensaje.replace("\n", "<br>")

def interpretar_mensaje(texto_usuario, estado_actual=None):
    resumen_pedido = ""
    if estado_actual and "items" in estado_actual:
        resumen_pedido = "\n".join([
            f"- {item['cantidad']} x {PRODUCTOS[item['producto']]['nombre']}"
            for item in estado_actual["items"]
            if item["producto"] in PRODUCTOS
        ])
    else:
        resumen_pedido = "Sin pedido aún."

    historia_conversacion = estado_actual.get("historia", [])[-5:] if estado_actual else []
    contexto_historia = "\n".join(historia_conversacion) if historia_conversacion else "Sin historia previa."

    prompt = f"""
Eres un asistente inteligente y amigable llamado FrostyBot, para una tienda de productos congelados llamada 'Congelados Deliciosos'. Tu personalidad es entusiasta, útil y conversacional: usa emojis 😊, preguntas abiertas para mantener el flujo, y siempre intenta vender o recomendar productos de forma natural. Responde en español, de manera corta y atractiva (máximo 150 palabras por respuesta, a menos que sea un menú o resumen).

Objetivo: Interpretar el mensaje del cliente, detectar la intención principal y generar una respuesta conversacional. Usa el contexto del pedido y la historia para personalizar. Si la pregunta es off-topic, redirige suavemente al tema de la tienda.

### Información de la tienda:
- Productos disponibles: {json.dumps(PRODUCTOS, ensure_ascii=False)}
- Descripciones detalladas: Empanadas (rellenas de carne o pollo, crujientes); Pasteles de pollo (con verduras frescas); Pasteles de arequipe (dulces y cremosos); Palitos de queso (perfectos para snacks); Arepas rellenas (con queso y jamón); Deditos de mozzarella (fundidos y deliciosos); Pizza personal (variedades: pepperoni, hawaiana, vegetariana).
- Políticas: Envíos en 1-2 días en la ciudad, pago por transferencia o efectivo. Promociones: Compra 10 empanadas y lleva 2 gratis. Ingredientes: Sin conservantes artificiales, apto para alérgenos.
- Horarios: Abierto 24/7 online, entregas de 8am-8pm.

### Historia de la conversación:
{contexto_historia}

### Pedido actual:
{resumen_pedido}

### Mensaje del cliente:
"{texto_usuario}"

Devuelve SOLO un JSON con:
- "intencion": e.g., "menu", "pedido", "agregar", etc.
- "items": [] si aplica
- "productos": [] si aplica
- "metodo": ""
- "tema": ""
- "detalles": ""
- "respuesta": "Texto conversacional generado"
"""
    respuesta = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Eres un asistente preciso que siempre devuelve JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=500
    )
    try:
        json_res = json.loads(respuesta.choices[0].message.content)
        if estado_actual is not None:
            estado_actual.setdefault("historia", []).append(f"Cliente: {texto_usuario}")
            estado_actual["historia"].append(f"Bot: {json_res.get('respuesta', '')}")
        return json_res
    except Exception as e:
        print("⚠️ Error parseando JSON del LLM:", e)
        return {"intencion": "no_entendido", "respuesta": "Lo siento, no entendí. ¿Puedes repetirlo? 😅"}

@app.post("/webhook/demo")
async def webhook_demo(mensaje: MensajeWeb):
    limpiar_estados_antiguos()
    try:
        uid = mensaje.usuario_id
        texto = mensaje.texto.strip()
        if uid not in ESTADOS:
            ESTADOS[uid] = {"fase": "inicio", "timestamp": time.time()}

        estado = ESTADOS[uid]
        resultado = interpretar_mensaje(texto, estado_actual=estado)
        intencion = resultado.get("intencion")
        respuesta = resultado.get("respuesta", "Lo siento, no entendí. ¿Puedes repetirlo? 😅")

        if intencion == "pedido":
            estado["items"] = resultado.get("items", [])
            estado["fase"] = "esperando_pago"

        elif intencion == "agregar":
            nuevos = resultado.get("items", [])
            estado.setdefault("items", [])
            for n in nuevos:
                ex = next((i for i in estado["items"] if i["producto"] == n["producto"]), None)
                if ex:
                    ex["cantidad"] += n["cantidad"]
                else:
                    estado["items"].append(n)

        elif intencion == "modificar":
            mods = resultado.get("items", [])
            for mod in mods:
                for i in estado.get("items", []):
                    if i["producto"] == mod["producto"]:
                        i["cantidad"] = mod["cantidad"]

        elif intencion == "eliminar":
            eliminar = resultado.get("productos", [])
            estado["items"] = [i for i in estado.get("items", []) if i["producto"] not in eliminar]

        elif intencion == "pago":
            estado["metodo"] = resultado.get("metodo", "")
            estado["fase"] = "esperando_confirmacion"

        elif intencion == "confirmar":
            ESTADOS.pop(uid, None)

        return {"respuesta": formatear_respuesta_web(respuesta), "estado": intencion or "esperando"}

    except Exception as e:
        print(f"⚠️ Error en demo: {e}")
        return {"respuesta": formatear_respuesta_web("Lo siento, hubo un error. Intenta de nuevo."), "estado": "error"}

@app.post("/webhook/demo/reset")
async def reset_demo(usuario_id: str):
    ESTADOS.pop(usuario_id, None)
    return {"status": "reset", "message": "Conversación reiniciada"}
