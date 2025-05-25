import os
import csv
import re
import tiktoken # <--- IMPORTACIÓN DE TIKTOKEN

# === INICIO DE FUNCIÓN FALTANTE ===
def sanitizar_nombre(nombre: str, es_carpeta=False) -> str:
    """
    Sanitiza una cadena para que sea un nombre de archivo/carpeta válido.
    """
    nombre = nombre.lower()
    nombre = re.sub(r'\s+', '_', nombre)
    if es_carpeta:
        nombre = re.sub(r'[^\w-]', '', nombre) # Para carpetas, solo alfanuméricos y guiones
    else:
        nombre = re.sub(r'[^\w.-]', '', nombre) # Para archivos, permitir puntos
    # Truncar si es demasiado largo (opcional)
    nombre = nombre[:150] # Limitar longitud para evitar problemas con el sistema de archivos
    if not nombre: # Si después de sanitizar queda vacío
        # Para carpetas, usamos un nombre genérico si el original se vuelve vacío
        if es_carpeta:
            return "documentos_sin_nombre_busqueda"
        return "documento_sin_titulo"
    return nombre
# === FIN DE FUNCIÓN FALTANTE ===

def limpiar_nombre_para_documento(nombre_archivo_txt: str) -> str:
    """
    Convierte un nombre de archivo sanitizado de nuevo a una forma más legible
    para el 'nombre del documento' en el CSV.
    """
    nombre_sin_extension = nombre_archivo_txt.rsplit('.txt', 1)[0]
    nombre_legible = nombre_sin_extension.replace('_', ' ')
    nombre_legible = ' '.join(word.capitalize() for word in nombre_legible.split())
    return nombre_legible

def contar_tokens_openai(texto: str, modelo_encoding: str = "cl100k_base") -> int:
    """
    Cuenta los tokens en un texto usando el codificador de tiktoken para un modelo OpenAI.
    "cl100k_base" es el encoding usado por gpt-4, gpt-3.5-turbo, text-embedding-ada-002.
    """
    try:
        encoding = tiktoken.get_encoding(modelo_encoding)
        tokens = encoding.encode(texto)
        return len(tokens)
    except Exception as e:
        print(f"Error al tokenizar con tiktoken (modelo {modelo_encoding}): {e}")
        return 0

def contar_tokens_en_archivo_openai(ruta_archivo_txt: str, modelo_encoding: str = "cl100k_base") -> int:
    """
    Lee el contenido de un archivo .txt, extrae la sección principal
    y cuenta los tokens usando tiktoken.
    """
    try:
        with open(ruta_archivo_txt, 'r', encoding='utf-8') as f:
            lineas = f.readlines()
        
        contenido_principal = []
        capturando_contenido = False
        for linea in lineas:
            if "-------------------- CONTENIDO --------------------" in linea:
                capturando_contenido = True
                continue 
            if capturando_contenido:
                contenido_principal.append(linea)
        
        texto_completo = "".join(contenido_principal).strip()
        
        if not texto_completo:
            return 0
            
        return contar_tokens_openai(texto_completo, modelo_encoding)
        
    except Exception as e:
        print(f"Error leyendo o procesando el archivo {ruta_archivo_txt}: {e}")
        return 0

def generar_csv_conteo_tokens_openai(carpeta_textos: str, archivo_csv_salida: str, modelo_encoding: str = "cl100k_base"):
    """
    Recorre una carpeta de archivos .txt, cuenta tokens con tiktoken y genera un CSV.
    """
    if not os.path.isdir(carpeta_textos):
        print(f"Error: La carpeta de textos '{carpeta_textos}' no existe.")
        return

    datos_tokens = []
    print(f"Procesando archivos en la carpeta: {carpeta_textos}")
    print(f"Usando encoding de tiktoken para modelos tipo: '{modelo_encoding}'")

    for nombre_archivo in os.listdir(carpeta_textos):
        if nombre_archivo.endswith(".txt"):
            ruta_completa_archivo = os.path.join(carpeta_textos, nombre_archivo)
            print(f"  Procesando archivo: {nombre_archivo}...")
            
            nombre_documento = limpiar_nombre_para_documento(nombre_archivo)
            cantidad_tokens = contar_tokens_en_archivo_openai(ruta_completa_archivo, modelo_encoding)
            
            if cantidad_tokens > 0 :
                datos_tokens.append({"nombre_documento": nombre_documento, "cantidad_tokens_openai": cantidad_tokens})
                print(f"    Nombre Documento: {nombre_documento}, Tokens (OpenAI {modelo_encoding}): {cantidad_tokens}")
            else:
                 print(f"    No se pudieron contar tokens (OpenAI) o el contenido estaba vacío para: {nombre_documento}")

    if not datos_tokens:
        print("No se procesaron datos de tokens para generar el CSV.")
        return

    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    ruta_csv_completa = os.path.join(script_dir, archivo_csv_salida)
    try:
        with open(ruta_csv_completa, mode='w', newline='', encoding='utf-8') as f_csv:
            campos = ["nombre_documento", "cantidad_tokens_openai"] 
            escritor_csv = csv.DictWriter(f_csv, fieldnames=campos)
            escritor_csv.writeheader()
            escritor_csv.writerows(datos_tokens)
        print(f"\nArchivo CSV con conteo de tokens (OpenAI) guardado en: {ruta_csv_completa}")
    except Exception as e:
        print(f"Error al escribir el archivo CSV '{ruta_csv_completa}': {e}")


if __name__ == "__main__":
    termino_busqueda_usado_para_carpeta = "decreto" 
    
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    # Usar la función sanitizar_nombre aquí
    nombre_carpeta_contenedora = sanitizar_nombre(termino_busqueda_usado_para_carpeta, es_carpeta=True) + "_colectados"
    ruta_carpeta_documentos = os.path.join(script_dir, nombre_carpeta_contenedora)
    
    encoding_modelo_openai = "cl100k_base"
    nombre_archivo_csv_salida = f"conteo_tokens_openai_{sanitizar_nombre(termino_busqueda_usado_para_carpeta, es_carpeta=True)}_{encoding_modelo_openai}.csv"

    print(f"Iniciando conteo de tokens (OpenAI) para documentos en: {ruta_carpeta_documentos}")
    generar_csv_conteo_tokens_openai(ruta_carpeta_documentos, nombre_archivo_csv_salida, encoding_modelo_openai)
    print("Script de conteo de tokens (OpenAI) finalizado.")