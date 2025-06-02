# setup_web_project.py
import os
import shutil
import ast
import textwrap
import traceback
import re

# --- Configuración del Proyecto ---
PROJECT_ROOT = os.getcwd()
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

KEYWORD_FOR_DATA = "decreto"
LANCEDB_TABLE_NAME_FIXED = KEYWORD_FOR_DATA
DIR_DOCUMENTOS_COMPLETOS_FIXED = f"{KEYWORD_FOR_DATA}_colectados"
DIR_RESUMENES_FIXED = f"{KEYWORD_FOR_DATA}_colectados_resumen"
DIR_LANCEDB_FIXED = "lancedb_store_bge_m3"

# --- Funciones Auxiliares (sin cambios) ---
def create_dir_if_not_exists(path):
    os.makedirs(path, exist_ok=True)
    print(f"INFO: Directorio creado/verificado: {path}")

def create_file_with_content(filepath, content, overwrite_if_exists=False, is_critical_structure_file=False):
    file_basename = os.path.basename(filepath)
    proceed_with_write = False; action_taken_log = ""
    if os.path.exists(filepath):
        if overwrite_if_exists or is_critical_structure_file:
            if is_critical_structure_file: print(f"ADVERTENCIA: Archivo crítico '{file_basename}' será sobrescrito.")
            proceed_with_write = True; action_taken_log = "actualizado (sobrescrito)"
        else: print(f"INFO: Archivo '{file_basename}' ya existe. No se sobrescribirá."); return
    else: proceed_with_write = True; action_taken_log = "creado"
    if proceed_with_write:
        try:
            dedented_content = textwrap.dedent(content)
            with open(filepath, "w", encoding="utf-8") as f: f.write(dedented_content)
            print(f"INFO: Archivo {action_taken_log}: {file_basename}")
        except Exception as e: print(f"ERROR_CRITICAL: Escribiendo {filepath}: {e}\n{traceback.format_exc()}")

def get_module_level_imports_from_source(source_code, script_name_for_log=""):
    imports_code_list = []
    try:
        tree = ast.parse(source_code)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports_code_list.append(ast.unparse(node))
    except SyntaxError as se: print(f"ADVERTENCIA_SYNTAX (get_imports): '{script_name_for_log}': {se}")
    except Exception: pass
    return "\n".join(sorted(list(set(imports_code_list))))

def extract_ast_nodes_as_string(source_code, node_names, node_type, script_name_for_log=""):
    extracted_code_list = []; mutable_node_names = list(node_names) if node_names else []
    if not mutable_node_names: return ""
    try:
        tree = ast.parse(source_code)
        for node in tree.body:
            current_node_name = None; is_target_node_type = False
            if node_type == "function" and isinstance(node, ast.FunctionDef): current_node_name = node.name; is_target_node_type = True
            elif node_type == "global_assign" and isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name): current_node_name = target.id; is_target_node_type = True; break
            if is_target_node_type and current_node_name in mutable_node_names:
                extracted_code_list.append(ast.unparse(node))
                if node_type == "global_assign":
                    while current_node_name in mutable_node_names: mutable_node_names.remove(current_node_name)
    except SyntaxError as se: print(f"ADVERTENCIA_SYNTAX (extract_nodes): '{script_name_for_log}' para '{node_names}': {se}")
    except Exception as e: print(f"ADVERTENCIA_EXTRACTION (extract_nodes): '{script_name_for_log}' para '{node_names}': {e}")
    return "\n\n".join(extracted_code_list)

def extract_specific_function_node(source_code, function_name):
    try:
        tree = ast.parse(source_code)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == function_name: return node
    except SyntaxError as se: print(f"ADVERTENCIA_SYNTAX (extract_specific_node): al buscar '{function_name}': {se}")
    except Exception: pass
    return None

def modify_function_signature_defaults(func_node: ast.FunctionDef, defaults_map: dict):
    if not func_node: return
    num_args = len(func_node.args.args); num_defaults = len(func_node.args.defaults)
    for i, arg_node in enumerate(reversed(func_node.args.args)):
        arg_name = arg_node.arg; default_idx_from_right = i
        if default_idx_from_right < num_defaults:
            actual_default_idx = num_defaults - 1 - default_idx_from_right
            if arg_name in defaults_map:
                try:
                    new_default_value_str = defaults_map[arg_name]; parts = new_default_value_str.split('.')
                    if len(parts) == 2:
                        new_default_node = ast.Attribute(value=ast.Name(id=parts[0], ctx=ast.Load()), attr=parts[1], ctx=ast.Load())
                        func_node.args.defaults[actual_default_idx] = new_default_node
                except Exception as e_ast_mod: print(f"ADVERTENCIA_SIGNATURE: Modificando default para '{arg_name}': {e_ast_mod}")

def extract_and_adapt_function(script_path, function_name, signature_defaults_to_inject: dict = None):
    if not os.path.exists(script_path): return f"# INFO: Archivo fuente para '{function_name}' ({os.path.basename(script_path)}) no encontrado."
    try:
        with open(script_path, "r", encoding="utf-8") as f: source_code = f.read()
        func_node = extract_specific_function_node(source_code, function_name)
        if func_node:
            if signature_defaults_to_inject: modify_function_signature_defaults(func_node, signature_defaults_to_inject)
            return ast.unparse(func_node)
        return f"# INFO: Función '{function_name}' no encontrada en {os.path.basename(script_path)} para extracción automática."
    except Exception as e:
        print(f"ERROR_PROCESSING_SCRIPT (extract_and_adapt): {script_path} para '{function_name}': {e}\n{traceback.format_exc()}")
        return f"# ERROR: No se pudo extraer '{function_name}' de {os.path.basename(script_path)}. Revise el traceback.\n# DEBES IMPLEMENTARLA MANUALMENTE."

def extract_globals_from_script(script_path, global_var_names):
    if not os.path.exists(script_path): return ""
    with open(script_path, "r", encoding="utf-8") as f: source_code = f.read()
    return extract_ast_nodes_as_string(source_code, global_var_names, "global_assign", os.path.basename(script_path))

def get_all_imports_from_script(script_path):
    if not os.path.exists(script_path): return ""
    with open(script_path, "r", encoding="utf-8") as f: source_code = f.read()
    return get_module_level_imports_from_source(source_code, os.path.basename(script_path))

# --- 1. Crear Estructura de Directorios ---
def setup_directories():
    print("\n--- Creando Directorios ---")
    create_dir_if_not_exists(CORE_DIR); create_dir_if_not_exists(TEMPLATES_DIR); create_dir_if_not_exists(STATIC_DIR)
    create_file_with_content(os.path.join(CORE_DIR, "__init__.py"), "# Core module", overwrite_if_exists=True)
    create_file_with_content(os.path.join(STATIC_DIR, "style.css"), "/* CSS */ body { font-family: sans-serif; }", overwrite_if_exists=True)
    print("-" * 30 + "\n")

# --- 2. Crear Archivos del Módulo `core` ---
def setup_core_module():
    print("--- Configurando Módulo 'core' ---")

    # config.py (Sobrescrito)
    sanitizar_tabla_func_code_str = """
def sanitizar_nombre_tabla_lancedb(nombre: str) -> str:
    nombre = str(nombre).lower()
    nombre = re.sub(r'\\s+', '_', nombre)
    nombre = re.sub(r'[^\\w-]', '', nombre)
    nombre = nombre[:60]
    return nombre if nombre else "documentos_dof"
"""
    # CORRECCIÓN: Las f-strings internas DEBEN usar las variables definidas DENTRO de config.py.
    # El .format() exterior solo inserta el bloque de sanitizar_tabla_func_code_str.
    config_py_content_template = """# core/config.py (SOBRESCRITO POR SETUP)
import os
from dotenv import load_dotenv
import re

DOTENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if not os.path.exists(DOTENV_PATH):
    print(f"ADVERTENCIA_CONFIG: Archivo .env no encontrado en la ruta esperada: {{DOTENV_PATH}}") # Esta f-string usará DOTENV_PATH de este scope
else:
    print(f"INFO_CONFIG: Cargando .env desde: {{DOTENV_PATH}}") # Esta f-string usará DOTENV_PATH de este scope
    load_dotenv(dotenv_path=DOTENV_PATH)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODELO_EMBEDDING_OLLAMA = "bge-m3"
MODELO_GENERACION_GROQ = "deepseek-r1-distill-llama-70b"

PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANCEDB_DIR_NAME = "{fixed_lancedb_dir_name}"
DECRETOS_DIR_NAME = "{fixed_decretos_dir_name}"
RESUMENES_DIR_NAME = "{fixed_resumenes_dir_name}"
LANCEDB_DIR = os.path.join(PROJECT_ROOT_DIR, LANCEDB_DIR_NAME)
DECRETOS_COLECTADOS_DIR = os.path.join(PROJECT_ROOT_DIR, DECRETOS_DIR_NAME)
RESUMENES_DIR = os.path.join(PROJECT_ROOT_DIR, RESUMENES_DIR_NAME)

NUM_FRAGMENTOS_A_RECUPERAR_LANCEDB = 4
LANCEDB_TABLE_NAME_DEFAULT = "{fixed_lancedb_table_name}"
NUM_DOCUMENTOS_RELEVANTES_K_RAG = 4
MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO = 1000
MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO = 400
ENCODING_TIKTOKEN_GENERACION = "cl100k_base"
LIMITE_SOLICITUDES_POR_MINUTO_GROQ = 30
LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ = 6000
MAX_COMPLETION_TOKENS_GENERACION = 768
TEMPERATURE_GENERACION = 0.3
MAX_API_REINTENTOS_GROQ = 3
TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS = 10

{s_func_code}

print(f"INFO_CONFIG: core/config.py inicializado. GROQ_API_KEY: {{'Presente' if GROQ_API_KEY else 'AUSENTE - ¡Revisar .env!'}}")
for name, path_val in [
    ("Directorio LanceDB", LANCEDB_DIR), ("Docs Completos", DECRETOS_COLECTADOS_DIR), ("Resúmenes", RESUMENES_DIR)
]:
    status = "Encontrado" if os.path.isdir(path_val) else "NO ENCONTRADO - ¡VERIFICAR RUTA!"
    print(f"  {{name}}: {{path_val}} ({{status}})")
"""
    config_py_content = config_py_content_template.format(
        s_func_code=sanitizar_tabla_func_code_str, # Este es el único placeholder para .format()
        # Los siguientes son para los f-strings internos de la plantilla, así que no necesitan pasarse al .format() exterior
        # DOTENV_PATH="DOTENV_PATH", # Esto era incorrecto
        fixed_lancedb_dir_name=DIR_LANCEDB_FIXED,
        fixed_decretos_dir_name=DIR_DOCUMENTOS_COMPLETOS_FIXED,
        fixed_resumenes_dir_name=DIR_RESUMENES_FIXED,
        fixed_lancedb_table_name=LANCEDB_TABLE_NAME_FIXED
    )
    create_file_with_content(os.path.join(CORE_DIR, "config.py"), config_py_content, is_critical_structure_file=True)

    # ... (Resto de setup_core_module como en la respuesta anterior,
    #      asegurándose de que file_operations.py, lancedb_service.py, y rag_service.py
    #      se generen correctamente. La corrección principal fue en config.py) ...

    fp_path = os.path.join(CORE_DIR, "file_operations.py")
    if not os.path.exists(fp_path):
        # La función sanitizar_nombre no se extrae, se define una genérica.
        file_operations_content = """# core/file_operations.py (Creado por setup)
import os; import re; from . import config

def sanitizar_nombre(nombre: str, es_carpeta=False) -> str:
    # Implementación genérica de sanitizar_nombre
    n = str(nombre).lower()
    n = re.sub(r'\\s+', '_', n) # Doble backslash para \s
    n = re.sub(r'[^\\w\\-\\.]' if not es_carpeta else r'[^\\w-]', '', n) # Doble backslash para \w, \-
    n = n[:150] # Limitar longitud
    return n if n else ('carpeta_vacia' if es_carpeta else 'archivo_vacio')

def _list_files_generic(directory: str, extension: str = ".txt") -> list:
    if not os.path.isdir(directory): return []
    try: return sorted([f for f in os.listdir(directory) if f.endswith(extension)])
    except Exception as e: print(f"ERROR_FILE_OPS (list): {directory} {e}"); return []

def _read_content_generic(directory: str, filename: str) -> str | None:
    filepath = os.path.join(directory, filename)
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f: lines = f.readlines()
        separator = "-------------------- CONTENIDO --------------------"
        doc_content = "".join(lines)
        if separator in doc_content:
            content_part = doc_content.split(separator, 1)
            return content_part[1].strip() if len(content_part) > 1 else doc_content.strip()
        return doc_content.strip()
    except Exception as e: print(f"ERROR_FILE_OPS (read): {filepath} {e}"); return None

def get_full_documents_list() -> list: return _list_files_generic(config.DECRETOS_COLECTADOS_DIR)
def get_summaries_list() -> list: return _list_files_generic(config.RESUMENES_DIR)
def get_full_document_content(filename: str) -> str | None: return _read_content_generic(config.DECRETOS_COLECTADOS_DIR, filename)
def get_summary_content_by_summary_filename(summary_filename: str) -> str | None: return _read_content_generic(config.RESUMENES_DIR, summary_filename)
def get_summary_content_by_original_filename(original_doc_filename: str) -> str | None:
    base_name = original_doc_filename.rsplit('.txt', 1)[0]
    summary_filename_expected = f"{base_name}_resumen.txt"
    return _read_content_generic(config.RESUMENES_DIR, summary_filename_expected)
"""
        create_file_with_content(fp_path, file_operations_content, overwrite_if_exists=False)


    ls_path = os.path.join(CORE_DIR, "lancedb_service.py")
    if not os.path.exists(ls_path):
        lancedb_service_content = """# core/lancedb_service.py (Creado por setup con lógica funcional)
from . import config
import numpy as np
from typing import List, Dict, Optional
import lancedb
import traceback
import ollama
import os

def obtener_embedding_ollama_pregunta(texto: str, modelo: str = config.MODELO_EMBEDDING_OLLAMA) -> Optional[np.ndarray]:
    try:
        response = ollama.embeddings(model=modelo, prompt=texto)
        embedding = response.get('embedding')
        return np.array(embedding) if embedding else None
    except Exception as e_ollama:
        print(f"ERROR_OLLAMA_EMBED: No se pudo generar embedding con Ollama (modelo: {modelo}): {e_ollama}")
        return None

def buscar_en_lancedb_web(pregunta_texto: str, k: int = config.NUM_FRAGMENTOS_A_RECUPERAR_LANCEDB) -> List[Dict]:
    if not os.path.isdir(config.LANCEDB_DIR):
        print(f"ERROR_LANCEDB: Directorio LanceDB no existe: {config.LANCEDB_DIR}")
        return []
    pregunta_embedding_np = obtener_embedding_ollama_pregunta(pregunta_texto)
    if pregunta_embedding_np is None: return []
    query_vector_list = pregunta_embedding_np.tolist()
    try:
        db = lancedb.connect(config.LANCEDB_DIR)
        if config.LANCEDB_TABLE_NAME_DEFAULT not in db.table_names():
            print(f"ERROR_LANCEDB: Tabla '{config.LANCEDB_TABLE_NAME_DEFAULT}' no en {db.table_names()}.")
            return []
        table = db.open_table(config.LANCEDB_TABLE_NAME_DEFAULT)
        results = table.search(query_vector_list).limit(k).to_list()
        print(f"INFO_LANCEDB: {len(results)} resultados para '{pregunta_texto[:20].replace(chr(10),' ')}...'")
        return results
    except Exception as e_search:
        print(f"ERROR_LANCEDB (search): {e_search}\\n{traceback.format_exc()}")
        return []
"""
        create_file_with_content(ls_path, lancedb_service_content, overwrite_if_exists=False)

    rs_path = os.path.join(CORE_DIR, "rag_service.py")
    if not os.path.exists(rs_path):
        rag_service_content = """# core/rag_service.py (Creado por setup con lógica adaptada)
from . import config
from .lancedb_service import buscar_en_lancedb_web
from .file_operations import get_summary_content_by_original_filename
import time; import tiktoken; from groq import Groq
from typing import List, Dict, Optional, Tuple; import traceback

cliente_groq_rag = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None
if not cliente_groq_rag: print("ADVERTENCIA_RAG: Cliente Groq NO inicializado.")

solicitudes_en_minuto_actual_groq = 0
tokens_procesados_en_minuto_actual_groq = 0
inicio_minuto_actual_groq = time.time()

def obtener_conteo_tokens_tiktoken(texto: str, encoding_nombre: str = config.ENCODING_TIKTOKEN_GENERACION) -> int:
    try: return len(tiktoken.get_encoding(encoding_nombre).encode(texto))
    except: return len(texto.split())

def verificar_y_esperar_limites_groq(tokens_entrada_prompt: int):
    global solicitudes_en_minuto_actual_groq, tokens_procesados_en_minuto_actual_groq, inicio_minuto_actual_groq
    tiempo_actual = time.time()
    if tiempo_actual - inicio_minuto_actual_groq >= 60:
        print(f"INFO_RAG_LIMITS: Nuevo minuto API Groq. Reset (Sols: {solicitudes_en_minuto_actual_groq}, Tokens: {tokens_procesados_en_minuto_actual_groq})")
        solicitudes_en_minuto_actual_groq=0;tokens_procesados_en_minuto_actual_groq=0;inicio_minuto_actual_groq=tiempo_actual
    max_prompt_seguro = config.LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ * 0.85
    if tokens_entrada_prompt > max_prompt_seguro and (tokens_procesados_en_minuto_actual_groq > 0 or solicitudes_en_minuto_actual_groq > 0):
        espera = (60.1-(tiempo_actual-inicio_minuto_actual_groq));
        if espera > 0: print(f"  ADVERTENCIA_RAG_LIMITS: Prompt grande. Esperando {espera:.2f}s..."); time.sleep(espera); solicitudes_en_minuto_actual_groq=0;tokens_procesados_en_minuto_actual_groq=0;inicio_minuto_actual_groq=time.time()
    if solicitudes_en_minuto_actual_groq >= config.LIMITE_SOLICITUDES_POR_MINUTO_GROQ:
        espera = (60.1-(tiempo_actual-inicio_minuto_actual_groq));
        if espera > 0: print(f"INFO_RAG_LIMITS: RPM Límite. Esperando {espera:.2f}s..."); time.sleep(espera); solicitudes_en_minuto_actual_groq=0;tokens_procesados_en_minuto_actual_groq=0;inicio_minuto_actual_groq=time.time()
    proyectados = tokens_procesados_en_minuto_actual_groq + tokens_entrada_prompt + config.MAX_COMPLETION_TOKENS_GENERACION
    if proyectados > config.LIMITE_TOKENS_POR_MINUTO_PROCESADOS_GROQ:
        espera = (60.1-(tiempo_actual-inicio_minuto_actual_groq));
        if espera > 0: print(f"INFO_RAG_LIMITS: TPM Límite. Esperando {espera:.2f}s..."); time.sleep(espera); solicitudes_en_minuto_actual_groq=0;tokens_procesados_en_minuto_actual_groq=0;inicio_minuto_actual_groq=time.time()

def generar_respuesta_con_groq_directo(prompt_completo_para_llm: str) -> Tuple[Optional[str], int]:
    global solicitudes_en_minuto_actual_groq, tokens_procesados_en_minuto_actual_groq
    tokens_prompt = obtener_conteo_tokens_tiktoken(prompt_completo_para_llm)
    try: verificar_y_esperar_limites_groq(tokens_prompt)
    except ValueError as ve: return f"Error: Prompt demasiado grande ({tokens_prompt} tokens).", tokens_prompt
    for intento in range(config.MAX_API_REINTENTOS_GROQ):
        try:
            print(f"INFO_RAG_GROQ: Enviando a Groq (intento {intento+1}), tokens: {tokens_prompt}")
            stream = cliente_groq_rag.chat.completions.create(model=config.MODELO_GENERACION_GROQ, messages=[{"role": "user", "content": prompt_completo_para_llm}], temperature=config.TEMPERATURE_GENERACION, max_tokens=config.MAX_COMPLETION_TOKENS_GENERACION, stream=True)
            resp_completa = "".join(c.choices[0].delta.content or "" for c in stream)
            resp_limpia = resp_completa.strip()
            tokens_resp = obtener_conteo_tokens_tiktoken(resp_limpia) if resp_limpia else 0
            solicitudes_en_minuto_actual_groq+=1; tokens_procesados_en_minuto_actual_groq+=tokens_prompt+tokens_resp
            return resp_limpia if resp_limpia else "El modelo generó una respuesta vacía.", tokens_prompt
        except Exception as e:
            err_str=str(e).lower(); print(f"ERROR_RAG_GROQ (API intento {intento+1}): {e}")
            if "rate limit" in err_str or "429" in err_str or "413" in err_str:
                espera=60.1 if "429" in err_str else config.TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS*(intento+1); print(f" Rate limit. Esperando {espera:.1f}s..."); time.sleep(espera)
                if "429" in err_str or "413" in err_str: solicitudes_en_minuto_actual_groq=0;tokens_procesados_en_minuto_actual_groq=0;inicio_minuto_actual_groq=time.time()
            elif intento < config.MAX_API_REINTENTOS_GROQ-1: time.sleep(config.TIEMPO_ESPERA_REINTENTO_GROQ_SEGUNDOS)
            else: return f"Error persistente con API Groq: {str(e)}", tokens_prompt
    return "No se pudo obtener respuesta de Groq.", tokens_prompt

def generar_respuesta_rag_web(pregunta_usuario: str, fragmentos_contexto: List[Dict[str, any]]) -> Tuple[str | None, int, str]:
    if not cliente_groq_rag: return "Error: Cliente Groq no configurado.", 0, "Cliente Groq no configurado."
    if not fragmentos_contexto: return "No se proporcionaron fragmentos.", 0, "Sin contexto."
    contexto_str_parts = []
    archivos_ya_con_resumen = set()
    for frag in fragmentos_contexto:
        orig_fn = frag.get('nombre_archivo_original')
        if orig_fn and orig_fn not in archivos_ya_con_resumen:
            resumen = get_summary_content_by_original_filename(orig_fn)
            if resumen:
                try:
                    enc = tiktoken.get_encoding(config.ENCODING_TIKTOKEN_GENERACION); toks = enc.encode(resumen)
                    res_final = enc.decode(toks[:config.MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO]) if len(toks) > config.MAX_TOKENS_POR_RESUMEN_EN_CONTEXTO else resumen
                    contexto_str_parts.append("Resumen del documento '{}':\\n{}".format(orig_fn, res_final))
                    archivos_ya_con_resumen.add(orig_fn)
                except Exception as e: print(f"ERR_SUM_PROC_WEB: {orig_fn} {e}")
    if contexto_str_parts: contexto_str_parts.append("\\n--- Fragmentos Específicos ---")
    for i, frag in enumerate(fragmentos_contexto):
        txt = frag.get('texto','');
        try:
            enc=tiktoken.get_encoding(config.ENCODING_TIKTOKEN_GENERACION); toks=enc.encode(txt)
            txt_final = enc.decode(toks[:config.MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO]) if len(toks) > config.MAX_TOKENS_POR_FRAGMENTO_EN_CONTEXTO else txt
            contexto_str_parts.append("Fragmento {} (de '{}', ID: {}):\\n{}".format(i+1, frag.get('nombre_archivo_original','N/A'), frag.get('id','N/A'), txt_final))
        except Exception as e: print(f"ERR_FRAG_PROC_WEB: frag {i+1} {e}")
    contexto_completo_str = "\\n\\n".join(contexto_str_parts)
    prompt_sistema = ("Eres un asistente experto respondiendo sobre documentos del DOF de México. "
                      "Basa tu respuesta ESTRICTAMENTE en la información de los resúmenes y fragmentos provistos. "
                      "Si la info no está, di: 'La información específica no se encuentra en los documentos proporcionados.' "
                      "No inventes. Cita el archivo original si es relevante, ej: '(según archivo.txt)'.")
    prompt_final_para_llm = (prompt_sistema + "\\n\\nPREGUNTA DEL USUARIO:\\n" + pregunta_usuario + "\\n\\nCONTEXTO:\\n" + contexto_completo_str + "\\n\\nRESPUESTA:")
    respuesta_llm, tokens_prompt = generar_respuesta_con_groq_directo(prompt_final_para_llm)
    return respuesta_llm, tokens_prompt, prompt_final_para_llm

def realizar_rag_completo_web(pregunta_usuario: str) -> Tuple[str | None, List[Dict], str, int]:
    fragmentos = buscar_en_lancedb_web(pregunta_usuario, k=config.NUM_DOCUMENTOS_RELEVANTES_K_RAG)
    if not fragmentos: return "No se encontraron fragmentos relevantes en LanceDB.", [], "", 0
    respuesta_texto, tokens_del_prompt, prompt_completo_str = generar_respuesta_rag_web(pregunta_usuario, fragmentos)
    return respuesta_texto, fragmentos, prompt_completo_str, tokens_del_prompt
"""
        create_file_with_content(rs_path, rag_service_content, overwrite_if_exists=False)

    print("-" * 30 + "\n")

# --- 3. Crear Plantillas HTML ---
# ... (Sin cambios)
def setup_html_templates():
    print("--- Creando/Verificando Plantillas HTML ---")
    base_html_content = """
    <!DOCTYPE html> <html lang="es"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <title>{% block title %}Proyecto DOF RAG{% endblock %}</title> <link rel="stylesheet" href="{{ url_for('static_files', path='style.css') }}"> <style> body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"; margin: 0; padding: 0; background-color: #f0f2f5; color: #1c1e21; line-height: 1.5; } header { background-color: #1877f2; color: white; padding: 15px 25px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); } header h1 { margin: 0; font-size: 1.8em; } nav { background-color: #ffffff; border-bottom: 1px solid #dddfe2; padding: 10px 25px; margin-bottom: 20px; display: flex; gap: 20px; } nav a { color: #1877f2; text-decoration: none; font-weight: 600; padding: 8px 12px; border-radius: 6px; transition: background-color 0.2s; } nav a:hover, nav a.active { background-color: #e7f3ff; color: #1877f2; } .container { max-width: 1000px; margin: 20px auto; padding: 25px; background-color: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); } h2 { color: #1c1e21; font-size: 1.5em; margin-top:0; margin-bottom:15px; border-bottom: 1px solid #eee; padding-bottom:10px;} ul.file-list { list-style: none; padding: 0; } ul.file-list li { margin-bottom: 8px; padding: 10px; background-color: #f7f8fa; border: 1px solid #dddfe2; border-radius:6px;} ul.file-list li a { text-decoration: none; color: #056be1; font-weight: 500;} ul.file-list li a:hover { text-decoration: underline; } textarea, input[type="text"] { width: calc(100% - 22px); padding: 10px; margin-bottom: 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 1em; } button { background-color: #1877f2; color: white; padding: 10px 18px; border: none; border-radius: 6px; cursor: pointer; font-size: 1em; font-weight: 600; transition: background-color 0.2s; } button:hover { background-color: #166fe5; } pre { background-color: #f0f2f5; padding: 15px; border: 1px solid #dddfe2; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; max-height: 450px; overflow-y: auto; } .document-content { margin-top: 15px; } .result-box { margin-top: 20px; border: 1px solid #dddfe2; padding: 18px; background-color: #ffffff; border-radius: 6px;} .result-box h3, .result-box h4 { margin-top:0; color: #333; } .error { color: #d32f2f; font-weight: bold; padding: 12px; background-color: #ffebee; border: 1px solid #d32f2f; border-radius: 6px; margin-bottom:15px; } details > summary { cursor: pointer; font-weight: 500; color: #056be1; margin-bottom:8px;} .metadata { font-size: 0.85em; color: #606770; margin-bottom: 5px; } </style> </head> <body> <header><h1>Proyecto DOF RAG</h1></header> <nav> <a href="{{ url_for('home') }}" {% if request.url.path == url_for('home') %}class="active"{% endif %}>Inicio</a> <a href="{{ url_for('explore_documents_page') }}" {% if request.url.path == url_for('explore_documents_page') %}class="active"{% endif %}>Explorar Documentos</a> <a href="{{ url_for('lancedb_query_page') }}" {% if request.url.path == url_for('lancedb_query_page') %}class="active"{% endif %}>Consultar LanceDB</a> <a href="{{ url_for('rag_chat_page') }}" {% if request.url.path == url_for('rag_chat_page') %}class="active"{% endif %}>Chat RAG</a> </nav> <div class="container"> {% block content %}{% endblock %} </div> </body> </html>
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "base.html"), base_html_content, overwrite_if_exists=True)
    index_html_content = """
    {% extends "base.html" %} {% block title %}Inicio - DOF RAG{% endblock %} {% block content %} <h2>Bienvenido al Proyecto DOF Scraper y RAG</h2> <p>Utiliza la navegación superior para explorar las funcionalidades de este sistema local.</p> <p>Este sistema te permite:</p> <ul> <li><strong>Explorar Documentos:</strong> Ver la lista de documentos completos y resúmenes generados.</li> <li><strong>Consultar LanceDB:</strong> Realizar búsquedas por similitud semántica directamente en la base de datos vectorial.</li> <li><strong>Chat RAG:</strong> Hacer preguntas en lenguaje natural que serán respondidas utilizando la información de los documentos, combinando la recuperación de LanceDB con la generación de lenguaje de un modelo LLM (vía Groq).</li> </ul> <p>Asegúrate de que los servicios necesarios (como Ollama para embeddings, si lo usas localmente) estén en ejecución y que el archivo <code>.env</code> con <code>GROQ_API_KEY</code> esté configurado.</p> {% endblock %}
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "index.html"), index_html_content, overwrite_if_exists=False)
    explore_html_content = """
    {% extends "base.html" %} {% block title %}Explorar Documentos{% endblock %} {% block content %} <h2>Explorar Documentos y Resúmenes</h2> <h3>Documentos Completos (de carpeta: '{{ dir_full_name }}')</h3> {% if full_docs %} <ul class="file-list"> {% for doc in full_docs %} <li><a href="{{ url_for('view_document_page', type='full', filename=doc) }}">{{ doc }}</a></li> {% endfor %} </ul> {% else %} <p class="error">No se encontraron documentos completos en la carpeta '{{ dir_full_name }}'. Verifica la ruta en <code>core/config.py</code> (variable <code>DECRETOS_COLECTADOS_DIR</code>) y asegúrate de que los archivos <code>.txt</code> existan allí. </p> {% endif %} <h3>Resúmenes (de carpeta: '{{ dir_summaries_name }}')</h3> {% if summaries %} <ul class="file-list"> {% for summary_file in summaries %} <li><a href="{{ url_for('view_document_page', type='summary', filename=summary_file) }}">{{ summary_file }}</a></li> {% endfor %} </ul> {% else %} <p class="error">No se encontraron resúmenes en la carpeta '{{ dir_summaries_name }}'. Verifica la ruta en <code>core/config.py</code> (variable <code>RESUMENES_DIR</code>) y asegúrate de que los archivos <code>_resumen.txt</code> existan allí. </p> {% endif %} {% endblock %}
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "explore_documents.html"), explore_html_content, overwrite_if_exists=False)
    view_doc_html_content = """
    {% extends "base.html" %} {% block title %}Ver {{ doc_type_display }} - {{ filename }}{% endblock %} {% block content %} <h2>{{ doc_type_display }}: {{ filename }}</h2> <p><a href="{{ url_for('explore_documents_page') }}">« Volver a la lista de exploración</a></p> {% if content %} <div class="document-content"> <h3>Contenido del Archivo:</h3> <pre>{{ content }}</pre> </div> {% elif content is none and filename %} <p class="error">El archivo '{{ filename }}' fue encontrado, pero su contenido principal parece estar vacío o no se pudo leer. Verifica el archivo y la lógica de extracción de contenido.</p> {% else %} <p class="error">No se pudo cargar el contenido del documento '{{ filename }}'.</p> {% endif %} {% endblock %}
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "view_document.html"), view_doc_html_content, overwrite_if_exists=False)
    lancedb_query_html_content = """
    {% extends "base.html" %} {% block title %}Consultar LanceDB{% endblock %} {% block content %} <h2>Consultar Base de Datos LanceDB (Embeddings)</h2> <p>Ingresa una pregunta para buscar fragmentos similares en LanceDB (tabla: '<strong>{{ lancedb_table_name }}</strong>').</p> <form method="post"> <textarea name="query_text_lancedb" rows="3" placeholder="Escribe tu pregunta para LanceDB...">{{ query_text_lancedb if query_text_lancedb else '' }}</textarea><br> <button type="submit">Buscar en LanceDB</button> </form> {% if error_lancedb %} <p class="error">Error en LanceDB: {{ error_lancedb }}</p> {% endif %} {% if results_lancedb is defined %} <h3>Resultados ({{ results_lancedb|length }} fragmentos):</h3> {% if results_lancedb %} {% for result_item in results_lancedb %} <div class="result-box"> <h4>Fragmento {{ loop.index }}</h4> <p class="metadata"><strong>ID:</strong> {{ result_item.get('id', 'N/A') }}</p> <p class="metadata"><strong>Archivo Original:</strong> {{ result_item.get('nombre_archivo_original', 'N/A') }}</p> <p class="metadata"><strong>Distancia:</strong> {{ "%.4f"|format(result_item.get('_distance', -1.0)) }}</p> <pre>{{ result_item.get('texto', '')[:500] }}{% if result_item.get('texto', '')|length > 500 %}...{% endif %}</pre> </div> {% endfor %} {% elif query_text_lancedb %} <p>No se encontraron resultados.</p> {% endif %} {% endif %} {% endblock %}
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "lancedb_query.html"), lancedb_query_html_content, overwrite_if_exists=False)
    rag_chat_html_content = """
    {% extends "base.html" %} {% block title %}Chat RAG con Groq{% endblock %} {% block content %} <h2>Chat RAG (LanceDB + Groq)</h2> <p>Pregunta al sistema RAG (tabla '<strong>{{ lancedb_table_name }}</strong>', modelo Groq: <strong>{{ groq_model_name }}</strong>).</p> <form method="post"> <textarea name="query_text_rag" rows="4" placeholder="Escribe tu pregunta aquí...">{{ query_text_rag if query_text_rag else '' }}</textarea><br> <button type="submit">Enviar Pregunta RAG</button> </form> {% if error_rag %} <p class="error">Error RAG: {{ error_rag }}</p> {% endif %} {% if rag_response_text is defined and rag_response_text is not none %} <div class="result-box"> <h3>Respuesta del Asistente RAG:</h3> <pre>{{ rag_response_text }}</pre> </div> {% if prompt_sent_to_groq %} <div class="result-box"> <h4>Contexto Enviado a Groq (Depuración):</h4> <details> <summary>Mostrar/Ocultar Prompt (Tokens: {{ tokens_in_prompt_num }})</summary> <pre>{{ prompt_sent_to_groq }}</pre> </details> </div> {% endif %} {% if retrieved_fragments_list %} <div class="result-box"> <h4>Fragmentos Recuperados de LanceDB ({{ retrieved_fragments_list|length }}):</h4> {% for fragment_item in retrieved_fragments_list %} <div style="border-top: 1px solid #eee; padding-top:10px; margin-top:10px;"> <h5>Fragmento {{ loop.index }}</h5> <p class="metadata"><strong>ID:</strong> {{ fragment_item.get('id', 'N/A') }}</p> <p class="metadata"><strong>Archivo Original:</strong> {{ fragment_item.get('nombre_archivo_original', 'N/A') }}</p> <p class="metadata"><strong>Distancia:</strong> {{ "%.4f"|format(fragment_item.get('_distance', -1.0)) }}</p> <pre>{{ fragment_item.get('texto', '')[:300] }}{% if fragment_item.get('texto', '')|length > 300 %}...{% endif %}</pre> </div> {% endfor %} </div> {% endif %} {% elif query_text_rag and not error_rag %} <p>Procesando...</p> {% endif %} {% endblock %}
    """
    create_file_with_content(os.path.join(TEMPLATES_DIR, "rag_chat.html"), rag_chat_html_content, overwrite_if_exists=False)
    print("-" * 30 + "\n")

# --- 4. Crear Aplicación FastAPI `main.py` ---
# ... (Sin cambios)
def setup_main_app():
    print("--- Creando/Actualizando Aplicación FastAPI (main.py) ---")
    main_py_lines = [
        "# main.py (SOBRESCRITO POR SETUP)",
        "from fastapi import FastAPI, Request, Form",
        "from fastapi.responses import HTMLResponse",
        "from fastapi.staticfiles import StaticFiles",
        "from fastapi.templating import Jinja2Templates",
        "import os; import traceback",
        "from typing import List, Dict, Optional, Tuple",
        "",
        "try:",
        "    from core import config",
        "    from core.file_operations import get_full_documents_list, get_summaries_list, get_full_document_content, get_summary_content_by_summary_filename",
        "    from core.lancedb_service import buscar_en_lancedb_web",
        "    from core.rag_service import realizar_rag_completo_web",
        "except ImportError as ie:",
        "    print(\"ERROR_CRITICAL_IMPORTS_MAIN: Fallo al importar de 'core'. {}\\n{}\".format(ie, traceback.format_exc()))",
        "    raise",
        "",
        "app = FastAPI(title=\"Proyecto DOF RAG\", version=\"0.8.1\")",
        "MAIN_DIR = os.path.dirname(os.path.abspath(__file__))",
        "templates = Jinja2Templates(directory=os.path.join(MAIN_DIR, \"templates\"))",
        "app.mount(\"/static\", StaticFiles(directory=os.path.join(MAIN_DIR, \"static\")), name=\"static_files\")",
        "",
        "@app.get(\"/\", response_class=HTMLResponse, tags=[\"Interfaz\"])",
        "async def home(r: Request): return templates.TemplateResponse(\"index.html\", {\"request\": r})",
        "",
        "@app.get(\"/explore\", response_class=HTMLResponse, tags=[\"Interfaz\"])",
        "async def explore_documents_page(r: Request):",
        "    return templates.TemplateResponse(\"explore_documents.html\", {",
        "        \"request\": r, \"full_docs\": get_full_documents_list(), \"summaries\": get_summaries_list(),",
        "        \"dir_full_name\": config.DECRETOS_DIR_NAME, \"dir_summaries_name\": config.RESUMENES_DIR_NAME",
        "    })",
        "",
        "@app.get(\"/view/{type}/{filename}\", response_class=HTMLResponse, tags=[\"Interfaz\"])",
        "async def view_document_page(r: Request, type: str, filename: str):",
        "    ct, dt = (get_full_document_content(filename), \"Documento Completo\") if type==\"full\" else \\",
        "             (get_summary_content_by_summary_filename(filename), \"Resumen\") if type==\"summary\" else (None, \"Tipo Desconocido\")",
        "    return templates.TemplateResponse(\"view_document.html\", {\"request\": r, \"filename\": filename, \"content\": ct, \"doc_type_display\": dt})",
        "",
        "@app.get(\"/lancedb-query\", response_class=HTMLResponse, tags=[\"Funcionalidad\"])",
        "async def lancedb_query_page(r: Request):",
        "    return templates.TemplateResponse(\"lancedb_query.html\", {\"request\": r, \"lancedb_table_name\": config.LANCEDB_TABLE_NAME_DEFAULT})",
        "",
        "@app.post(\"/lancedb-query\", response_class=HTMLResponse, tags=[\"Funcionalidad\"])",
        "async def handle_lancedb_query(r: Request, query_text_lancedb: str = Form(...)):",
        "    res, err = [], None",
        "    try: res = buscar_en_lancedb_web(query_text_lancedb)",
        "    except Exception as e: err = str(e); print(\"ERR_LANCEDB_EP: {}\\n{}\".format(err, traceback.format_exc()))",
        "    return templates.TemplateResponse(\"lancedb_query.html\", {",
        "        \"request\": r, \"results_lancedb\": res, \"query_text_lancedb\": query_text_lancedb,",
        "        \"error_lancedb\": err, \"lancedb_table_name\": config.LANCEDB_TABLE_NAME_DEFAULT",
        "    })",
        "",
        "@app.get(\"/rag-chat\", response_class=HTMLResponse, tags=[\"Funcionalidad\"])",
        "async def rag_chat_page(r: Request):",
        "    return templates.TemplateResponse(\"rag_chat.html\", {",
        "        \"request\": r, \"lancedb_table_name\": config.LANCEDB_TABLE_NAME_DEFAULT,",
        "        \"groq_model_name\": config.MODELO_GENERACION_GROQ",
        "    })",
        "",
        "@app.post(\"/rag-chat\", response_class=HTMLResponse, tags=[\"Funcionalidad\"])",
        "async def handle_rag_chat(r: Request, query_text_rag: str = Form(...)):",
        "    resp, frags, prompt, toks, err = None, [], \"\", 0, None",
        "    if not config.GROQ_API_KEY: err = \"Error Crítico: GROQ_API_KEY no está configurada.\"",
        "    else:",
        "        try: resp, frags, prompt, toks = realizar_rag_completo_web(query_text_rag)",
        "        except Exception as e: err = str(e); print(\"ERR_RAG_EP: {}\\n{}\".format(err, traceback.format_exc()))",
        "    return templates.TemplateResponse(\"rag_chat.html\", {",
        "        \"request\": r, \"rag_response_text\": resp, \"retrieved_fragments_list\": frags,",
        "        \"prompt_sent_to_groq\": prompt, \"tokens_in_prompt_num\": toks,",
        "        \"query_text_rag\": query_text_rag, \"error_rag\": err,",
        "        \"lancedb_table_name\": config.LANCEDB_TABLE_NAME_DEFAULT,",
        "        \"groq_model_name\": config.MODELO_GENERACION_GROQ",
        "    })",
        "",
        "if __name__ == \"__main__\":",
        "    import uvicorn",
        "    project_root_for_msg = PROJECT_ROOT if \"PROJECT_ROOT\" in globals() and PROJECT_ROOT else os.getcwd()",
        "    print(\"INFO: Ejecuta 'uvicorn main:app --reload --host 127.0.0.1 --port 8000' desde {}\".format(project_root_for_msg))",
        "    uvicorn.run(\"main:app\", host=\"127.0.0.1\", port=8000, reload=True)"
    ]
    create_file_with_content(os.path.join(PROJECT_ROOT, "main.py"), "\n".join(main_py_lines), is_critical_structure_file=True)
    print("-" * 30 + "\n")


# --- Ejecutar el Setup ---
if __name__ == "__main__":
    print("=============================================================")
    print("  INICIANDO CONFIGURACIÓN AUTOMATIZADA DEL PROYECTO WEB DOF RAG  ")
    print("=============================================================")
    setup_directories()
    setup_core_module()
    setup_html_templates()
    setup_main_app()
    print("\n" + "=" * 60)
    print("  ¡CONFIGURACIÓN AUTOMATIZADA COMPLETADA!  ")
    print("=" * 60)
    # --- INSTRUCCIONES DETALLADAS ---
    # (Las instrucciones finales son las mismas que en la respuesta anterior, usando .format())
    instructions = [
        "\n  PASO 1: PREPARACIÓN DEL ENTORNO (Realizar una sola vez)",
        "  " + "-" * 46,
        "  A. ARCHIVO `.env`:",
        "     Crea un archivo `.env` en la raíz del proyecto (`{}/`) con:".format(PROJECT_ROOT),
        "     `GROQ_API_KEY=tu_gsk_api_key_aqui`",
        "\n  B. DEPENDENCIAS:",
        "     En tu terminal (con entorno Conda activado):",
        "     `pip install fastapi uvicorn jinja2 python-dotenv tiktoken groq lancedb ollama numpy python-multipart`",

        "\n  PASO 2: VERIFICACIÓN DEL CÓDIGO GENERADO EN `core/`",
        "  " + "-" * 59,
        "  El script ha generado implementaciones más completas en `core/`. Revisa para entenderlas:",
        "\n  A. `core/config.py`:",
        "     - Verifica que `GROQ_API_KEY` se lea de tu `.env`.",
        "     - Confirma que `LANCEDB_TABLE_NAME_DEFAULT` es `'{LANCEDB_TABLE_NAME_FIXED}'`.".format(LANCEDB_TABLE_NAME_FIXED=LANCEDB_TABLE_NAME_FIXED),
        "     - Las rutas a las carpetas de datos usan nombres fijos. Verifica que existan.",

        "\n  B. `core/lancedb_service.py` y `core/rag_service.py`:",
        "     - Estas funciones AHORA están implementadas directamente por el script de setup.",
        "     - Revisa la lógica interna si encuentras comportamientos inesperados, especialmente",
        "       en `verificar_y_esperar_limites_groq` y `generar_respuesta_con_groq_directo` dentro de `core/rag_service.py`.",
        "       El objetivo es que funcionen directamente, pero la lógica de rate limiting y llamadas a API",
        "       puede necesitar ajustes finos basados en los límites reales de tu cuenta Groq y el comportamiento del modelo.",

        "\n  PASO 3: EJECUTAR LA APLICACIÓN WEB",
        "  " + "-" * 35,
        "  A. Activa tu entorno Conda.",
        "  B. Navega a la raíz del proyecto: `cd \"{}\"`".format(PROJECT_ROOT),
        "  C. Ejecuta Uvicorn:",
        "     `uvicorn main:app --reload --host 127.0.0.1 --port 8000`",

        "\n  PASO 4: PROBAR Y DEPURAR",
        "  " + "-" * 26,
        "  A. Abre tu navegador web y ve a `http://127.0.0.1:8000`.",
        "  B. Prueba todas las secciones, especialmente el Chat RAG.",
        "  C. OBSERVA LA CONSOLA de `uvicorn` para logs y errores.",
        "  D. Si hay errores, revisa la lógica en `core/` o los mensajes de error para pistas.",
        "\n  Con esta versión, la necesidad de adaptación manual post-setup debería ser mínima para el flujo principal.",
        "  El foco principal es asegurar que `config.py` y `.env` estén correctos y que Ollama esté disponible si lo usas.",
        "=" * 60
    ]
    print("\n".join(instructions))