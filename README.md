# Laboratorio Agroecológico

Aplicación web (Flask) para el seguimiento y análisis colaborativo de la salud del suelo en sistemas productivos agroecológicos. Forma parte del **Kit Abierto para el Monitoreo de la Salud del Suelo**: permite registrar muestras, cargar resultados de laboratorio (propios y externos), importar datos de campo desde SurveyStack, y visualizar todo de forma consolidada (tablas, gráficos, mapa).

Funciona también sin conexión a internet (modo offline), guardando los datos localmente hasta poder sincronizar.

## Métodos de laboratorio soportados

- Textura (método organoléptico)
- Volumen de Sedimentación
- Respiración basal (CO₂)
- Carbono Activo (POXC)
- Fósforo disponible (Olsen)
- pH y Conductividad Eléctrica
- Materia Orgánica Particulada (MOP)
- Estabilidad de agregados (Índice Slakes)
- Macrofauna
- Cromatografía de Pfeiffer
- Carga de análisis de laboratorio externo

Más detalle de uso de la plataforma en [GUIA_PLATAFORMA.md](GUIA_PLATAFORMA.md).

## Stack

- Flask + Werkzeug
- PostgreSQL (via `psycopg`)
- pandas / numpy / scipy / matplotlib para el procesamiento de datos
- Frontend: Bootstrap 5, ECharts, Leaflet

## Configuración local

1. Cloná el repo e instalá las dependencias:

   ```bash
   python -m venv venv
   venv\Scripts\activate  # en Windows
   pip install -r requirements.txt
   ```

2. Creá un archivo `.env` en la raíz con:

   ```
   DATABASE_URL=***REMOVED_DB_URI***
   SECRET_KEY=una-clave-secreta
   ```

3. Ejecutá la aplicación:

   ```bash
   python app.py
   ```

## Recursos

- [Manual del Kit](https://labagroecoabierto.gitlab.io/manual-kit-salud-suelo/)
- Contacto: fcastro@fca.uncu.edu.ar
