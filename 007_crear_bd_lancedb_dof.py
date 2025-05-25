import os
import re
import time
import lancedb
from lancedb.pydantic import LanceModel, Vector as LanceVector # <--- CAMBIO IMPORTANTE
import ollama
import tiktoken
import numpy as np
from typing import List, Dict, Optional, Generator
import hashlib
# from pydantic import BaseModel # Ya no necesitamos el BaseModel genérico de pydantic

# --- Configuración ---
MODELO_EMBEDDING_OLLAMA = "bge-m3"
DIMENSION_EMBEDDING = 1024 # Inicial, se intentará verificar
CHUNK_SIZE_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 150
ENCODING_TIKTOKEN_CHUNKING = "cl100k_base"

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

def sanitizar_nombre_tabla_lancedb(nombre: str) -> str:
    nombre = nombre.lower()
    nombre = re.sub(r'\s+', '_', nombre)
    nombre = re.sub(r'[^\w-]', '', nombre)
    nombre = nombre[:60]
    if not nombre: return "documentos_dof"
    return nombre

def obtener_conteo_tokens_tiktoken(texto: str, encoding_nombre: str = ENCODING_TIKTOKEN_CHUNKING) -> int:
    try:
        encoding = tiktoken.get_encoding(encoding_nombre)
        return len(encoding.encode(texto))
    except Exception as e:
        # print(f"    Advertencia: Error al contar tokens con tiktoken: {e}. Usando conteo de palabras.")
        return len(texto.split())

def fragmentador_texto_con_traslape(texto_completo: str,
                                   chunk_size: int = CHUNK_SIZE_TOKENS,
                                   chunk_overlap: int = CHUNK_OVERLAP_TOKENS,
                                   encoding_nombre: str = ENCODING_TIKTOKEN_CHUNKING) -> Generator[str, None, None]:
    if not texto_completo.strip(): return
    try:
        encoding = tiktoken.get_encoding(encoding_nombre)
    except Exception as e:
        print(f"Error al obtener encoding de tiktoken '{encoding_nombre}': {e}. No se puede fragmentar.")
        return
    tokens_totales = encoding.encode(texto_completo)
    longitud_total_tokens = len(tokens_totales)
    if longitud_total_tokens == 0: return
    # print(f"      Fragmentando texto con {longitud_total_tokens} tokens totales (Estimados con {encoding_nombre}).")
    inicio = 0
    while inicio < longitud_total_tokens:
        fin = min(inicio + chunk_size, longitud_total_tokens)
        fragmento_tokens = tokens_totales[inicio:fin]
        fragmento_texto = encoding.decode(fragmento_tokens)
        fragmento_texto_limpio = fragmento_texto.strip()
        if fragmento_texto_limpio: yield fragmento_texto_limpio
        if fin == longitud_total_tokens: break
        avance = chunk_size - chunk_overlap
        inicio += avance
        if avance <= 0:
            # print("      Advertencia: El tamaño del traslape es >= al tamaño del fragmento. Avanzando al final.")
            inicio = fin

def generar_id_fragmento(nombre_archivo: str, indice_fragmento: int) -> str:
    hash_nombre = hashlib.md5(nombre_archivo.encode()).hexdigest()[:8]
    return f"{hash_nombre}_frag_{indice_fragmento}"

def obtener_embedding_ollama_para_bd(texto: str, modelo: str = MODELO_EMBEDDING_OLLAMA) -> Optional[List[float]]:
    try:
        response = ollama.embeddings(model=modelo, prompt=texto)
        return response.get('embedding')
    except Exception as e:
        print(f"    Error al generar embedding con Ollama para el texto '{texto[:50]}...': {e}")
        return None

def crear_base_de_datos_lance(carpeta_documentos_txt: str,
                               nombre_tabla_lancedb: str,
                               directorio_bd_lance: str = "./lance_db"):
    if not os.path.isdir(directorio_bd_lance):
        os.makedirs(directorio_bd_lance)
        print(f"Directorio de LanceDB creado: {directorio_bd_lance}")

    db = lancedb.connect(directorio_bd_lance)
    print(f"Conectado a LanceDB en: {directorio_bd_lance}")

    # Determinar la dimensión del embedding dinámicamente
    actual_dimension_usar = DIMENSION_EMBEDDING # Valor por defecto
    print(f"Obteniendo embedding de prueba para determinar dimensión con {MODELO_EMBEDDING_OLLAMA}...")
    test_embedding = obtener_embedding_ollama_para_bd("texto de prueba para dimension")
    if test_embedding:
        actual_dimension_usar = len(test_embedding)
        print(f"Dimensión de embedding detectada para '{MODELO_EMBEDDING_OLLAMA}': {actual_dimension_usar}. Usando esta dimensión para el esquema.")
    else:
        print(f"No se pudo obtener embedding de prueba. Usando dimensión por defecto: {actual_dimension_usar}. ¡ESTO PODRÍA CAUSAR PROBLEMAS SI NO ES CORRECTO!")
        # Considerar salir si no se puede determinar la dimensión si es crítico
        # return

    # --- Definición del Esquema con LanceModel ---
    class DocumentoFragmento(LanceModel): # <--- USAR LanceModel
        id: str
        texto: str
        # Usar LanceVector con la dimensión determinada
        vector: LanceVector(actual_dimension_usar) # <--- USAR LanceVector(dimension)
        nombre_archivo_original: str
        indice_fragmento_en_doc: int

    try:
        print(f"Intentando crear/sobrescribir tabla '{nombre_tabla_lancedb}'...")
        tabla = db.create_table(
            nombre_tabla_lancedb,
            schema=DocumentoFragmento, # Pasar la clase LanceModel directamente
            mode="overwrite"
        )
        print(f"Tabla '{nombre_tabla_lancedb}' creada/abierta exitosamente.")
    except Exception as e:
        print(f"Error crítico al definir esquema o crear tabla LanceDB: {e}")
        print("Posibles causas:")
        print("- La dimensión del vector en el esquema no coincide con la dimensión de los embeddings generados.")
        print("- Problemas de permisos en el directorio de LanceDB.")
        print("- Inconsistencias en la instalación de LanceDB o PyArrow.")
        return

    if not os.path.isdir(carpeta_documentos_txt):
        print(f"Error: La carpeta de documentos '{carpeta_documentos_txt}' no existe.")
        return

    print(f"Procesando archivos .txt en: {carpeta_documentos_txt}")
    archivos_procesados_count = 0
    fragmentos_totales_guardados = 0
    datos_para_lote = [] # Para añadir en lotes

    for nombre_archivo in sorted(os.listdir(carpeta_documentos_txt)):
        if nombre_archivo.endswith(".txt"):
            print(f"\n  Procesando archivo original: {nombre_archivo}")
            ruta_completa_archivo_txt = os.path.join(carpeta_documentos_txt, nombre_archivo)
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
                    print(f"    El contenido principal del documento {nombre_archivo} está vacío. Saltando.")
                    continue

                for i, fragmento_texto in enumerate(fragmentador_texto_con_traslape(texto_documento_completo)):
                    # print(f"    Generando embedding para fragmento {i+1} de '{nombre_archivo}'...") # Log menos verboso
                    embedding_vector = obtener_embedding_ollama_para_bd(fragmento_texto)
                    if embedding_vector:
                        if len(embedding_vector) != actual_dimension_usar:
                            print(f"    ADVERTENCIA: Dimensión de embedding ({len(embedding_vector)}) no coincide con esquema ({actual_dimension_usar}) para fragmento {i+1} de '{nombre_archivo}'. Saltando.")
                            continue
                        id_frag = generar_id_fragmento(nombre_archivo, i)
                        datos_para_lote.append({
                            "id": id_frag,
                            "texto": fragmento_texto,
                            "vector": embedding_vector,
                            "nombre_archivo_original": nombre_archivo,
                            "indice_fragmento_en_doc": i
                        })
                        # print(f"      Embedding generado para fragmento {id_frag} (Texto: '{fragmento_texto[:30]}...')")
                    else:
                        print(f"      No se pudo generar embedding para fragmento {i+1} de '{nombre_archivo}'.")
                    time.sleep(0.02) # Reducir pausa si Ollama es local y rápido

                archivos_procesados_count += 1
                if len(datos_para_lote) >= 100: # Añadir en lotes de 100 (o ajusta)
                    if datos_para_lote:
                        tabla.add(datos_para_lote)
                        print(f"    Se añadieron {len(datos_para_lote)} fragmentos a la tabla LanceDB.")
                        fragmentos_totales_guardados += len(datos_para_lote)
                        datos_para_lote = []


            except Exception as e_file:
                print(f"  Error procesando el archivo {nombre_archivo}: {e_file}")
    
    # Añadir cualquier fragmento restante en el lote
    if datos_para_lote:
        tabla.add(datos_para_lote)
        print(f"    Se añadieron {len(datos_para_lote)} fragmentos finales a la tabla LanceDB.")
        fragmentos_totales_guardados += len(datos_para_lote)

    print(f"\nProcesamiento de {archivos_procesados_count} archivos completado.")
    if fragmentos_totales_guardados > 0:
        print("Creando índice IVF_PQ en la tabla (puede tardar un poco)...")
        try:
            # Crear un índice después de añadir todos los datos
            # Los parámetros num_partitions y num_sub_vectors dependen del tamaño de tus datos
            # y la dimensionalidad. Puedes empezar con valores por defecto o experimentar.
            # Para bge-m3 (1024 dims), si tienes miles de vectores:
            # num_partitions podría ser sqrt(N) donde N es el número de vectores.
            # num_sub_vectors suele ser dim / 2 o dim / 4 (e.g., 1024/4 = 256, pero debe ser un divisor)
            # LanceDB puede elegir valores por defecto si no se especifican.
            # Un valor común para num_sub_vectors es 96 o 64 si la dimensión es alta.
            # Para 1024 dimensiones, a menudo se usa num_sub_vectors = 32 o 64.
            # LanceDB recomienda que num_partitions sea alrededor de sqrt(N_filas).
            # Si N_filas < 256 * (valor_grande), num_partitions = 1 es mejor.
            # Si tienes, por ejemplo, 5000 fragmentos, sqrt(5000) ~ 70.
            n_filas = tabla.count_rows()
            n_particiones_sugerido = int(np.sqrt(n_filas)) if n_filas > 256 else 1
            if n_particiones_sugerido > 256 : n_particiones_sugerido = 256 # Límite superior común

            print(f"Número de filas para indexar: {n_filas}. Particiones sugeridas: {n_particiones_sugerido}")
            tabla.create_index(
                metric="cosine", # O "l2"
                # num_partitions=n_particiones_sugerido, # Ajusta esto
                # num_sub_vectors=64, # Para dim 1024, 64 o 32 son comunes. Max 96.
                                    # Si da error, prueba sin estos y deja que LanceDB use defaults.
                replace=True
            )
            print("Índice IVF_PQ creado exitosamente.")
        except Exception as e_index:
            print(f"Error al crear el índice IVF_PQ: {e_index}")
            print("La tabla se creó, pero la búsqueda puede ser más lenta sin un índice vectorial optimizado.")

    print(f"Total de {fragmentos_totales_guardados} fragmentos con embeddings guardados en la tabla '{nombre_tabla_lancedb}'.")
    print(f"Base de datos LanceDB guardada en: {directorio_bd_lance}")


if __name__ == "__main__":
    termino_busqueda_original_main = "decreto" 
    script_dir_main = os.path.dirname(__file__) if "__file__" in locals() else "."
    carpeta_textos_entrada_main = sanitizar_nombre(termino_busqueda_original_main, es_carpeta=True) + "_colectados"
    ruta_carpeta_textos_completa = os.path.join(script_dir_main, carpeta_textos_entrada_main)
    nombre_tabla_db = sanitizar_nombre_tabla_lancedb(termino_busqueda_original_main)
    directorio_lance = os.path.join(script_dir_main, "lancedb_store_bge_m3") # Nuevo nombre de directorio para esta BD

    print(f"Iniciando creación de base de datos LanceDB para la búsqueda: '{termino_busqueda_original_main}'")
    print(f"Modelo de embedding Ollama: {MODELO_EMBEDDING_OLLAMA}")
    print(f"Directorio de LanceDB: {directorio_lance}")
    print(f"Nombre de la tabla en LanceDB: {nombre_tabla_db}")
    print(f"Carpeta de documentos de entrada: {ruta_carpeta_textos_completa}")

    crear_base_de_datos_lance(ruta_carpeta_textos_completa, nombre_tabla_db, directorio_bd_lance=directorio_lance)
    
    print("\nScript de creación de base de datos LanceDB finalizado.")
    print(f"Para verificar, puedes abrir la tabla '{nombre_tabla_db}' en otra sesión de Python:")
    print(f"  import lancedb")
    print(f"  db = lancedb.connect('{directorio_lance}')")
    print(f"  try:")
    print(f"    table = db.open_table('{nombre_tabla_db}')")
    print(f"    print(table.schema)")
    print(f"    print(f'Número de filas: {{table.count_rows()}}'))")
    print(f"    print(table.head(2).to_pandas())")
    print(f"  except Exception as e: print(f'Error al abrir la tabla: {{e}}')")