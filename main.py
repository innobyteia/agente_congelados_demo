from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os, openai, json, time, logging, random, re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib

# ========== Setup ==========
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VendedorInteligente")

# ========== Datos ==========
PRODUCTOS = {
    "empanadas": {"nombre": "Empanadas", "precio": 1500, "descripcion": "Crujientes rellenas de carne o pollo", "categoria": "popular"},
    "pasteles de pollo": {"nombre": "Pasteles de pollo", "precio": 2500, "descripcion": "Suaves y con verduras frescas", "categoria": "popular"},
    "pizza personal": {"nombre": "Pizza personal", "precio": 5900, "descripcion": "Deliciosa pizza individual", "categoria": "especial"},
    "deditos de mozzarella": {"nombre": "Deditos de mozzarella", "precio": 2600, "descripcion": "Queso mozzarella empanizado", "categoria": "aperitivo"}
}

ALIAS_PRODUCTOS = {
    "empanada": "empanadas", "empanadas": "empanadas", "empana": "empanadas",
    "pastel": "pasteles de pollo", "pastel de pollo": "pasteles de pollo", "pasteles": "pasteles de pollo",
    "pizza": "pizza personal", "pizza personal": "pizza personal", "pizzas": "pizza personal",
    "deditos": "deditos de mozzarella", "deditos de mozzarella": "deditos de mozzarella", "mozzarella": "deditos de mozzarella",
}

NUM_PALABRAS = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "docena": 12, "una docena": 12, "media docena": 6
}

PROMOCIONES = [
    "🎉 ¡Compra 10 empanadas y lleva 2 GRATIS!",
    "🔥 Pizza personal + deditos por solo $9,900",
    "💫 3 pasteles de pollo por $6,900",
    "👨‍👩‍👧‍👦 Combo familiar: 2 pizzas + deditos $15,900",
]

DESPEDIDAS = [
    "¡Gracias por tu visita! Hasta pronto 😊",
    "¡Fue un placer ayudarte! ¡Vuelve pronto!",
    "¡Nos vemos! 🌈 Que tengas un día delicioso.",
    "¡Hasta luego! 🎯 Espero verte de nuevo pronto."
]

POLITICA_DATOS_LINK = "https://congelados-demo.com/politica-datos"

ESTADOS: Dict[str, Dict] = {}
LLM_CACHE: Dict[str, Dict] = {}  # Cache para respuestas del LLM

# ========== Utilidades Mejoradas ==========
def get_time_emoji() -> str:
    hour = datetime.now().hour
    if hour < 12: return "☀️"
    if hour < 18: return "🌤️"
    return "🌙"

def saludo_dinamico() -> str:
    """Saludo natural sin promociones forzadas"""
    emoji_tiempo = get_time_emoji()
    
    saludos_base = [
        f"¡Hola! {emoji_tiempo} Bienvenido a Congelados Deliciosos",
        f"¡Qué gusto verte por aquí! 👋 {emoji_tiempo}", 
        f"¡Hola! 🌟 Me da mucho gusto saludarte {emoji_tiempo}",
        f"¡Bienvenido! 🥟 {emoji_tiempo} ¿Cómo estás?"
    ]
    
    saludo = random.choice(saludos_base)
    
    # Ocasionalmente mencionar promoción suavemente (30% probabilidad)
    if random.random() < 0.3:
        promocion = random.choice(PROMOCIONES)
        return f"{saludo}. Por cierto, {promocion.lower()} ¿Te interesa?"
    
    return f"{saludo}. ¿En qué puedo ayudarte hoy?"

def generar_respuesta_promociones() -> str:
    """Respuesta dedicada para cuando preguntan por promociones"""
    promociones_texto = "\n".join([f"• {p}" for p in PROMOCIONES])
    return f"¡Claro! Tenemos estas promociones 🎉:\n\n{promociones_texto}\n\n¿Alguna te llama la atención? 😊"

def formatear_respuesta_web(mensaje: str) -> str:
    return mensaje.replace("\n", "<br>")

def normaliza_producto(token: str) -> Optional[str]:
    t = token.strip().lower()
    if t in ALIAS_PRODUCTOS:
        return ALIAS_PRODUCTOS[t]
    for alias, canon in ALIAS_PRODUCTOS.items():
        if alias in t:
            return canon
    if t in PRODUCTOS:
        return t
    return None

def _primer_match_producto(fragmento: str) -> Optional[str]:
    tokens = fragmento.split()
    for span in [3, 2, 1]:
        frag_corto = " ".join(tokens[:span])
        prod = normaliza_producto(frag_corto)
        if prod:
            return prod
    for tok in tokens:
        prod = normaliza_producto(tok)
        if prod:
            return prod
    return None

def extraer_productos_y_cantidades(texto: str) -> List[Dict]:
    texto = texto.lower()
    items: List[Dict] = []

    patrones = [
        r"(\d+)\s+([a-záéíóúñ ]+)(?=\s|$|\.|,)",
        r"\b(" + "|".join(re.escape(k) for k in NUM_PALABRAS.keys()) + r")\b\s+([a-záéíóúñ ]+)(?=\s|$|\.|,)",
        r"(?:quiero|dame|ponme|agrega|agregar|me gustaría|deseo)\s+(\d+)?\s*([a-záéíóúñ ]+)",
        r"(\d+)?\s*([a-záéíóúñ ]+)(?:\s+por\s+favor|\s+pf|\s+pls)?"
    ]

    candidatos: List[Dict] = []

    for patron in patrones:
        for match in re.finditer(patron, texto):
            cantidad = 1
            resto = ""

            if match.lastindex and match.lastindex >= 2:
                g1 = match.group(1)
                g2 = match.group(2)
                if g1 and g1.isdigit():
                    cantidad = int(g1)
                elif g1 and g1 in NUM_PALABRAS:
                    cantidad = NUM_PALABRAS[g1]
                resto = (g2 or "").strip()
            elif match.lastindex == 1:
                resto = (match.group(1) or "").strip()

            if resto:
                prod = _primer_match_producto(resto)
                if prod and prod in PRODUCTOS:
                    candidatos.append({"producto": prod, "cantidad": cantidad})

    # Detección de productos sueltos
    if not candidatos:
        for alias, canon in ALIAS_PRODUCTOS.items():
            if re.search(rf"\b{re.escape(alias)}\b", texto) and canon in PRODUCTOS:
                # Verificar que no sea parte de una frase más larga ya detectada
                if not any(alias in str(cand) for cand in candidatos):
                    candidatos.append({"producto": canon, "cantidad": 1})
                break

    # Merge de duplicados
    items_out: List[Dict] = []
    for it in candidatos:
        existente = next((i for i in items_out if i["producto"] == it["producto"]), None)
        if existente:
            existente["cantidad"] += it["cantidad"]
        else:
            items_out.append(it)

    return items_out

def extraer_json(texto: str) -> str:
    s = texto.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\{.*\}", s, re.DOTALL)
    return m.group(0) if m else s

def validar_items_llm(items: List[Dict]) -> List[Dict]:
    validos = []
    for item in items or []:
        if isinstance(item, dict) and "producto" in item and item["producto"] in PRODUCTOS:
            cantidad = max(1, int(item.get("cantidad", 1)))
            validos.append({"producto": item["producto"], "cantidad": cantidad})
        else:
            logger.warning(f"Item inválido del LLM: {item}")
    return validos

def generar_hash_texto(texto: str) -> str:
    """Genera hash para cache de LLM"""
    return hashlib.md5(texto.encode()).hexdigest()

# ========== Detección rápida mejorada ==========
def detectar_intencion_basica(texto: str) -> Optional[Dict]:
    t = texto.lower()

    # Saludos mejorados - SIN promoción en el saludo
    saludos_patrones = [
        r'^(hola|hey|hi|hello|buen[oa]s(\s*(d[ií]as|tardes|noches))?)\b',
        r'\b(qu[eé]\s*tal|c[oó]mo\s*est[aá]s|saludos|buen[oa]s)\b',
        r'^(ola|hey|hi|hello|buenas)'
    ]
    
    for patron in saludos_patrones:
        if re.search(patron, t):
            return {"intencion": "saludo", "respuesta": saludo_dinamico()}  # ← SOLO saludo, sin promoción

    # Nueva detección para promociones específicas
    if re.search(r'\b(promociones?|ofertas?|descuentos?|especiales)\b', t):
        return {"intencion": "promociones", "respuesta": generar_respuesta_promociones()}

    # Menú / catálogo
    if re.search(r'\b(men[úu]|menu|productos|cat[aá]logo|qu[eé]\s*(tienes|vendes)|oferta|ofertas)\b', t):
        productos = "\n".join([f"• {p['nombre']} - ${p['precio']:,}" for p in PRODUCTOS.values()])
        return {"intencion": "menu", "respuesta": f"Aquí va nuestro menú 🧊:\n\n{productos}\n\n¿Te antoja algo? 😋"}

    # Bebidas / no disponible
    if re.search(r'\b(bebidas?|gaseosa|jugo|agua|refresco|cerveza|licor|vino)\b', t):
        sugeridos = "empanadas, pasteles de pollo o deditos de mozzarella"
        return {"intencion": "no_disponible", "respuesta": f"Por ahora no manejamos bebidas 😅. Pero te puedo recomendar {sugeridos} — ¡son un hit! ¿Te gustaría agregar alguno? 😋"}

    # Entrega
    if re.search(r'\b(domicilio|env[ií]o|delivery|a mi casa|a domicilio|entregar|mandar)\b', t):
        return {"intencion": "entrega", "modo": "domicilio",
                "respuesta": f"🚚 Perfecto, envío a domicilio. Protegemos tus datos según nuestras políticas: {POLITICA_DATOS_LINK}. ¿Deseas confirmar el pedido? ✅"}
    
    if re.search(r'\b(recoger|tienda|punto de recogida|pick\s*up|pasar por|buscar|recojer)\b', t):
        return {"intencion": "entrega", "modo": "tienda",
                "respuesta": "🏪 Genial, recoger en tienda. ¿Confirmamos tu pedido ahora? ✅"}

    # Total
    if re.search(r'\b(total|cu[aá]nto\s+(va|debo|es|cuesta)|suma|valor)\b', t):
        return {"intencion": "total"}

    # Confirmar
    if re.search(r'\b(confirmar|confirmo|listo|ok|vale|s[ií]|acepto|de acuerdo)\b', t):
        return {"intencion": "confirmar"}

    # Despedida
    if re.search(r'\b(gracias|chao|adi[óo]s|hasta luego|bye|nos vemos|finalizar|terminar)\b', t):
        return {"intencion": "despedida", "respuesta": random.choice(DESPEDIDAS)}

    return None

# ========== LLM conversacional con cache ==========
def interpretar_mensaje_con_LLM(texto_usuario: str, estado_actual=None) -> Dict:
    try:
        # Generar hash para cache
        texto_hash = generar_hash_texto(texto_usuario)
        if texto_hash in LLM_CACHE:
            logger.info(f"Usando respuesta cacheada para: {texto_usuario}")
            return LLM_CACHE[texto_hash]

        resumen = "\n".join([
            f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']}"
            for i in (estado_actual.get("items", []) if estado_actual else [])
        ]) or "Ninguno."

        catalogo = "\n".join([
            f"{p['nombre']} - ${p['precio']} ({p['descripcion']})"
            for p in PRODUCTOS.values()
        ])

        prompt = f"""
Eres "Tu Vendedor Inteligente" para "Congelados Deliciosos". Responde cálido y profesional.

CATÁLOGO (SOLO estos productos):
{catalogo}

PEDIDO ACTUAL:
{resumen}

MENSAJE DEL CLIENTE:
"{texto_usuario}"

REGLAS:
- SOLO usar productos del catálogo
- Si preguntan por algo no disponible, sugiere 1-3 alternativas del catálogo
- Respuestas breves (máx 100 palabras), con emojis
- Termina con una pregunta amable (CTA)

Devuelve SOLO JSON:
{{
  "intencion": "menu|pedido|saludo|despedida|pago|entrega|detalles_producto|recomendacion|no_disponible|no_entendido|confirmar",
  "items": [{{"producto":"nombre_exacto","cantidad":X}}],
  "metodo": "transferencia|efectivo|",
  "modo": "domicilio|tienda|",
  "respuesta": "Texto conversacional con emojis"
}}
"""
        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Responde solo con JSON válido. Usa solo productos del catálogo proporcionado."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=400
        )
        
        raw = resp.choices[0].message.content
        resultado = json.loads(extraer_json(raw))

        # Validar y sanitizar items
        if "items" in resultado:
            resultado["items"] = validar_items_llm(resultado["items"])

        # Cachear respuesta
        LLM_CACHE[texto_hash] = resultado
        return resultado

    except Exception as e:
        logger.error(f"Error en LLM: {e}")
        return {"intencion": "no_entendido", "respuesta": "Lo siento 😅 no logré entender bien. ¿Podrías decirlo de otra forma?"}

# ========== Esquemas ==========
class MensajeWeb(BaseModel):
    texto: str
    usuario_id: str

# ========== Endpoints con manejo de errores ==========
@app.post("/webhook/demo")
async def webhook_demo(mensaje: MensajeWeb):
    try:
        uid = mensaje.usuario_id
        texto = mensaje.texto.strip()

        if not texto:
            return {"respuesta": formatear_respuesta_web("¡Hola! 👋 ¿En qué puedo ayudarte hoy?"), "estado": "saludo"}

        if uid not in ESTADOS:
            ESTADOS[uid] = {
                "items": [], 
                "historia": [], 
                "timestamp": time.time(), 
                "metodo": None, 
                "entrega": None
            }
        
        estado = ESTADOS[uid]
        estado["timestamp"] = time.time()

        # 1) Detección rápida
        deteccion = detectar_intencion_basica(texto)
        if deteccion:
            return _manejar_deteccion_rapida(deteccion, estado, uid)

        # 2) Extracción de productos
        items_detectados = extraer_productos_y_cantidades(texto)
        if items_detectados:
            return _manejar_items_detectados(items_detectados, estado)

        # 3) LLM para casos complejos
        resultado = interpretar_mensaje_con_LLM(texto, estado_actual=estado)
        return _manejar_respuesta_llm(resultado, estado, uid, texto)

    except Exception as e:
        logger.error(f"Error en webhook_demo: {e}")
        return {
            "respuesta": formatear_respuesta_web("¡Ups! 😅 Tuve un problema. ¿Podrías intentarlo de nuevo?"),
            "estado": "error"
        }

def _manejar_deteccion_rapida(deteccion: Dict, estado: Dict, uid: str) -> Dict:
    intencion = deteccion["intencion"]
    
    if intencion == "saludo":
        return {"respuesta": formatear_respuesta_web(deteccion["respuesta"]), "estado": "saludo"}
    
    elif intencion == "menu":
        return {"respuesta": formatear_respuesta_web(deteccion["respuesta"]), "estado": "menu"}
    
    elif intencion == "no_disponible":
        return {"respuesta": formatear_respuesta_web(deteccion["respuesta"]), "estado": "no_disponible"}
    
    elif intencion == "entrega":
        estado["entrega"] = deteccion.get("modo")
        return {"respuesta": formatear_respuesta_web(deteccion["respuesta"]), "estado": "entrega_confirmada"}
    
    elif intencion == "total":
        if not estado.get("items"):
            return {"respuesta": formatear_respuesta_web("Aún no tienes productos en tu pedido. ¿Te muestro el menú? 😊"), "estado": "total"}
        
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
        desglose = "\n".join(
            f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}"
            for i in estado["items"]
        )
        return {
            "respuesta": formatear_respuesta_web(f"🧮 Tu pedido va así:\n{desglose}\n\nTotal: ${total:,}\n¿Confirmamos o agregas algo más?"),
            "estado": "total"
        }
    
    elif intencion == "confirmar":
        return _confirmar_pedido(estado, uid)
    
    elif intencion == "despedida":
        return {"respuesta": formatear_respuesta_web(deteccion["respuesta"]), "estado": "despedida"}
    
    return {"respuesta": formatear_respuesta_web("No entendí 😅 ¿Podrías reformular?"), "estado": "no_entendido"}

def _manejar_items_detectados(items_detectados: List[Dict], estado: Dict) -> Dict:
    for nuevo in items_detectados:
        existente = next((i for i in estado["items"] if i["producto"] == nuevo["producto"]), None)
        if existente:
            existente["cantidad"] += nuevo["cantidad"]
        else:
            estado["items"].append(nuevo)

    total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
    desglose = "\n".join([
        f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}"
        for i in estado["items"]
    ])
    
    respuestas = [
        f"🛒 ¡Perfecto! He actualizado tu pedido:\n{desglose}\n\nTotal: ${total:,}\n¿Quieres agregar algo más o pasamos al pago? 💳",
        f"✅ ¡Agregado! Tu pedido:\n{desglose}\n\n💰 Total: ${total:,}\n¿Deseas algo adicional?",
        f"🎯 ¡Excelente elección! Ahora tienes:\n{desglose}\n\n💵 Total: ${total:,}\n¿Necesitas algo más?"
    ]
    
    return {"respuesta": formatear_respuesta_web(random.choice(respuestas)), "estado": "pedido"}

def _manejar_respuesta_llm(resultado: Dict, estado: Dict, uid: str, texto: str) -> Dict:
    intencion = resultado.get("intencion", "no_entendido")
    respuesta_llm = resultado.get("respuesta", "")
    
    # Guardar historia
    estado.setdefault("historia", []).append(f"Cliente: {texto}")
    estado["historia"].append(f"Bot: {respuesta_llm}")
    
    if intencion == "pedido":
        nuevos = validar_items_llm(resultado.get("items", []))
        for n in nuevos:
            existente = next((i for i in estado["items"] if i["producto"] == n["producto"]), None)
            if existente:
                existente["cantidad"] += n.get("cantidad", 1)
            else:
                estado["items"].append({"producto": n["producto"], "cantidad": n.get("cantidad", 1)})
        
        total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
        desglose = "\n".join([
            f"- {i['cantidad']} x {PRODUCTOS[i['producto']]['nombre']} = ${i['cantidad'] * PRODUCTOS[i['producto']]['precio']:,}"
            for i in estado["items"]
        ]) or "— vacío —"
        
        return {
            "respuesta": formatear_respuesta_web(respuesta_llm or f"🛒 Pedido actualizado:\n{desglose}\n\nTotal: ${total:,}\n¿Deseas algo más?"),
            "estado": "pedido"
        }
    
    elif intencion == "pago":
        metodo = resultado.get("metodo")
        if metodo:
            estado["metodo"] = metodo
            return {"respuesta": formatear_respuesta_web(f"💳 Perfecto, registré *{metodo}*. ¿Confirmamos el pedido? ✅"), "estado": "pago"}
        return {"respuesta": formatear_respuesta_web(respuesta_llm or "💳 Aceptamos transferencia o efectivo. ¿Cuál prefieres?"), "estado": "pago"}
    
    elif intencion == "entrega":
        modo = resultado.get("modo")
        if modo == "domicilio":
            estado["entrega"] = "domicilio"
            txt = f"📦 ¡Listo! Enviaremos tu pedido a domicilio. Tus datos serán tratados según nuestras políticas: {POLITICA_DATOS_LINK}. ¿Deseas confirmar ahora? ✅"
            return {"respuesta": formatear_respuesta_web(txt), "estado": "entrega_confirmada"}
        elif modo == "tienda":
            estado["entrega"] = "tienda"
            return {"respuesta": formatear_respuesta_web("🏪 Perfecto, lo prepararemos para *recoger en tienda*. ¿Quieres confirmar tu pedido ahora? ✅"), "estado": "entrega_confirmada"}
        else:
            return {"respuesta": formatear_respuesta_web("¿Prefieres *recoger en tienda* o *envío a domicilio*? 🏪🚚"), "estado": "entrega_pendiente"}
    
    elif intencion == "confirmar":
        return _confirmar_pedido(estado, uid)
    
    else:
        return {"respuesta": formatear_respuesta_web(respuesta_llm or "No te entendí bien 😅 ¿Podrías decirlo de otra forma?"), "estado": intencion}

def _confirmar_pedido(estado: Dict, uid: str) -> Dict:
    if not estado.get("items"):
        return {"respuesta": formatear_respuesta_web("Aún no tienes productos en tu pedido. ¿Te muestro el menú? 😊"), "estado": "menu"}
    
    total = sum(i["cantidad"] * PRODUCTOS[i["producto"]]["precio"] for i in estado["items"])
    ESTADOS.pop(uid, None)
    
    cierre = (
        f"🎉 ¡Pedido confirmado! Total: ${total:,}<br>"
        "En breve un asesor finalizará el proceso y coordinará la entrega. ¡Gracias por elegirnos! 🙌<br><br>"
        "PS: Este es un *demo* de Tu Vendedor Inteligente (web/WhatsApp/IG). "
        "¿Te gustaría tener uno así en tu empresa? 😉"
    )
    
    return {"respuesta": formatear_respuesta_web(cierre), "estado": "confirmado"}

@app.post("/webhook/demo/reset")
async def reset(usuario_id: str):
    ESTADOS.pop(usuario_id, None)
    return {"status": "ok", "message": "Conversación reiniciada"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/stats")
async def stats():
    return {
        "usuarios_activos": len(ESTADOS),
        "cache_llm": len(LLM_CACHE),
        "productos": len(PRODUCTOS)
    }

@app.get("/")
async def root():
    return {
        "message": "Tu Vendedor Inteligente está activo 🤖", 
        "version": "3.0",
        "estado": "optimizado"
    }



