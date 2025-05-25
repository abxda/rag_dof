*Nota: Los nombres de carpetas y archivos generados pueden variar según el término de búsqueda utilizado.*

## Instalación y Configuración

1.  **Clonar el Repositorio:**
    ```bash
    git clone https://github.com/tu_usuario/rag_dof.git
    cd rag_dof
    ```

2.  **Configurar Entorno Conda:**
    Se recomienda usar Conda (Miniforge/Anaconda) para gestionar el entorno.
    ```bash
    conda create --name rag_dof_env python=3.11 # O la versión de Python que prefieras
    conda activate rag_dof_env
    ```

3.  **Instalar Dependencias de Python:**
    Navega al directorio `scripts/` (o donde tengas los scripts) y ejecuta:
    ```bash
    pip install playwright groq python-dotenv tiktoken ollama numpy scikit-learn lancedb
    ```
    *(Puede ser necesario añadir `--break-system-packages` si estás en un entorno Linux que protege el Python del sistema).*

4.  **Instalar Navegadores para Playwright:**
    ```bash
    playwright install
    # Opcionalmente, para dependencias de sistema en Linux:
    # playwright install-deps
    ```

5.  **Instalar y Configurar Ollama:**
    *   Sigue las instrucciones en [ollama.com](https://ollama.com/install.sh) para instalar Ollama.
    *   Descarga el modelo de embeddings:
        ```bash
        ollama pull bge-m3
        ```
    *   Asegúrate de que el servicio Ollama esté corriendo.

6.  **Configurar API Keys:**
    *   Crea un archivo `.env` en la raíz del proyecto (`rag_dof/.env`).
    *   Añade tu clave API de Groq:
        ```
        GROQ_API_KEY=gsk_TU_API_KEY_DE_GROQ_AQUI
        ```

7.  **Crear `.gitignore`:**
    Asegúrate de que tu archivo `.gitignore` incluya al menos:
    ```
    .env
    __pycache__/
    *.pyc
    /decreto_colectados/
    /decreto_colectados_resumen/
    /lancedb_store_bge_m3/
    *.csv
    *OLD*/
    *.DS_Store
    ```

## Ejecución de los Scripts

Los scripts están diseñados para ejecutarse en secuencia. Se recomienda revisar cada script para entender su función específica y ajustar parámetros como términos de búsqueda, modelos LLM, o límites de recolección según sea necesario.

1.  **`001_test_playwright.py`**: Prueba la configuración de Playwright.
2.  **`002_dof_web_scraper.py` / `003_dof_web_scraper_next.py`**: Recolecta URLs del DOF. (El `_next.py` incluye paginación).
3.  **`004_procesar_urls_dof.py`**: Descarga el contenido de las URLs recolectadas.
4.  **`005_generar_resumenes_dof.py`**: Genera resúmenes de los documentos descargados.
5.  **`006_contar_tokens_dof.py`**: Cuenta tokens de los documentos o resúmenes.
6.  **`007_crear_bd_lancedb_dof.py`**: Crea la base de datos vectorial con embeddings.
7.  **`008_consultar_bd_lancedb_terminal.py`**: Permite probar la recuperación de la BD LanceDB.
8.  **`009_rag_dof_ollama_groq_deepseek.py`**: Ejecuta la aplicación RAG interactiva completa.

**Ejemplo de ejecución del pipeline RAG (después de los pasos previos):**
```bash
conda activate rag_dof_env
cd scripts # o donde estén los scripts
python 009_rag_dof_ollama_groq_deepseek.py
