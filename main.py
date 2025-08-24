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
    "alitas bbq": {"nombre": "Alitas BBQ", "precio": 4800},
    "croquetas de pollo": {"nombre": "Croquetas de pollo", "precio": 2000},
    "nuggets": {"nombre": "Nuggets", "precio": 2300},
    "tamal tolimense": {"nombre": "Tamal tolimense", "precio": 5500},
    "buñuelos": {"nombre": "Buñuelos", "precio": 1300},
    "pan de bono": {"nombre": "Pan de bono", "precio": 1500},
    "churros": {"nombre": "Churros", "precio": 1900},
    "lasagna de carne": {"nombre": "Lasaña de carne", "precio": 6700},
    "pizza personal": {"nombre": "Pizza personal", "precio": 5900},
}

ESTADOS = {}

def limpiar_estados_antiguos():
    ahora = time.time()
    usuarios_a_eliminar = []
    for usuario_id, estado in ESTADOS.items():
        if ahora - estado.get("timestamp", 0) > 3600:
            usuarios_a_eliminar.append(usuario_id)
    for usuario_id in usuarios_a_eliminar:
        ESTADOS.pop(usuario_id, None)

def normalizar_texto(texto):
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
    return texto

def formatear_respuesta_web(mensaje):
    mensaje = mensaje.replace('\n', '<br>')
    if "menú" in mensaje.lower():
        return "📋 " + mensaje
    elif "pedido" in mensaje.lower():
        return "🛒 " + mensaje
    elif "pago" in mensaje.lower():
        return "💳 " + mensaje
    elif "confirmar" in mensaje.lower():
        return "✅ " + mensaje
    else:
        return "💬 " + mensaje

def enviar_mensaje(numero, mensaje):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensaje}
    }
    response = requests.post(url, headers=headers, json=data)
    print("🔁 Enviado:", response.status_code, response.text)

def interpretar_mensaje(texto_usuario):
    prompt = f"""
Eres un asistente conversacional amable, empático y profesional para una tienda de congelados. Tu objetivo es ayudar al cliente a hacer pedidos, ver el menú, resolver dudas o redirigir de forma cordial temas que no tengan que ver con la tienda.

Productos disponibles: {', '.join(PRODUCTOS.keys())}

Mensaje del cliente: \"{texto_usuario}\"

Responde solo con un JSON que indique la intención:
- Ver menú:
  {{"intencion": "menu"}}
- Hacer pedido:
  {{"intencion": "pedido", "items": [{{"producto": "empanadas", "cantidad": 5}}]}}
- Confirmar pedido:
  {{"intencion": "confirmar"}}
- Modificar pedido:
  {{"intencion": "modificar", "items": [{{"producto": "empanadas", "cantidad": 2}}]}}
- Elegir método de pago:
  {{"intencion": "pago", "metodo": "efectivo"}}
- Pedir hablar con alguien:
  {{"intencion": "hablar"}}
- Tema fuera de contexto:
  {{"intencion": "fuera_de_contexto", "tema": "vacaciones"}}
- No se entiende:
  {{"intencion": "no_entendido"}}
"""
    respuesta = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    try:
        return json.loads(respuesta.choices[0].message.content)
    except:
        return {"intencion": "no_entendido"}

class MensajeWeb(BaseModel):
    texto: str
    usuario_id: str

@app.post("/webhook/demo")
async def webhook_demo(mensaje: MensajeWeb):
    limpiar_estados_antiguos()
    try:
        usuario_id = mensaje.usuario_id
        texto = mensaje.texto
        if usuario_id not in ESTADOS:
            ESTADOS[usuario_id] = {"fase": "inicio", "timestamp": time.time()}
            return {"respuesta": formatear_respuesta_web("¡Hola! 👋 Bienvenido a nuestra tienda de congelados. ¿Te gustaría ver el menú?"), "estado": "nuevo"}

        estado = ESTADOS[usuario_id]
        resultado = interpretar_mensaje(texto)
        intencion = resultado.get("intencion")

        if intencion == "menu":
            productos = "\n".join([f"- {v['nombre']} - ${v['precio']}" for v in PRODUCTOS.values()])
            return {"respuesta": formatear_respuesta_web(f"Nuestro menú:\n{productos}\n\n¿Qué te gustaría ordenar?"), "estado": "mostrando_menu"}

        elif intencion == "pedido":
            items = resultado.get("items", [])
            ESTADOS[usuario_id] = {"fase": "esperando_pago", "items": items, "timestamp": time.time()}
            resumen = "Tu pedido:\n"
            for item in items:
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    resumen += f"{item['cantidad']} x {prod['nombre']} - ${item['cantidad'] * prod['precio']}\n"
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Cómo deseas pagar? (transferencia/efectivo)"), "estado": "esperando_pago"}

        elif intencion == "confirmar":
            ESTADOS.pop(usuario_id, None)
            return {"respuesta": formatear_respuesta_web("🎉 ¡Tu pedido ha sido confirmado! Gracias por tu compra 🧡"), "estado": "confirmado"}

        elif intencion == "hablar":
            return {"respuesta": formatear_respuesta_web("Un asesor humano se comunicará contigo pronto. 🙌"), "estado": "esperando_asesor"}

        elif intencion == "fuera_de_contexto":
            tema = resultado.get("tema", "ese tema")
            return {"respuesta": formatear_respuesta_web(f"¡Qué interesante lo que mencionas sobre {tema}! 😄 Pero soy un asistente de congelados. ¿Te gustaría ver el menú?"), "estado": "fuera_de_contexto"}

        else:
            return {"respuesta": formatear_respuesta_web("No entendí. ¿Quieres ver el menú o hacer un pedido?"), "estado": "esperando"}

    except Exception as e:
        print(f"Error en demo: {e}")
        return {"respuesta": formatear_respuesta_web("Lo siento, hubo un error. Intenta de nuevo."), "estado": "error"}

@app.post("/webhook/demo/reset")
async def reset_demo(usuario_id: str):
    if usuario_id in ESTADOS:
        ESTADOS.pop(usuario_id)
    return {"status": "reset", "message": "Conversación reiniciada"}
