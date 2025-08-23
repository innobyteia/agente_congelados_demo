from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import requests
import openai
import json
import unicodedata

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
openai.api_key = os.getenv("OPENAI_API_KEY")
PHONE_NUMBER_ID = "700653199793289"

# Productos disponibles
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


# Estado de conversación por número
ESTADOS = {}

def normalizar_texto(texto):
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode("utf-8")
    return texto

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
Eres un asistente que ayuda a los clientes a hacer pedidos en una tienda de congelados.
Productos: Empanadas, Pasteles de pollo, Pasteles de arequipe, Palitos de queso.
Mensaje: {texto_usuario}
Devuelve un JSON con una de estas estructuras:

Para ver el menú:
{{"intencion": "menu"}}

Para hacer pedido:
{{"intencion": "pedido", "items": [{{"producto": "empanadas", "cantidad": 5}}, ...]}}

Para hablar con alguien:
{{"intencion": "hablar"}}

Para confirmar:
{{"intencion": "confirmar"}}

Para modificar:
{{"intencion": "modificar", "items": [{{"producto": "empanadas", "cantidad": 10}}, ...]}}

Para seleccionar pago:
{{"intencion": "pago", "metodo": "efectivo"}}

Si no se entiende:
{{"intencion": "no_entendido"}}
"""
    respuesta = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    try:
        return json.loads(respuesta.choices[0].message.content)
    except:
        return {"intencion": "no_entendido"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return JSONResponse(content=int(params.get("hub.challenge")))
    return JSONResponse(content={"error": "Token inválido"}, status_code=403)

@app.post("/webhook")
async def recibir_mensaje(request: Request):
    data = await request.json()
    print("📨 Mensaje recibido:", data)
    try:
        cambio = data['entry'][0]['changes'][0]['value']
        if "messages" in cambio:
            mensaje = cambio['messages'][0]
            numero = mensaje['from']
            texto = mensaje['text']['body']

            estado = ESTADOS.get(numero, {"fase": "inicio"})
            resultado = interpretar_mensaje(texto)
            intencion = resultado.get("intencion")

            if estado["fase"] == "inicio":
                ESTADOS[numero] = {"fase": "esperando_intencion"}
                enviar_mensaje(numero, "Bienvenido a la tienda proveedor. ¿Quieres ver el menú, hacer un pedido o hablar con alguien?")

            elif intencion == "menu":
                productos = "\n".join([f"- {v['nombre']} - ${v['precio']}" for v in PRODUCTOS.values()])
                enviar_mensaje(numero, "proveedor Nuestro menú:\n" + productos)

            elif intencion == "pedido":
                ESTADOS[numero] = {"fase": "esperando_pago", "items": resultado["items"]}
                enviar_mensaje(numero, "¿Deseas pagar con transferencia o en efectivo?")

            elif intencion == "pago" and estado["fase"] == "esperando_pago":
                estado["metodo"] = resultado.get("metodo")
                resumen, total = "", 0
                for item in estado["items"]:
                    nombre = item["producto"].lower()
                    cantidad = item["cantidad"]
                    prod = PRODUCTOS.get(nombre)
                    if prod:
                        subtotal = cantidad * prod["precio"]
                        resumen += f"{cantidad} x {prod['nombre']} = ${subtotal}\n"
                        total += subtotal
                resumen += f"Método de pago: {estado['metodo']}\nTotal: ${total}"
                ESTADOS[numero]["fase"] = "esperando_confirmacion"
                enviar_mensaje(numero, "Este es el resumen de tu pedido:\n" + resumen + "\n¿Confirmas el pedido o deseas modificarlo?")

            elif intencion == "confirmar" and estado["fase"] == "esperando_confirmacion":
                enviar_mensaje(numero, "Tu pedido ha sido confirmado. Gracias por comprar con nosotros!")
                ESTADOS.pop(numero)

            elif intencion == "modificar":
                ESTADOS[numero] = {"fase": "esperando_pago", "items": resultado["items"]}
                enviar_mensaje(numero, "Entendido. ¿Deseas pagar con transferencia o en efectivo?")

            elif intencion == "hablar":
                enviar_mensaje(numero, "Un asesor se comunicará contigo pronto.")

            else:
                enviar_mensaje(numero, "Lo siento, no entendí eso. ¿Quieres ver el menú, hacer un pedido o hablar con alguien?")

        elif "statuses" in cambio:
            print("📬 Estado del mensaje:", cambio["statuses"][0]["status"])

    except Exception as e:
        print("⚠️ Error procesando el mensaje:", e)

    return {"status": "ok"}
