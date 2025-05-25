import os
import re
import lancedb
import ollama # Para generar embedding de la pregunta
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity # Para calcular similitud si es necesario manualmente (aunque LanceDB lo hace)
from typing import List, Dict, Optional

# --- Configuración ---
MODELO_EMBEDDING_OLLAMA = "bge-m3" # El mismo modelo usado para crear la BD
DIMENSION_EMBEDDING = 1024 # La dimensión de bge-m3
NUM_FRAGMENTOS_A_RECUPERAR = 4 # Cuántos fragmentos más similares traer

def sanitizar_nombre(nombre: str, es_carpeta=False) -> str: # Reutilizamos para nombre de tabla
    nombre = nombre.lower()
    nombre = re.sub(r'\s+', '_', nombre)
    if es_carpeta:
        nombre = re.sub(r'[^\w-]', '', nombre)
    else: # Para nombres de tabla u otros
        nombre = re.sub(r'[^\w.-]', '', nombre) # Permitir puntos por si acaso
    nombre = nombre[:60]
    if not nombre:
        if es_carpeta: return "datos_genericos"
        return "tabla_generica"
    return nombre

def obtener_embedding_ollama_pregunta(texto: str, modelo: str = MODELO_EMBEDDING_OLLAMA) -> Optional[np.ndarray]:
    """Genera un embedding para la pregunta del usuario."""
    try:
        response = ollama.embeddings(model=modelo, prompt=texto)
        embedding = response.get('embedding')
        if embedding:
            return np.array(embedding)
        else:
            print("Error: Ollama no devolvió un embedding para la pregunta.")
            return None
    except Exception as e:
        print(f"Error al generar embedding para la pregunta con Ollama: {e}")
        return None

def buscar_fragmentos_similares_lance(db_path: str, table_name: str, pregunta_texto: str, k: int = NUM_FRAGMENTOS_A_RECUPERAR) -> List[Dict]:
    """
    Conecta a LanceDB, genera embedding para la pregunta y busca los k fragmentos más similares.
    Devuelve los fragmentos recuperados como una lista de diccionarios.
    """
    try:
        db = lancedb.connect(db_path)
        table = db.open_table(table_name)
    except Exception as e:
        print(f"Error al conectar o abrir la tabla LanceDB '{table_name}' en '{db_path}': {e}")
        return []

    print(f"\nGenerando embedding para la pregunta: '{pregunta_texto[:100]}...'")
    pregunta_embedding = obtener_embedding_ollama_pregunta(pregunta_texto)

    if pregunta_embedding is None:
        return []

    print(f"Buscando los {k} fragmentos más similares en la tabla '{table_name}'...")
    try:
        # LanceDB puede tomar el vector directamente o el texto (y usará el modelo de embedding asociado si se definió con SourceField/VectorField)
        # Como aquí estamos generando el embedding de la pregunta explícitamente, lo pasamos.
        # Si el esquema de la tabla se creó con LanceModel y especificando un modelo de embedding
        # para el campo 'texto' (como SourceField), podríamos hacer table.search(pregunta_texto)
        # pero como construimos los embeddings fuera y los pasamos como List[float], es más seguro
        # generar el embedding de la pregunta con el mismo método y buscar por vector.
        
        # Asegurarse de que el vector de consulta sea una lista de floats para LanceDB
        query_vector_list = pregunta_embedding.tolist()

        results = table.search(query_vector_list).limit(k).to_list()
        # to_list() devuelve una lista de diccionarios, donde cada dict es una fila.
        # Ya incluye los metadatos y la distancia.
        
        print(f"Búsqueda completada. Se encontraron {len(results)} resultados.")
        return results
    except Exception as e:
        print(f"Error durante la búsqueda en LanceDB: {e}")
        return []


if __name__ == "__main__":
    termino_busqueda_usado = "decreto" # El mismo término usado para crear la BD y la tabla

    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    directorio_bd = os.path.join(script_dir, "lancedb_store_bge_m3") # Donde guardaste la BD Lance
    nombre_de_la_tabla = sanitizar_nombre(termino_busqueda_usado, es_carpeta=False) # Sanitiza para nombre de tabla

    print("Mini Aplicación de Consulta RAG (Terminal) - Probando LanceDB")
    print("----------------------------------------------------------")
    print(f"Usando Base de Datos LanceDB en: {directorio_bd}")
    print(f"Tabla: {nombre_de_la_tabla}")
    print(f"Modelo de Embedding (Ollama): {MODELO_EMBEDDING_OLLAMA}")
    print(f"Se recuperarán los {NUM_FRAGMENTOS_A_RECUPERAR} fragmentos más relevantes.")
    print("----------------------------------------------------------")

    if not os.path.exists(directorio_bd) or not os.path.isdir(directorio_bd):
        print(f"Error: El directorio de la base de datos LanceDB '{directorio_bd}' no existe.")
        print("Asegúrate de haber ejecutado primero el script 'crear_bd_lancedb_dof.py'.")
        exit()
    
    # Pequeña prueba para ver si podemos abrir la tabla
    try:
        db_test = lancedb.connect(directorio_bd)
        tbl_test = db_test.open_table(nombre_de_la_tabla)
        print(f"Tabla '{nombre_de_la_tabla}' abierta exitosamente. Contiene {tbl_test.count_rows()} fragmentos.")
        # print("Esquema de la tabla:")
        # print(tbl_test.schema)
    except Exception as e_test:
        print(f"Error al intentar abrir la tabla '{nombre_de_la_tabla}' para prueba inicial: {e_test}")
        print("Asegúrate de que el nombre de la tabla y el directorio de la BD sean correctos y la BD se haya creado.")
        exit()


    while True:
        pregunta_usuario = input("\nIntroduce tu pregunta sobre los decretos (o escribe 'salir' para terminar):\n> ")
        if pregunta_usuario.lower() == 'salir':
            break
        if not pregunta_usuario.strip():
            continue

        fragmentos_recuperados = buscar_fragmentos_similares_lance(directorio_bd, nombre_de_la_tabla, pregunta_usuario)

        if fragmentos_recuperados:
            print("\n--- Fragmentos Recuperados Más Relevantes ---")
            for i, frag_info in enumerate(fragmentos_recuperados):
                print(f"\nFragmento {i+1}:")
                print(f"  ID del Fragmento: {frag_info.get('id', 'N/A')}")
                print(f"  Archivo Original: {frag_info.get('nombre_archivo_original', 'N/A')}")
                print(f"  Índice en Documento: {frag_info.get('indice_fragmento_en_doc', 'N/A')}")
                # La distancia es una métrica interna de LanceDB, menor es mejor para L2/Euclidiana, mayor es mejor para Coseno (si no está normalizada a distancia)
                # Por defecto, search() ordena por la métrica con la que se creó el índice (o L2 si no hay índice).
                # bge-m3 suele usar similitud coseno, por lo que un valor más alto de similitud (o menor distancia coseno) es mejor.
                # LanceDB devuelve un campo '_distance' que para 'cosine' es 1 - similitud_coseno (menor es mejor).
                if '_distance' in frag_info:
                    print(f"  Distancia (menor es mejor): {frag_info['_distance']:.4f}")
                print(f"  Texto del Fragmento (primeros 300 caracteres):\n    \"{frag_info.get('texto', '')[:300]}...\"")
            print("--------------------------------------------")
        else:
            print("No se encontraron fragmentos relevantes para tu pregunta en la base de datos.")

    print("\nSaliendo de la aplicación de consulta.")