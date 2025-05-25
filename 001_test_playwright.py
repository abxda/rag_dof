from playwright.sync_api import sync_playwright, Playwright
import sys

def run_test():
    print(f"Intentando usar Playwright con Python en: {sys.executable}")
    version_disponible = False
    try:
        # Intentar obtener la versión del paquete playwright instalado si está disponible
        # Esto se hace mejor con 'pip show playwright' desde la CLI.
        # Aquí solo confirmamos que podemos importar módulos específicos.
        import playwright.sync_api
        print(f"Módulo playwright.sync_api importado correctamente.")
        version_disponible = True # Asumimos que si importa, algo está bien.
    except ImportError:
        print("Error: No se pudo importar playwright.sync_api. La biblioteca Playwright de Python no parece estar instalada correctamente.")
        return
    except Exception as e_ver:
        print(f"No se pudo determinar la versión de la biblioteca Playwright mediante importación: {e_ver}")
        version_disponible = True # Aún así, procedemos con la prueba funcional

    if not version_disponible:
         print("No se pudo confirmar la instalación de la biblioteca Playwright.")
         return

    try:
        with sync_playwright() as playwright_instance:
            print("Playwright Sync API iniciada.")

            # Probar Chromium
            try:
                browser_chromium = playwright_instance.chromium.launch(headless=True)
                print("Chromium lanzado exitosamente.")
                browser_chromium.close()
                print("Chromium cerrado.")
            except Exception as e_chromium:
                print(f"Error al lanzar/cerrar Chromium: {e_chromium}")
                print("Asegúrate de que Chromium esté instalado (ej. 'python -m playwright install chromium')")

            # Puedes descomentar las siguientes secciones si también quieres probar Firefox y WebKit
            # Probar Firefox
            # try:
            #     browser_firefox = playwright_instance.firefox.launch(headless=True)
            #     print("Firefox lanzado exitosamente.")
            #     browser_firefox.close()
            #     print("Firefox cerrado.")
            # except Exception as e_firefox:
            #     print(f"Error al lanzar/cerrar Firefox: {e_firefox}")
            #     print("Asegúrate de que Firefox esté instalado (ej. 'python -m playwright install firefox')")

            # Probar WebKit
            # try:
            #     browser_webkit = playwright_instance.webkit.launch(headless=True)
            #     print("WebKit lanzado exitosamente.")
            #     browser_webkit.close()
            #     print("WebKit cerrado.")
            # except Exception as e_webkit:
            #     print(f"Error al lanzar/cerrar WebKit: {e_webkit}")
            #     print("Asegúrate de que WebKit esté instalado (ej. 'python -m playwright install webkit')")

        print("\nPrueba de Playwright completada exitosamente.")

    except Exception as e:
        print(f"Error general al usar Playwright: {e}")
        if "Executable doesn't exist" in str(e) or "BrowserType.launch: Executable" in str(e):
            print("Esto usualmente significa que los navegadores no están instalados o Playwright no puede encontrarlos.")
            print("Ejecuta 'python -m playwright install' en tu terminal (con el entorno Conda activo).")
        elif "No module named 'playwright'" in str(e): # Aunque ya lo verificamos
             print("Esto significa que la biblioteca Playwright de Python no está instalada en este entorno.")
             print("Ejecuta 'pip install playwright --break-system-packages' o revisa tu instalación.")
        else:
            print("Ocurrió un error inesperado durante la prueba funcional.")


if __name__ == "__main__":
    run_test()