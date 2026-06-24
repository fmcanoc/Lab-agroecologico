# Guía de la Plataforma — Laboratorio Abierto Agroecológico

## ¿Qué es la plataforma?

Es una aplicación web para el seguimiento y análisis de la salud del suelo en sistemas productivos agroecológicos. Permite registrar muestras de suelo, cargar los resultados de distintos análisis de laboratorio, importar datos de productores y parcelas desde **SurveyStack**, y visualizar los resultados de forma integrada.

Está diseñada para funcionar también sin conexión a internet (modo offline), guardando los datos ingresados localmente hasta que se pueda sincronizar.

---

## Cómo ingresar a la plataforma

1. Abrí el navegador y accedé a la URL de la plataforma.
2. En la pantalla de inicio verás dos opciones:
   - **Registrarse**: para crear una cuenta nueva (ingresás nombre de usuario y contraseña).
   - **Iniciar sesión**: si ya tenés cuenta, ingresás tu usuario y contraseña.
3. Una vez autenticado, serás redirigido al panel principal.

> Las contraseñas se almacenan de forma segura (hash). La plataforma no guarda contraseñas en texto plano.

---

## Estructura general

La aplicación está organizada en una barra lateral izquierda con las siguientes secciones:

### GENERAL
- **Muestras** — Registro de nuevas muestras de suelo con nombre, ubicación, cultivo y descripción. Incluye una sub-pestaña de **SurveyStack**.

### LABORATORIO
Cada pestaña corresponde a un método de análisis:

| Pestaña | Método |
|---|---|
| **Textura** | Clasificación textural por método organoléptico ("gusanito") |
| **Respiración** | Respiración basal del suelo (actividad de CO₂) |
| **Carbono Activo** | POXC — Carbono Oxidable por Permanganato |
| **Fósforo** | Método Olsen — disponibilidad de fósforo |
| **pH / CE** | pH y conductividad eléctrica del suelo |
| **MOP** | Materia Orgánica Particulada (%) |
| **Agregados** | Estabilidad de agregados — Índice Slakes (escala 0–6) |

### BIODIVERSIDAD
- **Macrofauna** — Registro fotográfico de fauna del suelo.
- **Cromatografía** — Análisis circular de cromatografía de Pfeiffer con foto y observaciones.

### MÉTRICAS
- **Resultados** — Visualización consolidada de todos los datos cargados.

---

## SurveyStack

**SurveyStack** es una plataforma externa de encuestas digitales utilizada para relevar información de productores, parcelas y muestras de suelo en campo. La plataforma puede importar automáticamente esos datos.

### Cómo conectar tu cuenta de SurveyStack

1. Ir a la pestaña **Muestras → SurveyStack**.
2. Ingresar el **email** y la **contraseña** de tu cuenta de SurveyStack.
3. Hacer clic en **Conectar**. Se guarda un token de acceso (no la contraseña).
4. Una vez conectado, aparecen las encuestas disponibles para importar.

### Encuestas preconfiguradas

La plataforma tiene tres encuestas integradas:

| Encuesta | Descripción |
|---|---|
| **Muestra Suelo** | Registro de muestras de suelo en campo |
| **Test Parcela** | Datos de la parcela (superficie, cultivo, historial) |
| **Test Productor** | Perfil del productor y la finca |

### Importar datos

1. Seleccionar la encuesta que querés importar.
2. Hacer clic en **Importar**. La plataforma descarga las respuestas desde SurveyStack y las asocia a tu cuenta.
3. Los datos de productores quedarán disponibles en la pestaña **Productores** y los de parcelas en **Parcelas** (dentro de Resultados).

### Desconectar

En la misma sección se puede revocar el acceso con el botón **Desconectar**.

---

## Asistente de métodos (chat emergente)

En la esquina inferior derecha de la pantalla encontrarás un botón flotante con un ícono de chat. Al hacer clic, se abre el **Asistente de Métodos de Laboratorio**.

### ¿Qué hace?

El asistente detecta automáticamente en qué pestaña de análisis estás parado y ofrece respuestas sobre ese método específico.

### Preguntas predefinidas

Para cada método hay tres preguntas rápidas disponibles:

| Botón | Pregunta |
|---|---|
| **¿Qué es?** | Descripción del método o indicador |
| **¿Para qué sirve?** | Utilidad e información que aporta al análisis del suelo |
| **¿Cómo se interpreta?** | Rangos de referencia y lectura de los resultados |

También podés escribir tu propia pregunta en el campo de texto.

> El asistente se oculta automáticamente en la sección de Resultados, ya que allí la información se presenta de otra forma.

---

## Sección de Resultados

La pestaña **Resultados** integra todos los datos cargados en un solo lugar. Tiene cuatro sub-pestañas:

### Resultados (principal)

- **Tabla consolidada**: muestra todas las muestras con sus valores por método (textura, pH, CE, POXC, fósforo, respiración, MOP, Índice Slakes, cromatografía). Cada columna tiene un botón `ⓘ` con información de interpretación del indicador.
- **Gráfico de burbujas**: visualización interactiva de correlaciones entre dos indicadores seleccionables en los ejes X e Y.
- **Gráfico de respiración**: evolución del CO₂ a lo largo del tiempo para todas las muestras.
- **Radar**: perfil comparativo de una muestra seleccionada.
- **Mapa**: ubicación geográfica de las muestras sobre un mapa interactivo (Leaflet).
- **Exportar CSV**: botón para descargar todos los datos en formato `.csv`.

### Muestra

Vista detallada de una muestra individual con todos sus análisis cargados.

### Parcelas

Listado de parcelas importadas desde SurveyStack, con datos productivos de cada una.

### Productores

Perfiles de productores importados desde SurveyStack con datos de sus fincas.
