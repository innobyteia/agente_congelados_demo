# -*- coding: utf-8 -*-
from __future__ import print_function
import requests

ENDPOINT = "https://agente-congelados-demo.onrender.com/webhook/demo"
RESET_ENDPOINT = "https://agente-congelados-demo.onrender.com/webhook/demo/reset"
USER_ID = "usuario_prueba_001"

def enviar(texto):
    response = requests.post(ENDPOINT, json={"texto": texto, "usuario_id": USER_ID})
    print("Usuario: {}".format(texto))
    if response.status_code == 200:
        try:
            data = response.json()
            print("Bot   : {}".format(data.get("respuesta")))
        except Exception as e:
            print("Error parseando JSON: {}".format(e))
    else:
        print("Error al conectar con el bot. Código: {}".format(response.status_code))

def reset():
    requests.post(RESET_ENDPOINT, params={"uid": USER_ID})

if __name__ == "__main__":
    # === INICIO DEL TEST ===
    reset()

    # Fase 1: Saludo y menú
    enviar("hola")
    enviar("qué productos tienes?")
    enviar("y qué me recomiendas?")

    # Fase 2: Pedido
    enviar("quiero 2 empanadas y una pizza")
    enviar("ponle 3 deditos de mozzarella")
    enviar("cancela la pizza")
    enviar("cuánto va el total?")

    # Fase 3: Pago
    enviar("cómo pago?")
    enviar("transferencia")
    enviar("sí, confírmalo")

    # Fase 4: Preguntas adicionales
    enviar("venden bebidas?")
    enviar("es congelado o ya viene listo?")
    enviar("se puede recoger en tienda?")
    enviar("tengo alergia, qué ingredientes tienen las empanadas?")

    # Fase 5: Conversación humana
    enviar("estoy planeando una reunión familiar")
    enviar("gracias")
