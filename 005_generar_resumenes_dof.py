import os
import csv
import re
import time
import tiktoken
from groq import Groq
from dotenv import load_dotenv
from typing import Optional, List, Dict
import shutil # Para renombrar carpetas

# --- Configuración ---
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# NUEVO MODELO Y LÍMITES
MODELO_GROQ = "meta-llama/Llama-4-Scout-17B-16E-Instruct" # Asegúrate que este sea el nombre exacto del modelo en Groq
ENCODING_TIKTOKEN = "cl100k_base" # Generalmente bueno para modelos Llama recientes

# Límites de la API para Llama-4-Scout-17B
LIMITE_SOLICITUDES_POR_MINUTO = 30
LIMITE_TOKENS_POR_MINUTO_PROCESADOS = 30000 # Nuevo límite más alto
# LIMITE_TOKENS_POR_DIA ya no es una preocupación según lo indicado ("No limit")

# Configuración del script
# Asumamos que el contexto efectivo que queremos usar es menor que el TPM para una sola solicitud.
# Si Llama-4-Scout-17B-16E-Instruct tiene un contexto de 16K, podemos ser más generosos.
# Vamos a apuntar a no exceder ~25K tokens en una sola solicitud para estar seguros con el TPM de 30K.
MAX_TOKENS_PARA_ENVIAR_MODELO = 25000 # Ajusta esto basado en el contexto real del modelo y pruebas
MAX_COMPLETION_TOKENS_RESUMEN = 768 # Llama 4 puede ser bueno con resúmenes un poco más largos si es necesario
TEMPERATURE_RESUMEN = 0.4 # Ligeramente más bajo para mayor factualidad
MAX_API_REINTENTOS = 3
TIEMPO_ESPERA_REINTENTO_SEGUNDOS = 10
PAUSA_MINIMA_ENTRE_SOLICITUDES_SEGUNDOS = 2.0 # (30 solicitudes/min -> 2 segs/solicitud)

# Variables globales para el seguimiento de límites
solicitudes_en_minuto_actual = 0
tokens_procesados_en_minuto_actual = 0
inicio_minuto_actual = time.time()

def sanitizar_nombre(nombre: str, es_carpeta=False) -> str:
    nombre = nombre.lower()
    nombre = re.sub(r'\s+', '_', nombre)
    if es_carpeta:
        nombre = re.sub(r'[^\w-]', '', nombre)
    else:
        nombre = re.sub(r'[^\w.-]', '', nombre)
    nombre = nombre[:150]
    if not nombre:
        if es_carpeta: return "documentos_sin_nombre_busqueda"
        return "documento_sin_titulo"
    return nombre

def renombrar_carpeta_si_existe(ruta_carpeta: str):
    """Si la carpeta existe, la renombra añadiendo un sufijo _OLD_XXX."""
    if os.path.exists(ruta_carpeta):
        i = 1
        while True:
            nueva_ruta_old = f"{ruta_carpeta}_OLD_{i:03d}"
            if not os.path.exists(nueva_ruta_old):
                print(f"La carpeta '{ruta_carpeta}' ya existe. Renombrando a '{nueva_ruta_old}'.")
                try:
                    shutil.move(ruta_carpeta, nueva_ruta_old)
                    print(f"Carpeta renombrada exitosamente.")
                except Exception as e:
                    print(f"Error al renombrar la carpeta '{ruta_carpeta}': {e}. Puede que necesites hacerlo manualmente.")
                    # Podrías optar por detener el script aquí o continuar con la creación de la nueva
                    # si el renombrado falla, pero es más seguro verificar.
                    raise # Re-lanza la excepción si el renombrado es crítico
                break
            i += 1

def obtener_conteo_tokens_tiktoken(texto: str, encoding_nombre: str = ENCODING_TIKTOKEN) -> int:
    try:
        encoding = tiktoken.get_encoding(encoding_nombre)
        return len(encoding.encode(texto))
    except Exception: # Ser más genérico en la captura aquí
        return len(texto.split()) # Fallback a conteo de palabras simple

def truncar_texto_por_tokens(texto: str, encoding_nombre: str, max_tokens: int) -> str:
    try:
        encoding = tiktoken.get_encoding(encoding_nombre)
        tokens = encoding.encode(texto)
        if len(tokens) > max_tokens:
            tokens_truncados = tokens[:max_tokens]
            texto_truncado = encoding.decode(tokens_truncados)
            print(f"    Texto truncado de {len(tokens)} a {len(tokens_truncados)} tokens (aprox. {obtener_conteo_tokens_tiktoken(texto_truncado, encoding_nombre)}).")
            return texto_truncado
        return texto
    except Exception as e:
        print(f"    Advertencia: Error al truncar texto con tiktoken: {e}. Usando truncado por caracteres.")
        max_chars = max_tokens * 3 
        if len(texto) > max_chars:
            print(f"    Fallback: Texto truncado por longitud de caracteres de {len(texto)} a {max_chars} chars.")
            return texto[:max_chars]
        return texto

def verificar_y_esperar_limites_api(tokens_entrada_prompt: int):
    global solicitudes_en_minuto_actual, tokens_procesados_en_minuto_actual, inicio_minuto_actual
    tiempo_actual = time.time()

    if tiempo_actual - inicio_minuto_actual >= 60:
        print(f"    -- Nuevo minuto para límites API. Reseteando contadores (Sols prev: {solicitudes_en_minuto_actual}, Tokens prev: {tokens_procesados_en_minuto_actual}) --")
        solicitudes_en_minuto_actual = 0
        tokens_procesados_en_minuto_actual = 0
        inicio_minuto_actual = tiempo_actual

    # Chequeo 1: ¿La solicitud actual por sí sola excede una porción segura del límite TPM?
    # Con 30K TPM, una sola solicitud de hasta ~25-28K debería estar bien si no hay otras recientes.
    umbral_tpm_solicitud_unica = LIMITE_TOKENS_POR_MINUTO_PROCESADOS * 0.90 # 90%
    if tokens_entrada_prompt > umbral_tpm_solicitud_unica:
        print(f"    ADVERTENCIA: La solicitud actual ({tokens_entrada_prompt} tokens) es grande vs el límite TPM ({LIMITE_TOKENS_POR_MINUTO_PROCESADOS}).")
        # Considerar esperar al siguiente minuto si esta solicitud es muy grande Y ya hemos usado algo de la cuota del minuto
        if tokens_procesados_en_minuto_actual > 0: # Si ya hemos hecho algo este minuto
             tiempo_para_siguiente_minuto = 60.1 - (tiempo_actual - inicio_minuto_actual)
             if tiempo_para_siguiente_minuto > 0:
                print(f"    La solicitud es grande y ya se usaron tokens este min. Esperando {tiempo_para_siguiente_minuto:.2f}s...")
                time.sleep(tiempo_para_siguiente_minuto)
                solicitudes_en_minuto_actual = 0
                tokens_procesados_en_minuto_actual = 0
                inicio_minuto_actual = time.time()

    # Chequeo 2: Límite de solicitudes acumuladas
    if solicitudes_en_minuto_actual >= LIMITE_SOLICITUDES_POR_MINUTO:
        tiempo_para_siguiente_minuto = 60.1 - (tiempo_actual - inicio_minuto_actual)
        if tiempo_para_siguiente_minuto > 0:
            print(f"    Límite de {LIMITE_SOLICITUDES_POR_MINUTO} Sols/min alcanzado. Esperando {tiempo_para_siguiente_minuto:.2f}s...")
            time.sleep(tiempo_para_siguiente_minuto)
        solicitudes_en_minuto_actual = 0
        tokens_procesados_en_minuto_actual = 0
        inicio_minuto_actual = time.time()

    # Chequeo 3: Límite de tokens acumulados
    # Proyectamos el uso si esta solicitud se procesa (entrada + un estimado para la salida)
    if tokens_procesados_en_minuto_actual + tokens_entrada_prompt + MAX_COMPLETION_TOKENS_RESUMEN > LIMITE_TOKENS_POR_MINUTO_PROCESADOS:
        tiempo_para_siguiente_minuto = 60.1 - (tiempo_actual - inicio_minuto_actual)
        if tiempo_para_siguiente_minuto > 0:
            print(f"    Límite de Tokens/min (proyectado {tokens_procesados_en_minuto_actual + tokens_entrada_prompt + MAX_COMPLETION_TOKENS_RESUMEN} / {LIMITE_TOKENS_POR_MINUTO_PROCESADOS}) cercano. Esperando {tiempo_para_siguiente_minuto:.2f}s...")
            time.sleep(tiempo_para_siguiente_minuto)
        solicitudes_en_minuto_actual = 0
        tokens_procesados_en_minuto_actual = 0
        inicio_minuto_actual = time.time()

def generar_resumen_con_groq(cliente_groq: Groq, texto_documento: str) -> Optional[str]:
    global solicitudes_en_minuto_actual, tokens_procesados_en_minuto_actual

    prompt_resumen = (
        "Eres un asistente experto en la extracción de información clave de documentos oficiales mexicanos. "
        "Tu tarea es generar un resumen muy conciso, en un solo párrafo, que capture la esencia y los puntos más importantes del siguiente documento. "
        "Evita frases introductorias como 'El documento habla de...' o 'Este texto es sobre...'. Ve directamente a los hechos y el propósito principal."
        f"\n\n--- INICIO DEL DOCUMENTO ---\n{texto_documento}\n--- FIN DEL DOCUMENTO ---\n\n"
        "RESUMEN CONCISO EN UN PÁRRAFO:"
    )
    tokens_prompt_estimados = obtener_conteo_tokens_tiktoken(prompt_resumen)

    verificar_y_esperar_limites_api(tokens_prompt_estimados)

    for intento in range(MAX_API_REINTENTOS):
        try:
            print(f"    Enviando a Groq (modelo: {MODELO_GROQ}, intento {intento + 1}/{MAX_API_REINTENTOS}, tokens_prompt: {tokens_prompt_estimados})...")
            start_time_api = time.time()
            stream = cliente_groq.chat.completions.create(
                model=MODELO_GROQ,
                messages=[{"role": "user", "content": prompt_resumen}],
                temperature=TEMPERATURE_RESUMEN,
                max_tokens=MAX_COMPLETION_TOKENS_RESUMEN,
                top_p=1,
                stream=True,
                stop=None,
            )
            
            resumen_completo = ""
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                resumen_completo += content
            
            api_call_duration = time.time() - start_time_api
            resumen_limpio = resumen_completo.strip()
            tokens_resumen_salida = obtener_conteo_tokens_tiktoken(resumen_limpio)

            solicitudes_en_minuto_actual += 1
            tokens_procesados_en_minuto_actual += tokens_prompt_estimados + tokens_resumen_salida
            print(f"    Resumen recibido ({tokens_resumen_salida} tokens) en {api_call_duration:.2f}s. Sols este min: {solicitudes_en_minuto_actual}. Tokens este min: {tokens_procesados_en_minuto_actual}.")
            
            if resumen_limpio:
                return resumen_limpio
            else:
                print("    Groq devolvió un resumen vacío.")
                return None

        except Exception as e:
            error_str = str(e).lower()
            print(f"    Error en la API de Groq (intento {intento + 1}): {e}")
            # Ya no necesitamos preocuparnos por TPD, pero otros rate limits o errores 413/429 pueden ocurrir.
            if "rate limit" in error_str or "ratelimit" in error_str or "429" in error_str or "413" in error_str:
                print("    Error de Rate Limit o tamaño de solicitud detectado por la API.")
                espera_adicional = 60 if "429" in error_str else TIEMPO_ESPERA_REINTENTO_SEGUNDOS * (intento + 1) # Espera más si es 429
                print(f"    Esperando {espera_adicional} segundos antes de reintentar...")
                time.sleep(espera_adicional)
                # Reiniciar contadores después de esperar por rate limit puede ser una buena idea
                if "429" in error_str: # Si es un rate limit más serio, resetear el minuto
                    solicitudes_en_minuto_actual = 0
                    tokens_procesados_en_minuto_actual = 0
                    inicio_minuto_actual = time.time()
            elif intento < MAX_API_REINTENTOS - 1:
                print(f"    Reintentando en {TIEMPO_ESPERA_REINTENTO_SEGUNDOS} segundos...")
                time.sleep(TIEMPO_ESPERA_REINTENTO_SEGUNDOS)
            else:
                print("    Se alcanzó el máximo de reintentos para la API de Groq.")
                return None
    return None


def procesar_documentos_para_resumen(carpeta_textos_entrada: str, termino_busqueda_original: str):
    if not GROQ_API_KEY:
        print("Error: GROQ_API_KEY no configurada.")
        return

    cliente_groq = Groq()

    nombre_carpeta_resumenes_base = sanitizar_nombre(termino_busqueda_original, es_carpeta=True) + "_colectados_resumen"
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    ruta_carpeta_resumenes = os.path.join(script_dir, nombre_carpeta_resumenes_base)
    ruta_carpeta_textos = os.path.join(script_dir, carpeta_textos_entrada)

    if not os.path.isdir(ruta_carpeta_textos):
        print(f"Error: Carpeta de entrada '{ruta_carpeta_textos}' no existe.")
        return

    # Renombrar carpeta de resúmenes existente si es necesario
    renombrar_carpeta_si_existe(ruta_carpeta_resumenes)
    
    # Crear la nueva carpeta de resúmenes
    try:
        os.makedirs(ruta_carpeta_resumenes)
        print(f"Carpeta de resúmenes creada: {ruta_carpeta_resumenes}")
    except OSError as e:
        print(f"Error al crear la carpeta de resúmenes '{ruta_carpeta_resumenes}': {e}. Verifique los permisos o si es un archivo.")
        return


    archivos_txt_encontrados = sorted([f for f in os.listdir(ruta_carpeta_textos) if f.endswith(".txt")])
    if not archivos_txt_encontrados:
        print(f"No se encontraron archivos .txt en '{ruta_carpeta_textos}'.")
        return

    print(f"Procesando {len(archivos_txt_encontrados)} archivos .txt de: {carpeta_textos_entrada}")

    for i, nombre_archivo in enumerate(archivos_txt_encontrados):
        print(f"\nProcesando documento {i+1}/{len(archivos_txt_encontrados)}: {nombre_archivo}")
        ruta_completa_archivo_txt = os.path.join(ruta_carpeta_textos, nombre_archivo)

        try:
            with open(ruta_completa_archivo_txt, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
            
            contenido_principal_texto = []
            capturando_contenido = False
            for linea in lineas:
                if "-------------------- CONTENIDO --------------------" in linea:
                    capturando_contenido = True; continue
                if capturando_contenido: contenido_principal_texto.append(linea)
            
            texto_documento_completo = "".join(contenido_principal_texto).strip()

            if not texto_documento_completo:
                print("    El contenido principal del documento está vacío. Saltando.")
                continue

            print(f"    Tokenizando y truncando texto (límite envío: {MAX_TOKENS_PARA_ENVIAR_MODELO} tokens)...")
            texto_para_modelo = truncar_texto_por_tokens(
                texto_documento_completo, ENCODING_TIKTOKEN, MAX_TOKENS_PARA_ENVIAR_MODELO
            )
            
            resumen = generar_resumen_con_groq(cliente_groq, texto_para_modelo)

            if resumen:
                nombre_archivo_resumen = nombre_archivo.rsplit('.txt', 1)[0] + "_resumen.txt"
                ruta_archivo_resumen = os.path.join(ruta_carpeta_resumenes, nombre_archivo_resumen)
                try:
                    with open(ruta_archivo_resumen, "w", encoding="utf-8") as f_resumen:
                        f_resumen.write(resumen)
                    print(f"    Resumen guardado en: {ruta_archivo_resumen}")
                except Exception as e_write_resumen:
                    print(f"    Error al escribir archivo de resumen {ruta_archivo_resumen}: {e_write_resumen}")
            else:
                print("    No se generó resumen para este documento.")
            
            if i + 1 < len(archivos_txt_encontrados):
                print(f"    Pausa mínima de {PAUSA_MINIMA_ENTRE_SOLICITUDES_SEGUNDOS:.2f}s antes del siguiente documento...")
                time.sleep(PAUSA_MINIMA_ENTRE_SOLICITUDES_SEGUNDOS)

        except Exception as e_file:
            print(f"  Error grave procesando archivo {nombre_archivo}: {e_file}")

    print("\nProcesamiento de resúmenes finalizado.")


if __name__ == "__main__":
    termino_busqueda_original_main = "decreto" 
    script_dir_main = os.path.dirname(__file__) if "__file__" in locals() else "."
    carpeta_textos_entrada_main = sanitizar_nombre(termino_busqueda_original_main, es_carpeta=True) + "_colectados"
    
    print(f"Iniciando script para generar resúmenes de docs en: '{carpeta_textos_entrada_main}' con el modelo {MODELO_GROQ}")
    procesar_documentos_para_resumen(carpeta_textos_entrada_main, termino_busqueda_original_main)
    print("Script de generación de resúmenes finalizado.")