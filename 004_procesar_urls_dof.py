import csv
import os
import re # Para sanitizar nombres de archivo/carpeta
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
from typing import List, Dict, Optional
import time
import random # <--- IMPORTACIÓN PARA RETARDO ALEATORIO

# --- Constantes y Selectores ---
# Selector para el contenido principal en la página de detalle de la nota
SELECTOR_CONTENIDO_NOTA = "div#DivDetalleNota"
# Rango para el retardo aleatorio en segundos
MIN_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 3.0

def sanitizar_nombre(nombre: str, es_carpeta=False) -> str:
    """
    Sanitiza una cadena para que sea un nombre de archivo/carpeta válido.
    """
    nombre = nombre.lower()
    nombre = re.sub(r'\s+', '_', nombre)
    if es_carpeta:
        nombre = re.sub(r'[^\w-]', '', nombre)
    else:
        nombre = re.sub(r'[^\w.-]', '', nombre)
    nombre = nombre[:150]
    if not nombre:
        return "documento_sin_titulo"
    return nombre

def extraer_contenido_de_nota(page: Page, url: str) -> Optional[str]:
    """
    Visita una URL de nota y extrae el contenido textual principal.
    """
    print(f"  Visitando URL: {url}")
    try:
        page.goto(url, timeout=60000, wait_until='domcontentloaded')
        
        contenido_elemento = page.locator(SELECTOR_CONTENIDO_NOTA)
        if not contenido_elemento.is_visible(timeout=20000):
            print(f"  ERROR: El contenedor principal '{SELECTOR_CONTENIDO_NOTA}' no se encontró o no está visible en {url}")
            base_path_error = os.path.dirname(__file__) if "__file__" in locals() else "."
            error_filename_base = sanitizar_nombre(url.split("codigo=")[-1].split("&")[0] if "codigo=" in url else url.split("/")[-1])
            
            html_content_error = page.content()
            with open(os.path.join(base_path_error, f"error_contenido_{error_filename_base}.html"), "w", encoding="utf-8") as f:
                f.write(html_content_error)
            page.screenshot(path=os.path.join(base_path_error, f"screenshot_error_contenido_{error_filename_base}.png"), full_page=True)
            print(f"  HTML y Screenshot guardados para URL con error de contenido: {url}")
            return None

        texto_nota = contenido_elemento.inner_text()
        texto_nota = re.sub(r'\s\s+', ' ', texto_nota) 
        texto_nota = texto_nota.strip()
        
        print(f"  Contenido extraído (primeros 200 chars): {texto_nota[:200]}...")
        return texto_nota

    except PlaywrightTimeoutError:
        print(f"  TIMEOUT al intentar cargar o encontrar contenido en: {url}")
    except Exception as e:
        print(f"  Error al procesar URL {url}: {e}")
    return None


def procesar_urls_y_guardar_contenido(archivo_csv_entrada: str, termino_busqueda_original: str):
    """
    Lee URLs de un CSV, visita cada una, extrae contenido y lo guarda en archivos de texto,
    con un retardo aleatorio entre solicitudes.
    """
    nombre_carpeta_base = sanitizar_nombre(termino_busqueda_original, es_carpeta=True) + "_colectados"
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    ruta_carpeta_base = os.path.join(script_dir, nombre_carpeta_base)
    
    if not os.path.exists(ruta_carpeta_base):
        os.makedirs(ruta_carpeta_base)
        print(f"Carpeta creada: {ruta_carpeta_base}")
    else:
        print(f"La carpeta ya existe: {ruta_carpeta_base}")

    archivo_csv_completo = os.path.join(script_dir, archivo_csv_entrada)
    if not os.path.exists(archivo_csv_completo):
        print(f"Error: El archivo CSV de entrada '{archivo_csv_completo}' no fue encontrado.")
        return

    enlaces_a_procesar: List[Dict[str, str]] = []
    with open(archivo_csv_completo, mode='r', newline='', encoding='utf-8') as f_csv:
        lector_csv = csv.DictReader(f_csv)
        for fila in lector_csv:
            enlaces_a_procesar.append(fila)
    
    if not enlaces_a_procesar:
        print("No se encontraron URLs en el archivo CSV para procesar.")
        return
    
    print(f"Se procesarán {len(enlaces_a_procesar)} URLs desde '{archivo_csv_entrada}'.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(
             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        print("Navegador iniciado para procesar URLs.")

        archivos_guardados_count = 0
        for i, enlace_info in enumerate(enlaces_a_procesar):
            print(f"\nProcesando URL {i+1}/{len(enlaces_a_procesar)}...")
            url_nota = enlace_info.get("url")
            texto_titulo_original = enlace_info.get("texto", "documento_desconocido")

            if not url_nota:
                print(f"  Advertencia: Fila {i+1} en CSV no tiene URL. Saltando.")
                # Aplicar retardo incluso si se salta para mantener un ritmo
                if i + 1 < len(enlaces_a_procesar): # No esperar después del último ítem
                    tiempo_espera = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                    print(f"  Esperando {tiempo_espera:.2f} segundos antes de la siguiente URL...")
                    time.sleep(tiempo_espera)
                continue

            contenido_texto = extraer_contenido_de_nota(page, url_nota)

            if contenido_texto:
                nombre_archivo_txt = sanitizar_nombre(texto_titulo_original) + ".txt"
                ruta_archivo_txt = os.path.join(ruta_carpeta_base, nombre_archivo_txt)

                try:
                    with open(ruta_archivo_txt, "w", encoding="utf-8") as f_txt:
                        f_txt.write(f"URL: {url_nota}\n")
                        f_txt.write(f"TÍTULO ORIGINAL: {texto_titulo_original}\n\n")
                        f_txt.write("-------------------- CONTENIDO --------------------\n\n")
                        f_txt.write(contenido_texto)
                    print(f"  Contenido guardado en: {ruta_archivo_txt}")
                    archivos_guardados_count += 1
                except Exception as e_write:
                    print(f"  Error al escribir el archivo {ruta_archivo_txt}: {e_write}")
            
            # Aplicar retardo aleatorio ANTES de la siguiente solicitud,
            # pero no después de procesar el último ítem.
            if i + 1 < len(enlaces_a_procesar):
                tiempo_espera = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                print(f"  Esperando {tiempo_espera:.2f} segundos antes de la siguiente URL...")
                time.sleep(tiempo_espera)

        browser.close()
        print(f"\nProcesamiento de URLs finalizado. Se guardaron {archivos_guardados_count} archivos.")


if __name__ == "__main__":
    # Este script asume que el CSV del script anterior ya existe.
    archivo_csv_con_urls = "resultados_dof_paginado.csv" 
    termino_busqueda_usado = "decreto" 

    # Obtener la ruta del directorio donde se encuentra el script actual
    script_dir = os.path.dirname(__file__) if "__file__" in locals() else "."
    ruta_csv_completa = os.path.join(script_dir, archivo_csv_con_urls)


    if not os.path.exists(ruta_csv_completa):
        print(f"Error: El archivo '{ruta_csv_completa}' no existe. Ejecuta primero el script de recolección de URLs.")
    else:
        print(f"Iniciando script para procesar URLs desde '{ruta_csv_completa}' para la búsqueda '{termino_busqueda_usado}'.")
        procesar_urls_y_guardar_contenido(archivo_csv_con_urls, termino_busqueda_usado) # Pasamos solo el nombre del archivo, la función le antepone la ruta
        print("Script de procesamiento de contenido finalizado.")