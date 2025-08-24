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

    prompt = f"""
Actúas como un asistente de una tienda de productos congelados. Tu tarea es interpretar el mensaje del cliente y devolver un JSON con la intención detectada. Usa el contexto del pedido si existe.

### Pedido actual:
{resumen_pedido}

### Mensaje del cliente:
"{texto_usuario}"

Devuelve SOLO un JSON. Las posibles intenciones son:

- Ver menú:
  {{ "intencion": "menu" }}
- Hacer nuevo pedido:
  {{ "intencion": "pedido", "items": [{{"producto": "empanadas", "cantidad": 2}}] }}
- Agregar productos:
  {{ "intencion": "agregar", "items": [{{"producto": "churros", "cantidad": 1}}] }}
- Modificar cantidades:
  {{ "intencion": "modificar", "items": [{{"producto": "empanadas", "cantidad": 3}}] }}
- Eliminar productos:
  {{ "intencion": "eliminar", "productos": ["nuggets"] }}
- Confirmar pedido:
  {{ "intencion": "confirmar" }}
- Elegir método de pago:
  {{ "intencion": "pago", "metodo": "efectivo" }}
- Hablar con humano:
  {{ "intencion": "hablar" }}
- Pregunta fuera de contexto:
  {{ "intencion": "fuera_de_contexto", "tema": "vacaciones" }}
- No se entiende:
  {{ "intencion": "no_entendido" }}
"""
    respuesta = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    try:
        return json.loads(respuesta.choices[0].message.content)
    except Exception as e:
        print("⚠️ Error parseando JSON del LLM:", e)
        return {"intencion": "no_entendido"}


class MensajeWeb(BaseModel):
    texto: str
    usuario_id: str

@app.post("/webhook/demo")
async def webhook_demo(mensaje: MensajeWeb):
    limpiar_estados_antiguos()
    try:
        usuario_id = mensaje.usuario_id
        texto = mensaje.texto.strip().lower()
        if usuario_id not in ESTADOS:
            ESTADOS[usuario_id] = {"fase": "inicio", "timestamp": time.time()}

        # Saludo inicial manual
        if texto in ["hola", "buenas", "buenos días", "buenas tardes", "buenas noches"]:
            return {"respuesta": formatear_respuesta_web("¡Hola! 👋 ¿Te gustaría ver el menú o hacer un pedido?"), "estado": "saludo"}

        estado = ESTADOS[usuario_id]
        resultado = interpretar_mensaje(texto, estado_actual=estado)
        intencion = resultado.get("intencion")

        if intencion == "menu":
            productos = "\n".join([f"- {v['nombre']} - ${v['precio']}" for v in PRODUCTOS.values()])
            return {"respuesta": formatear_respuesta_web(f"Nuestro menú:\n{productos}\n\n¿Qué te gustaría ordenar?"), "estado": "mostrando_menu"}

        elif intencion == "pedido":
            items = resultado.get("items", [])
            estado["fase"] = "esperando_pago"
            estado["items"] = items
            estado["timestamp"] = time.time()
            resumen = "Tu pedido:\n"
            for item in items:
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    resumen += f"{item['cantidad']} x {prod['nombre']} - ${item['cantidad'] * prod['precio']}\n"
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Cómo deseas pagar? (transferencia/efectivo)?"), "estado": "esperando_pago"}

        elif intencion == "agregar":
            nuevos_items = resultado.get("items", [])
            if "items" not in estado:
                estado["items"] = []
            for nuevo in nuevos_items:
                ya_existe = next((i for i in estado["items"] if i["producto"] == nuevo["producto"]), None)
                if ya_existe:
                    ya_existe["cantidad"] += nuevo["cantidad"]
                else:
                    estado["items"].append(nuevo)
            resumen = "Pedido actualizado:\n"
            for item in estado["items"]:
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    resumen += f"{item['cantidad']} x {prod['nombre']} - ${item['cantidad'] * prod['precio']}\n"
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Deseas pagar ahora o agregar más productos?"), "estado": "esperando_pago"}

        elif intencion == "modificar":
            modificaciones = resultado.get("items", [])
            for mod in modificaciones:
                for item in estado.get("items", []):
                    if item["producto"] == mod["producto"]:
                        item["cantidad"] = mod["cantidad"]
            resumen = "Pedido modificado:\n"
            for item in estado["items"]:
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    resumen += f"{item['cantidad']} x {prod['nombre']} - ${item['cantidad'] * prod['precio']}\n"
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Confirmas el pedido o deseas hacer más cambios?"), "estado": "esperando_pago"}

        elif intencion == "eliminar":
            productos_a_eliminar = resultado.get("productos", [])
            estado["items"] = [item for item in estado.get("items", []) if item["producto"] not in productos_a_eliminar]
            resumen = "Pedido actualizado:\n"
            for item in estado["items"]:
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    resumen += f"{item['cantidad']} x {prod['nombre']} - ${item['cantidad'] * prod['precio']}\n"
            if not estado["items"]:
                resumen += "Sin productos en el pedido."
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Deseas agregar algo más?"), "estado": "esperando_pago"}

        elif intencion == "pago":
            metodo = resultado.get("metodo", "sin especificar")
            estado["metodo"] = metodo
            resumen = "Resumen de tu pedido:\n"
            total = 0
            for item in estado.get("items", []):
                prod = PRODUCTOS.get(item["producto"])
                if prod:
                    subtotal = item["cantidad"] * prod["precio"]
                    total += subtotal
                    resumen += f"{item['cantidad']} x {prod['nombre']} = ${subtotal}\n"
            resumen += f"Método de pago: {metodo}\nTotal: ${total}"
            return {"respuesta": formatear_respuesta_web(f"{resumen}\n¿Confirmas el pedido?"), "estado": "esperando_confirmacion"}

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
        print(f"⚠️ Error en demo: {e}")
        return {"respuesta": formatear_respuesta_web("Lo siento, hubo un error. Intenta de nuevo."), "estado": "error"}



@app.post("/webhook/demo/reset")
async def reset_demo(usuario_id: str):
    if usuario_id in ESTADOS:
        ESTADOS.pop(usuario_id)
    return {"status": "reset", "message": "Conversación reiniciada"}
