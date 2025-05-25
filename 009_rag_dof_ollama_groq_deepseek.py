import os
import re
import time
import json
import numpy as np
import ollama
import lancedb
from groq import Groq
from dotenv import load_dotenv
from typing import List, Dict, Optional, Tuple
import tiktoken

# --- Configuración ---
load_dotenv()

MODELO_EMBEDDING_OLLAMA = "bge-m3"
DIMENSION_EMBEDDING = 1024
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODELO_GENERACION_GROQ = "deepseek-r1-distill-llama-70b"
ENCODING_TIKTOKEN_GENERACION = "cl100k_base"

LIMITE_SOLICITUDES_POR_MINUTO_GROQ = 30
LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ = 6000

NUM_DOCUMENTOS_RELEVANTES_K = 4
MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO = 1000
MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO = 400
MAX_CONTEXTO_TOTAL_PARA_GENERACION = LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ * 0.90
MAX_COMPLETION_TOKENS_GENERACION = 768
TEMPERATURE_GENERACION = 0.3

MAX_API_REINTENTOS_GROQ = 3
TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS = 10
PAUSA_MINIMA_GROQ_SEGUNDOS = 2.0

solicitudes_en_minuto_actual_groq = 0
tokens_procesados_en_minuto_actual_groq = 0
inicio_minuto_actual_groq = time.time()

def sanitizar_nombre(nombre: str, es_carpeta=False) -> str:
    nombre = nombre.lower(); nombre = re.sub(r'\s+', '_', nombre)
    if es_carpeta: nombre = re.sub(r'[^\w-]', '', nombre)
    else: nombre = re.sub(r'[^\w.-]', '', nombre)
    nombre = nombre[:60]
    if not nombre:
        if es_carpeta: return "datos_genericos"
        return "tabla_generica"
    return nombre

def obtener_conteo_tokens_tiktoken(texto: str, encoding_nombre: str = ENCODING_TIKTOKEN_GENERACION) -> int:
    try: return len(tiktoken.get_encoding(encoding_nombre).encode(texto))
    except Exception: return len(texto.split())

def obtener_embedding_ollama_pregunta(texto: str, modelo: str = MODELO_EMBEDDING_OLLAMA) -> Optional[np.ndarray]:
    try:
        response = ollama.embeddings(model=modelo, prompt=texto)
        embedding = response.get('embedding')
        if embedding: return np.array(embedding)
        print("Error: Ollama no devolvió embedding para la pregunta."); return None
    except Exception as e: print(f"Error generando embedding (Ollama): {e}"); return None

def buscar_fragmentos_similares_lance(db_path: str, table_name: str, pregunta_texto: str, k: int = NUM_DOCUMENTOS_RELEVANTES_K) -> List[Dict]:
    try:
        db = lancedb.connect(db_path); table = db.open_table(table_name)
    except Exception as e: print(f"Error conectando/abriendo tabla LanceDB '{table_name}': {e}"); return []
    print(f"Generando embedding para pregunta: '{pregunta_texto[:70]}...'")
    pregunta_embedding = obtener_embedding_ollama_pregunta(pregunta_texto)
    if pregunta_embedding is None: return []
    print(f"Buscando {k} fragmentos más similares en '{table_name}'...")
    try:
        results = table.search(pregunta_embedding.tolist()).limit(k).to_list()
        print(f"Búsqueda completada. {len(results)} resultados."); return results
    except Exception as e: print(f"Error en búsqueda LanceDB: {e}"); return []

def verificar_y_esperar_limites_groq(tokens_prompt_generacion: int):
    global solicitudes_en_minuto_actual_groq, tokens_procesados_en_minuto_actual_groq, inicio_minuto_actual_groq
    tiempo_actual = time.time()
    max_prompt_seguro = MAX_CONTEXTO_TOTAL_PARA_GENERACION 

    if tiempo_actual - inicio_minuto_actual_groq >= 60:
        print(f"    -- Nuevo minuto API Groq. Reset (Sols: {solicitudes_en_minuto_actual_groq}, Tokens: {tokens_procesados_en_minuto_actual_groq}) --")
        solicitudes_en_minuto_actual_groq = 0; tokens_procesados_en_minuto_actual_groq = 0; inicio_minuto_actual_groq = tiempo_actual
    
    if tokens_prompt_generacion > max_prompt_seguro :
        raise ValueError(f"Prompt ({tokens_prompt_generacion}) excede umbral seguro ({max_prompt_seguro}) para TPM ({LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ}).")

    if solicitudes_en_minuto_actual_groq >= LIMITE_SOLICITUDES_POR_MINUTO_GROQ:
        espera = 60.1 - (tiempo_actual - inicio_minuto_actual_groq)
        if espera > 0: print(f"    Límite {LIMITE_SOLICITUDES_POR_MINUTO_GROQ} Sols/min (Groq) alcanzado. Esperando {espera:.2f}s..."); time.sleep(espera)
        solicitudes_en_minuto_actual_groq = 0; tokens_procesados_en_minuto_actual_groq = 0; inicio_minuto_actual_groq = time.time()

    proyectados = tokens_procesados_en_minuto_actual_groq + tokens_prompt_generacion + MAX_COMPLETION_TOKENS_GENERACION
    if proyectados > LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ:
        espera = 60.1 - (tiempo_actual - inicio_minuto_actual_groq)
        if espera > 0: print(f"    Límite Tokens/min (Groq) (proy. {proyectados}/{LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ}) cercano. Esperando {espera:.2f}s..."); time.sleep(espera)
        solicitudes_en_minuto_actual_groq = 0; tokens_procesados_en_minuto_actual_groq = 0; inicio_minuto_actual_groq = time.time()

def leer_resumen_de_archivo(nombre_archivo_original_txt: str, carpeta_base_resumenes: str) -> Optional[str]:
    nombre_archivo_resumen = nombre_archivo_original_txt.rsplit('.txt', 1)[0] + "_resumen.txt"
    ruta_archivo_resumen = os.path.join(carpeta_base_resumenes, nombre_archivo_resumen)
    if os.path.exists(ruta_archivo_resumen):
        try:
            with open(ruta_archivo_resumen, 'r', encoding='utf-8') as f_resumen:
                return f_resumen.read().strip()
        except Exception as e:
            # print(f"    Advertencia: No se pudo leer el archivo de resumen '{ruta_archivo_resumen}': {e}")
            return None
    return None

def generar_respuesta_con_rag_groq(cliente_groq: Groq, pregunta_usuario: str, documentos_contexto: List[Dict[str, any]], carpeta_resumenes: str) -> Tuple[Optional[str], int]:
    global solicitudes_en_minuto_actual_groq, tokens_procesados_en_minuto_actual_groq
    tokens_prompt_final_enviados = 0
    if not documentos_contexto: return "No pude encontrar documentos relevantes para responder.", 0
    contexto_str_parts = []
    archivos_originales_ya_con_resumen = set()
    for doc in documentos_contexto:
        nombre_original = doc.get('nombre_archivo_original')
        if nombre_original and nombre_original not in archivos_originales_ya_con_resumen:
            resumen_texto = leer_resumen_de_archivo(nombre_original, carpeta_resumenes)
            if resumen_texto:
                encoding = tiktoken.get_encoding(ENCODING_TIKTOKEN_GENERACION)
                tokens_resumen = encoding.encode(resumen_texto)
                if len(tokens_resumen) > MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO:
                    resumen_texto = encoding.decode(tokens_resumen[:MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO])
                contexto_str_parts.append(f"Resumen del documento '{nombre_original}':\n{resumen_texto}")
                archivos_originales_ya_con_resumen.add(nombre_original)
    if contexto_str_parts: contexto_str_parts.append("\n--- Detalles de Fragmentos Específicos Recuperados ---")
    for doc_idx, doc in enumerate(documentos_contexto):
        texto_fragmento = doc.get('texto', '')
        encoding = tiktoken.get_encoding(ENCODING_TIKTOKEN_GENERACION)
        tokens_originales_fragmento = encoding.encode(texto_fragmento)
        if len(tokens_originales_fragmento) > MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO:
            texto_fragmento = encoding.decode(tokens_originales_fragmento[:MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO])
        contexto_str_parts.append(f"Fragmento {doc_idx+1} (del archivo: '{doc.get('nombre_archivo_original', 'N/A')}', ID: {doc.get('id','N/A')}):\n{texto_fragmento}")
    contexto_str = "\n\n".join(contexto_str_parts)
    prompt_completo = (
        "Eres un asistente experto en responder preguntas sobre documentos del Diario Oficial de la Federación (DOF) de México. "
        "Tu respuesta debe basarse ESTRICTAMENTE en la información contenida en los siguientes resúmenes y fragmentos de documentos proporcionados. "
        "Primero se presentan resúmenes generales de los documentos relevantes, seguidos de fragmentos específicos. "
        "Sé directo y factual. Si la información necesaria para responder la pregunta no está presente en los fragmentos, debes indicar claramente: "
        "'La información específica para responder a su pregunta no se encuentra en los fragmentos de documentos proporcionados.' "
        "No inventes información ni hagas suposiciones más allá del texto dado.\n\n"
        f"PREGUNTA DEL USUARIO:\n{pregunta_usuario}\n\n"
        "CONTEXTO (RESÚMENES Y FRAGMENTOS DE DOCUMENTOS RELEVANTES):\n"
        f"{contexto_str}\n\n"
        "RESPUESTA (basada únicamente en el contexto anterior):"
    )
    tokens_prompt_final_enviados = obtener_conteo_tokens_tiktoken(prompt_completo)
    
    # --- MOSTRAR EL PROMPT COMPLETO ---
    print("\n--- PROMPT COMPLETO ENVIADO A GROQ ---")
    print(prompt_completo)
    print(f"--- FIN DEL PROMPT (Tokens estimados: {tokens_prompt_final_enviados}) ---\n")
    # ------------------------------------
    
    try: verificar_y_esperar_limites_groq(tokens_prompt_final_enviados)
    except ValueError as e_val: return f"Error prompt: {e_val}", tokens_prompt_final_enviados

    for intento in range(MAX_API_REINTENTOS_GROQ):
        try:
            stream = cliente_groq.chat.completions.create(
                model=MODELO_GENERACION_GROQ,
                messages=[{"role": "user", "content": prompt_completo}],
                temperature=TEMPERATURE_GENERACION, max_tokens=MAX_COMPLETION_TOKENS_GENERACION, top_p=1, stream=True
            )
            respuesta_llm = "".join([chunk.choices[0].delta.content or "" for chunk in stream])
            tokens_respuesta = obtener_conteo_tokens_tiktoken(respuesta_llm)
            solicitudes_en_minuto_actual_groq += 1
            tokens_procesados_en_minuto_actual_groq += tokens_prompt_final_enviados + tokens_respuesta
            return respuesta_llm.strip(), tokens_prompt_final_enviados
        except Exception as e:
            error_str = str(e).lower()
            print(f"    Error API Groq (intento {intento + 1}/{MAX_API_REINTENTOS_GROQ}): {e}")
            if "rate limit" in error_str or "ratelimit" in error_str or "429" in error_str or "413" in error_str:
                espera = 60.1 if "429" in error_str else TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS * (intento + 1)
                print(f"    Error límite API. Esperando {espera:.1f}s..."); time.sleep(espera)
                if "429" in error_str or "413" in error_str: 
                    solicitudes_en_minuto_actual_groq = 0; tokens_procesados_en_minuto_actual_groq = 0; inicio_minuto_actual_groq = time.time()
            elif intento < MAX_API_REINTENTOS_GROQ - 1:
                time.sleep(TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS)
            else: return "Error persistente con API Groq.", tokens_prompt_final_enviados
    return "No se pudo obtener respuesta del modelo Groq.", tokens_prompt_final_enviados

if __name__ == "__main__":
    if not GROQ_API_KEY: print("Error: GROQ_API_KEY no configurada."); exit()
    cliente_groq_main = Groq()
    termino_busqueda_usado = "decreto"
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    directorio_bd = os.path.join(script_dir, "lancedb_store_bge_m3")
    nombre_de_la_tabla = sanitizar_nombre(termino_busqueda_usado, es_carpeta=False)
    carpeta_resumenes_entrada = sanitizar_nombre(termino_busqueda_usado, es_carpeta=True) + "_colectados_resumen"
    ruta_carpeta_resumenes_completa = os.path.join(script_dir, carpeta_resumenes_entrada)

    print(f"App RAG :: DOF :: Ollama (Embed) :: Groq (Gen) || Modelo Groq: {MODELO_GENERACION_GROQ}")
    print(f"Usando resúmenes de: {ruta_carpeta_resumenes_completa}")
    print("--------------------------------------------------------------------------------")
    if not os.path.exists(directorio_bd) or not os.path.isdir(directorio_bd):
        print(f"Error: Dir BD LanceDB '{directorio_bd}' no existe."); exit()
    if not os.path.exists(ruta_carpeta_resumenes_completa) or not os.path.isdir(ruta_carpeta_resumenes_completa):
        print(f"Error: Carpeta de resúmenes '{ruta_carpeta_resumenes_completa}' no existe."); exit()
    try:
        db_test = lancedb.connect(directorio_bd); tbl_test = db_test.open_table(nombre_de_la_tabla)
        print(f"Tabla LanceDB '{nombre_de_la_tabla}' abierta. Contiene {tbl_test.count_rows()} fragmentos (de docs completos).")
    except Exception as e_test: print(f"Error al abrir tabla '{nombre_de_la_tabla}': {e_test}"); exit()

    while True:
        pregunta_usuario = input("\nIntroduce tu pregunta (o 'salir'):\n> ")
        if pregunta_usuario.lower() == 'salir': break
        if not pregunta_usuario.strip(): continue
        fragmentos_recuperados = buscar_fragmentos_similares_lance(directorio_bd, nombre_de_la_tabla, pregunta_usuario)
        respuesta_llm_texto, tokens_usados_prompt_llm = "No se procesó.", 0
        if fragmentos_recuperados:
            respuesta_llm_texto, tokens_usados_prompt_llm = generar_respuesta_con_rag_groq(
                cliente_groq_main, pregunta_usuario, fragmentos_recuperados, ruta_carpeta_resumenes_completa
            )
        else:
            respuesta_llm_texto = "No se encontraron fragmentos relevantes."
        
        print("\nRespuesta del Asistente RAG:")
        print("==================================================")
        print(respuesta_llm_texto if respuesta_llm_texto else "El modelo no generó una respuesta.")
        print("==================================================")
        # No mostramos el conteo de tokens del prompt aquí, ya se mostró antes de la llamada a Groq
        
        if fragmentos_recuperados:
            print("\n--- Fragmentos de Documentos Originales Usados para Contextualizar (base de la recuperación) ---")
            for i, frag_info in enumerate(fragmentos_recuperados):
                distancia = frag_info.get('_distance', float('inf'))
                print(f"\nFragmento {i+1}:")
                print(f"  ID: {frag_info.get('id', 'N/A')}")
                print(f"  Archivo Original: {frag_info.get('nombre_archivo_original', 'N/A')}")
                print(f"  Índice en Documento: {frag_info.get('indice_fragmento_en_doc', 'N/A')}")
                print(f"  Distancia (menor es mejor): {distancia:.4f}")
                print(f"  Texto del Fragmento (primeros 250 caracteres):\n    \"{frag_info.get('texto', '')[:250].replace(chr(10), ' ')}...\"")
            print("------------------------------------------------------------------------------------")
        time.sleep(PAUSA_MINIMA_GROQ_SEGUNDOS)
    print("\nSaliendo...")