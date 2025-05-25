import csv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import os
import time
from urllib.parse import urljoin

def buscar_en_dof_y_extraer_enlaces_local(termino_busqueda: str, nombre_archivo_csv: str):
    with sync_playwright() as p:
        print("Lanzando el navegador Chromium...")
        browser = None
        page = None
        try:
            browser = p.chromium.launch(headless=True) # Cambia a False para depurar visualmente
            page = browser.new_page()
            print("Navegador y página creados.")
        except Exception as e:
            print(f"Error al lanzar el navegador: {e}")
            return

        try:
            print(f"Navegando a https://www.dof.gob.mx/...")
            page.goto("https://www.dof.gob.mx/", timeout=60000)
            print("Página del DOF cargada.")

            print(f"Ingresando '{termino_busqueda}' en el campo de búsqueda...")
            campo_busqueda_selector = "input#textobusqueda"
            page.wait_for_selector(campo_busqueda_selector, state="visible", timeout=30000)
            page.fill(campo_busqueda_selector, termino_busqueda)
            print(f"Término '{termino_busqueda}' ingresado.")

            print("Realizando la búsqueda...")
            # Es importante esperar la navegación después de enviar el formulario.
            # page.press puede no esperar a que la nueva página cargue completamente.
            # Usaremos page.click en un botón de submit si es posible, o page.press y luego una espera explícita de navegación.
            
            # Intenta encontrar el botón de submit real del formulario de búsqueda.
            # Por el HTML que vi antes, hay un <input type='submit'> sin un ID claro,
            # pero está dentro del div id="buscar" y form action="busqueda_detalle.php"
            # Una forma más robusta podría ser page.locator('form[action="busqueda_detalle.php"] input[type="submit"]').click()
            # o el que tiene el value='' y el background-image.
            # Por ahora, seguiremos con page.press y luego verificaremos.

            page.press(campo_busqueda_selector, "Enter")
            print("Búsqueda enviada. Esperando navegación...")

            # Esperar a que la página cargue después del submit.
            # waitForLoadState('domcontentloaded') o 'networkidle' pueden ser útiles.
            try:
                page.wait_for_load_state('networkidle', timeout=30000) # Espera a que la red esté inactiva
                print(f"Navegación completada. URL actual: {page.url}")
            except PlaywrightTimeoutError:
                print("Timeout esperando que la red se calme después de la búsqueda. Continuando de todas formas...")
            except Exception as e_nav:
                print(f"Error durante la espera de navegación post-búsqueda: {e_nav}. Continuando...")


            # ---- NUEVA VERIFICACIÓN: Detectar la página de "ATENTO AVISO" ----
            aviso_selector_texto = "text=Su solicitud no pudo ser procesada correctamente"
            # También podrías usar un selector CSS más específico si el texto cambia
            # aviso_selector_css = "td.txt_blanco:has-text('ATENTO AVISO')"
            
            # Damos un tiempo corto para que aparezca el aviso si es que va a aparecer
            es_pagina_de_aviso = False
            try:
                page.wait_for_selector(aviso_selector_texto, timeout=10000) # 10 segundos para que aparezca el aviso
                es_pagina_de_aviso = True
                print("¡ALERTA! Se detectó la página de 'ATENTO AVISO'.")
                print("El texto de búsqueda podría ser inválido o hubo un problema con la solicitud.")
                # Guardar el HTML de esta página de aviso para análisis
                aviso_html_path = os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "pagina_atento_aviso.html")
                with open(aviso_html_path, "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(f"HTML de la página de aviso guardado en: {aviso_html_path}")
                
            except PlaywrightTimeoutError:
                print("No se detectó la página de 'ATENTO AVISO'. Se asume que son resultados válidos (o una página diferente).")
                es_pagina_de_aviso = False
            except Exception as e_aviso_check:
                print(f"Error inesperado al verificar la página de aviso: {e_aviso_check}")
                es_pagina_de_aviso = False # Asumir que no es para no detener el script innecesariamente


            if es_pagina_de_aviso:
                print("Terminando el script debido a la página de 'ATENTO AVISO'. No se extraerán enlaces.")
                # No hacemos nada más, el finally se encargará de cerrar el navegador.
                return # Salimos de la función aquí

            # ---- FIN DE NUEVA VERIFICACIÓN ----


            # Si NO es la página de aviso, procedemos a buscar los resultados REALES
            print("Esperando a que carguen los resultados de la búsqueda (en la página de resultados real)...")
            
            # ESTE ES EL SELECTOR CLAVE PARA LOS RESULTADOS REALES.
            # Basado en la imagen de la página de resultados que SÍ funcionó manualmente:
            # Los enlaces están dentro de `<a>` y parece que están precedidos por un `<img>` con `alt="Ver detalle de nota"`
            # o son simplemente `<a>` con una clase o estructura distintiva DENTRO de la tabla de resultados.
            # El selector 'a.enlaces' podría ser demasiado genérico si la página de "ATENTO AVISO" también lo usa.
            #
            # Inspeccionando tu imagen de "RESULTADO DE BÚSQUEDA" (la que SÍ tiene resultados):
            # Los enlaces de los resultados parecen ser el texto descriptivo de cada acuerdo.
            # Estos enlaces están dentro de una estructura repetitiva.
            # Vamos a intentar un selector más específico para la página de resultados.
            # Por ejemplo, si cada resultado está en un `div` o `tr` y el enlace es un `<a>` dentro:
            #
            # Un selector común para estos enlaces de título en el DOF es:
            # `td[valign="top"] > a[href*="nota_detalle.php"]` (Enlaces que contienen nota_detalle.php)
            # o `a.ligaTitulo` si tuvieran tal clase.
            #
            # Viendo tu imagen de "RESULTADO DE BÚSQUEDA", los enlaces son el texto principal de cada item.
            # NO tienen la clase "enlaces". La clase "enlaces" era para "Ver más" del indicador.
            #
            # ¡AJUSTE IMPORTANTE DEL SELECTOR DE RESULTADOS!
            # Los enlaces de los resultados en la imagen que SÍ tiene resultados no usan 'a.enlaces'.
            # Son enlaces que contienen el título del acuerdo.
            # Si inspeccionas uno de esos enlaces en la página de resultados real (la que funciona manualmente),
            # necesitas encontrar un patrón.
            #
            # EJEMPLO DE UN SELECTOR MÁS PROBABLE PARA LA PÁGINA DE RESULTADOS REAL:
            # Si los resultados están en una tabla y cada fila de resultado tiene un enlace:
            # Supongamos que los resultados están en una tabla con un `<tbody>` y luego `<tr>`
            # Y dentro de un `<td>` hay un `<a>` que es el título.
            # O si cada resultado es un <div class="resultado-item"> y dentro un <a>
            #
            # Vamos a usar un selector que busque enlaces dentro de un contenedor que
            # probablemente solo exista en la página de resultados.
            # Viendo la imagen de "RESULTADO DE BÚSQUEDA", parece que cada resultado está en un bloque.
            # Los enlaces son directamente el texto del acuerdo.
            #
            # INTENTEMOS UN SELECTOR MÁS ESPECÍFICO PARA LOS TÍTULOS DE LOS RESULTADOS:
            # Este es un intento, podría necesitar ajuste basado en el HTML real de la página de resultados.
            # Buscamos enlaces que están dentro de un 'td' con alineación 'justify' y clase 'NotaCompleta'.
            # O un patrón más general si eso no funciona: buscar enlaces que parezcan títulos de notas.
            #
            # El HTML de la página de "ATENTO AVISO" no tiene la misma estructura que la de resultados.
            #
            # Selector anterior: selector_resultados_enlaces = "a.enlaces" <--- INCORRECTO para resultados principales
            #
            # NUEVO INTENTO DE SELECTOR para los enlaces principales de resultados (basado en cómo se ven en la imagen):
            # Los enlaces de resultado de búsqueda suelen ser `<a>` dentro de celdas de tabla o divs específicos.
            # Mirando tu imagen "original_image.png", los enlaces de resultados NO son "a.enlaces".
            # Son el texto descriptivo. Necesitamos un selector para ESOS enlaces.
            # Si los resultados están en celdas de una tabla:
            # Ejemplo: `table.resultados_detalle td > a` (si la tabla tiene esa clase)
            #
            # Vamos a asumir que los enlaces de resultados están dentro de elementos `<a>`
            # que son hijos directos de `<td>` y que su `href` contiene "nota_detalle.php".
            # Esto es una suposición común para el DOF.
            selector_resultados_principales = 'td > a[href*="nota_detalle.php"]'
            # O si el texto es el enlace y está en un `div` con una clase específica:
            # selector_resultados_principales = 'div.resultado_item a' (esto es una suposición)

            # Si la página de resultados tiene un `div` o `table` con un ID o clase específica que envuelve todos los resultados:
            # page.wait_for_selector("#contenedorDeResultados " + selector_resultados_principales, timeout=60000)

            # Por ahora, intentaremos el selector más genérico para los enlaces de detalle de nota,
            # asumiendo que ya estamos en la página correcta (no la de aviso).
            try:
                page.wait_for_selector(selector_resultados_principales, state="visible", timeout=60000)
                print(f"Selector para resultados principales ('{selector_resultados_principales}') encontrado.")
            except PlaywrightTimeoutError:
                print(f"TIMEOUT: No se encontraron enlaces de resultados principales con el selector '{selector_resultados_principales}'.")
                print("Es posible que la búsqueda no haya arrojado resultados, o el selector es incorrecto para la página de resultados.")
                # Guardar HTML y screenshot de esta página también
                page_content_no_results = page.content()
                no_results_html_path = os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "pagina_sin_resultados_o_selector_incorrecto.html")
                with open(no_results_html_path, "w", encoding="utf-8") as f:
                    f.write(page_content_no_results)
                print(f"HTML de la página actual guardado en: {no_results_html_path}")
                page.screenshot(path=os.path.join(os.path.dirname(__file__) if "__file__" in locals() else ".", "screenshot_sin_resultados.png"), full_page=True)
                return # Salir si no hay resultados con el selector esperado


            print("Extrayendo enlaces de los resultados principales...")
            enlaces_elementos = page.query_selector_all(selector_resultados_principales)

            enlaces_extraidos = []
            if not enlaces_elementos:
                print("No se encontraron enlaces de resultados principales con el selector.")
            else:
                print(f"Se encontraron {len(enlaces_elementos)} elementos para resultados principales.")
                current_page_url = page.url
                for i, elemento_enlace in enumerate(enlaces_elementos):
                    href = elemento_enlace.get_attribute("href")
                    # Para el texto, intentemos tomar el texto del enlace directamente,
                    # o si está anidado, podrías necesitar un selector más específico dentro del 'a'
                    texto_enlace = elemento_enlace.inner_text().strip().replace('\n', ' ').replace('\r', ' ')
                    if href and texto_enlace: # Asegurarse de que hay href Y texto.
                        enlace_absoluto = urljoin(current_page_url, href)
                        enlaces_extraidos.append({"texto": texto_enlace, "url": enlace_absoluto})
                        print(f" - Encontrado ({i+1}): {texto_enlace} ({enlace_absoluto})")
                    else:
                        print(f" - Elemento ({i+1}) no tenía href o texto válido. Href: {href}, Texto: '{texto_enlace}'")


            if enlaces_extraidos:
                base_path = os.path.dirname(__file__) if "__file__" in locals() else "."
                ruta_archivo_csv = os.path.join(base_path, nombre_archivo_csv)
                print(f"\nGuardando {len(enlaces_extraidos)} enlaces en '{ruta_archivo_csv}'...")
                with open(ruta_archivo_csv, mode='w', newline='', encoding='utf-8') as archivo_csv:
                    escritor_csv = csv.DictWriter(archivo_csv, fieldnames=["texto", "url"])
                    escritor_csv.writeheader()
                    escritor_csv.writerows(enlaces_extraidos)
                print(f"Enlaces guardados exitosamente en '{ruta_archivo_csv}'.")
            else:
                print("No se extrajeron enlaces de resultados principales para guardar.")

        except PlaywrightTimeoutError as e_timeout:
            print(f"Ocurrió un TIMEOUT durante la ejecución del scraping: {e_timeout}")
            # ... (código de guardado de screenshot y HTML)
            error_screenshot_path = "error_dof_scraper_timeout.png"
            base_path = os.path.dirname(__file__) if "__file__" in locals() else "."
            full_screenshot_path = os.path.join(base_path, error_screenshot_path)
            try:
                html_content = page.content()
                with open(os.path.join(base_path, "error_page_content_timeout.html"), "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"Se guardó el contenido HTML de la página del error: {os.path.join(base_path, 'error_page_content_timeout.html')}")
                page.screenshot(path=full_screenshot_path, full_page=True)
                print(f"Se guardó una captura de pantalla del error: {full_screenshot_path}")
            except Exception as e_screenshot:
                print(f"No se pudo guardar la captura de pantalla o el HTML del error: {e_screenshot}")

        except Exception as e:
            print(f"Ocurrió un error INESPERADO durante la ejecución del scraping: {e}")
            # ... (código de guardado de screenshot y HTML)
            error_screenshot_path = "error_dof_scraper_inesperado.png"
            base_path = os.path.dirname(__file__) if "__file__" in locals() else "."
            full_screenshot_path = os.path.join(base_path, error_screenshot_path)
            try:
                html_content = page.content()
                with open(os.path.join(base_path, "error_page_content_inesperado.html"), "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"Se guardó el contenido HTML de la página del error: {os.path.join(base_path, 'error_page_content_inesperado.html')}")
                page.screenshot(path=full_screenshot_path, full_page=True)
                print(f"Se guardó una captura de pantalla del error: {full_screenshot_path}")
            except Exception as e_screenshot:
                print(f"No se pudo guardar la captura de pantalla o el HTML del error: {e_screenshot}")

        finally:
            if browser and browser.is_connected():
                browser.close()
                print("Navegador cerrado.")

if __name__ == "__main__":
    termino_a_buscar = "acuerdo energías limpias"
    nombre_del_archivo = "resultados_dof.csv"
    print(f"Iniciando script para buscar en DOF: '{termino_a_buscar}'")
    buscar_en_dof_y_extraer_enlaces_local(termino_a_buscar, nombre_del_archivo)
    print("Script de scraping del DOF finalizado.")