import csv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError
import os
import time
from urllib.parse import urljoin
from typing import List, Dict, Optional

# --- Constantes y Configuración ---
BASE_URL = "https://www.dof.gob.mx/"
CAMPO_BUSQUEDA_SELECTOR = "input#textobusqueda"

# SELECTOR DEL BOTÓN/ENLACE "SIGUIENTE PÁGINA" ACTUALIZADO BASADO EN EL HTML PROPORCIONADO
SELECTOR_SIGUIENTE_PAGINA = 'a:has(img[alt="siguiente"])'
# Alternativamente, podrías usar:
# SELECTOR_SIGUIENTE_PAGINA = 'a.txt_azul:has(img[alt="siguiente"])' # Si necesitas ser más específico con la clase del <a>
# SELECTOR_SIGUIENTE_PAGINA = 'img[alt="siguiente"]' # Si Playwright maneja bien el clic en la imagen para activar el <a> padre

AVISO_SELECTOR_TEXTO = "text=Su solicitud no pudo ser procesada correctamente"
SELECTOR_RESULTADOS_PRINCIPALES = 'a[href*="nota_detalle.php"]'


def extraer_enlaces_de_pagina(page: Page) -> List[Dict[str, str]]:
    """Extrae los enlaces y textos de la página de resultados actual."""
    enlaces_extraidos_pagina = []
    print(f"URL actual para extracción: {page.url}")
    print(f"Intentando encontrar elementos con selector: {SELECTOR_RESULTADOS_PRINCIPALES}")
    
    try:
        page.wait_for_selector(f"{SELECTOR_RESULTADOS_PRINCIPALES}:visible", timeout=20000)
        print("Primer elemento de resultado principal visible.")
    except PlaywrightTimeoutError:
        print(f"TIMEOUT: No se encontró ningún enlace de resultado principal visible con el selector '{SELECTOR_RESULTADOS_PRINCIPALES}' en la página actual.")
        return []

    enlaces_elementos = page.query_selector_all(SELECTOR_RESULTADOS_PRINCIPALES)
    
    if not enlaces_elementos:
        print("No se encontraron elementos que coincidan con el selector de resultados principales en esta página.")
    else:
        print(f"Se encontraron {len(enlaces_elementos)} elementos para resultados principales en esta página.")
        current_page_url = page.url
        for i, elemento_enlace in enumerate(enlaces_elementos):
            href = elemento_enlace.get_attribute("href")
            texto_enlace = elemento_enlace.inner_text().strip().replace('\n', ' ').replace('\r', ' ')
            if href and texto_enlace:
                enlace_absoluto = urljoin(current_page_url, href)
                enlaces_extraidos_pagina.append({"texto": texto_enlace, "url": enlace_absoluto})
            else:
                pass
    return enlaces_extraidos_pagina


def buscar_en_dof_con_paginacion(termino_busqueda: str, nombre_archivo_csv: str, max_urls_a_recolectar: int):
    todos_los_enlaces_recolectados: List[Dict[str, str]] = []
    urls_ya_vistas = set()

    with sync_playwright() as p:
        print("Lanzando el navegador Chromium...")
        browser = None
        page = None
        try:
            browser = p.chromium.launch(headless=True) # Cambia a False para depurar visualmente
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
            )
            page = context.new_page()
            print("Navegador y página creados.")
        except Exception as e:
            print(f"Error al lanzar el navegador: {e}")
            return

        try:
            print(f"Navegando a {BASE_URL}...")
            page.goto(BASE_URL, timeout=60000)
            print("Página del DOF cargada.")

            print(f"Ingresando '{termino_busqueda}' en el campo de búsqueda...")
            page.wait_for_selector(CAMPO_BUSQUEDA_SELECTOR, state="visible", timeout=30000)
            page.fill(CAMPO_BUSQUEDA_SELECTOR, termino_busqueda)
            print(f"Término '{termino_busqueda}' ingresado.")

            print("Realizando la búsqueda inicial...")
            page.press(CAMPO_BUSQUEDA_SELECTOR, "Enter")
            print("Búsqueda enviada. Esperando navegación...")
            try:
                page.wait_for_load_state('domcontentloaded', timeout=45000)
                print(f"Navegación inicial completada. URL actual: {page.url}")
            except PlaywrightTimeoutError:
                print("Timeout esperando carga después de la búsqueda inicial.")
            
            pagina_actual = 1
            while len(todos_los_enlaces_recolectados) < max_urls_a_recolectar:
                print(f"\n--- Procesando página {pagina_actual} (URL: {page.url}) ---")

                es_pagina_de_aviso = False
                try:
                    # Usamos locator para verificar existencia sin esperar demasiado si no está
                    if page.locator(AVISO_SELECTOR_TEXTO).is_visible(timeout=5000): # Chequeo rápido
                        es_pagina_de_aviso = True
                        print("¡ALERTA! Se detectó la página de 'ATENTO AVISO'.")
                        # Guardar HTML para depuración
                        aviso_html_path = os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "pagina_atento_aviso_en_paginacion.html")
                        with open(aviso_html_path, "w", encoding="utf-8") as f:
                            f.write(page.content())
                        print(f"HTML de la página de aviso guardado en: {aviso_html_path}")
                except Exception: # Si is_visible da timeout u otro error, asumimos que no es la página de aviso
                    es_pagina_de_aviso = False
                
                if es_pagina_de_aviso:
                    print("Terminando debido a página de 'ATENTO AVISO'.")
                    break

                enlaces_esta_pagina = extraer_enlaces_de_pagina(page)

                if not enlaces_esta_pagina and pagina_actual > 1 :
                    print("No se encontraron más enlaces en esta página. Asumiendo fin de resultados.")
                    break
                
                if not enlaces_esta_pagina and pagina_actual == 1:
                    print("La primera página de búsqueda no arrojó resultados con el selector esperado.")
                    # Guardar HTML y screenshot para diagnóstico
                    page_content_no_results_p1 = page.content()
                    no_results_html_path_p1 = os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "pagina1_sin_resultados.html")
                    with open(no_results_html_path_p1, "w", encoding="utf-8") as f:
                        f.write(page_content_no_results_p1)
                    print(f"HTML de la página 1 sin resultados guardado en: {no_results_html_path_p1}")
                    page.screenshot(path=os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "screenshot_pagina1_sin_resultados.png"), full_page=True)
                    break # Salir si la primera página no da nada.


                nuevos_enlaces_agregados_count = 0
                for enlace_info in enlaces_esta_pagina:
                    if enlace_info["url"] not in urls_ya_vistas:
                        if len(todos_los_enlaces_recolectados) < max_urls_a_recolectar:
                            todos_los_enlaces_recolectados.append(enlace_info)
                            urls_ya_vistas.add(enlace_info["url"])
                            nuevos_enlaces_agregados_count +=1
                        else:
                            break 
                
                print(f"Se agregaron {nuevos_enlaces_agregados_count} nuevos enlaces de esta página.")
                print(f"Total de enlaces recolectados hasta ahora: {len(todos_los_enlaces_recolectados)}")

                if len(todos_los_enlaces_recolectados) >= max_urls_a_recolectar:
                    print(f"Se alcanzó el máximo de {max_urls_a_recolectar} URLs a recolectar.")
                    break

                print(f"Buscando el botón/enlace de 'Siguiente Página' con selector: '{SELECTOR_SIGUIENTE_PAGINA}'")
                siguiente_pagina_locator = page.locator(SELECTOR_SIGUIENTE_PAGINA)
                
                try:
                    if siguiente_pagina_locator.is_visible(timeout=10000): # Espera hasta 10s
                        if siguiente_pagina_locator.is_enabled(timeout=1000): # Espera hasta 1s para que esté habilitado
                            print("Botón/enlace 'Siguiente Página' encontrado y clickeable. Haciendo clic...")
                            siguiente_pagina_locator.click()
                            # Esperar a que la nueva página o el contenido se actualice.
                            # 'domcontentloaded' es una buena opción general.
                            # 'networkidle' podría ser demasiado largo si hay scripts de fondo.
                            page.wait_for_load_state('domcontentloaded', timeout=30000)
                            print(f"Navegado a la siguiente página (o contenido actualizado).")
                            pagina_actual += 1
                            time.sleep(1) # Pequeña pausa cortés
                        else:
                            print("Botón/enlace 'Siguiente Página' encontrado pero no está habilitado (podría ser la última página).")
                            break
                    else:
                        print("Botón/enlace 'Siguiente Página' no encontrado o no visible. Fin de la paginación.")
                        break
                except PlaywrightTimeoutError:
                    print("Timeout buscando/verificando el botón/enlace de 'Siguiente Página'. Asumiendo fin de la paginación.")
                    break
                except Exception as e_click_siguiente:
                    print(f"Error al intentar hacer clic en 'Siguiente Página': {e_click_siguiente}. Fin de la paginación.")
                    # Guardar HTML y screenshot de esta situación
                    error_html_paginacion = os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "error_paginacion.html")
                    with open(error_html_paginacion, "w", encoding="utf-8") as f:
                        f.write(page.content())
                    page.screenshot(path=os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "screenshot_error_paginacion.png"), full_page=True)
                    print(f"HTML y Screenshot guardados para el error de paginación.")
                    break
            # Fin del bucle while
        except PlaywrightTimeoutError as e_timeout:
            print(f"Ocurrió un TIMEOUT general: {e_timeout}")
            # ...
        except Exception as e:
            print(f"Ocurrió un error INESPERADO: {e}")
            # ...
        finally:
            if todos_los_enlaces_recolectados:
                base_path = os.path.dirname(__file__) if "__file__" in locals() else "."
                ruta_archivo_csv = os.path.join(base_path, nombre_archivo_csv)
                print(f"\nGuardando {len(todos_los_enlaces_recolectados)} enlaces totales en '{ruta_archivo_csv}'...")
                with open(ruta_archivo_csv, mode='w', newline='', encoding='utf-8') as archivo_csv:
                    escritor_csv = csv.DictWriter(archivo_csv, fieldnames=["texto", "url"])
                    escritor_csv.writeheader()
                    escritor_csv.writerows(todos_los_enlaces_recolectados)
                print(f"Enlaces guardados exitosamente en '{ruta_archivo_csv}'.")
            else:
                print("No se recolectaron enlaces para guardar en CSV.")

            if browser and browser.is_connected():
                browser.close()
                print("Navegador cerrado.")

if __name__ == "__main__":
    termino_busqueda_main = "decreto" 
    nombre_archivo_main = "resultados_dof_paginado.csv"
    max_urls_main = 50 

    print(f"Iniciando script para buscar en DOF: '{termino_busqueda_main}', recolectando hasta {max_urls_main} URLs.")
    buscar_en_dof_con_paginacion(termino_busqueda_main, nombre_archivo_main, max_urls_main)
    print("Script de scraping del DOF con paginación finalizado.")