### Integrantes

- Carlos Aular  
- Juan Martin Pedrozo

# Descripción

Proyecto de scrapping de 3 sitios de noticias.

## Objetivo

Scrapear todas las noticias del tema Política desde la asunción del actual Presidente, y luego realizar un análisis de sentimientos para obtener la evolución del tono de las noticias relacionadas.  
Se scrapera:

- Infobae  
- MisionesOnline  
- LaNacion

De los cuales La Nación e Infobae poseen una API pública que se puede usar para acceder a los datos estructurados directamente y MisionesOnline, al estar hecho en WordPress, expone su API REST pública (/wp-json/wp/v2/posts), por lo que no hace falta navegar el sitio para listar las notas.

## Tecnologias

- Dagster para orquestación de datos  
- Python  
- UV package manager  
- Playwright para scrappeo  
- Requests library para interaccion con APIs directa.

## Planteamiento

El proyecto construye un dataset de noticias de política argentina publicadas desde la asunción de Javier Milei (10/12/2023) en tres medios, y mide cómo evoluciona el tono de esa cobertura en el tiempo.  
**Pregunta principal:** ¿cómo cambió el sentimiento de las noticias de política desde diciembre de 2023, y difiere entre un medio nacional digital (Infobae), un diario nacional tradicional (La Nación) y un medio provincial (MisionesOnline)?  
**Preguntas secundarias:**

* ¿Hay quiebres de tono alrededor de hitos políticos (Ley Bases, elecciones legislativas de octubre de 2025, conflictos con gobernadores)?  
* ¿El medio provincial cubre la política con un tono distinto al de los nacionales?

**Alcance:** sección Política de cada medio, del 10/12/2023 a la fecha de corte del scraping. Se trabaja con título, bajada y cuerpo de cada nota.

## Fuentes de datos

Los tres medios exponen APIs públicas sin autenticación, así que todo se consume con requests y Playwright queda solo como respaldo. Infobae y La Nación usan Arc XP y su frontend consulta /pf/api/v3/content/fetch/...; MisionesOnline es WordPress y expone su API REST.

| Medio | Cómo listar notas | Cómo obtener el texto | Observaciones |
| :---- | :---- | :---- | :---- |
| Infobae | API pública de Arc del frontend (/pf/api/v3/content/fetch/...), sin auth. Respaldo: sitemaps por categoría (/arc/outboundfeeds/sitemap2/category/politica/) | Misma API de Arc: detalle de nota en JSON | robots.txt solo prohíbe /buscador |
| La Nación | API pública de Arc del frontend (/pf/api/v3/content/fetch/...), sin auth. Respaldo: sitemap histórico diario (sitemap-articles-from\<fecha\>-to\<fecha\>.xml) | Misma API de Arc: detalle de nota en JSON | El sitemap histórico solo lista desde 18/09/2025. robots.txt prohíbe /pf/api/ para bots |
| MisionesOnline | API REST de WordPress: /wp-json/wp/v2/posts?categories=7\&after=2023-12-10 | El mismo JSON trae content.rendered (HTML del cuerpo) | Categoría Política (id 7), 55.895 notas en total, hija de Política y Economía (id 93796\) |

Consultado el 01/10/2026: misionesonline.net/wp-json/wp/v2/categories, robots.txt de Infobae y La Nación, infobae.com/arc/outboundfeeds/sitemap-index-static y lanacion.com.ar/sitemap-index-historico.xml.

## Arquitectura

Se reutiliza el marco del repo mcd-ua-text-mining: proyecto Dagster con uv, assets cargados desde defs/ con load\_from\_defs\_folder, Postgres en docker-compose como storage de Dagster y el script dagster-up.sh para levantar todo. Se descarta lo específico de fake news (LightGBM, BERT, SearXNG, webapp).  
Flujo de assets:

1. raw\_infobae, raw\_lanacion y raw\_misionesonline: una descarga por medio, particionada por mes. Un mes fallido se reintenta solo y el backfill histórico corre por partes.  
2. noticias\_politica: une las tres fuentes con un esquema común, limpia el HTML y deduplica.  
3. sentimiento\_noticias: score de sentimiento por nota.  
4. evolucion\_tono: agregados por medio y semana, y gráficos.

Un schedule diario agrega las notas nuevas. Estructura propuesta del repo:  
`news-politica/`  
  `docker-compose.yaml        # postgres (copiado del repo anterior)`  
  `pyproject.toml / uv.lock`  
  `scripts/dagster-up.sh`  
  `src/news_politica/`  
    `definitions.py`  
    `dagster_home/dagster.yaml`  
    `sources/                 # un cliente por medio`  
    `defs/assets/             # raw_*, noticias_politica, sentimiento, evolucion`  
    `defs/jobs.py, schedules.py`  
  `data/                      # parquet, gitignored`  
  `notebooks/                 # EDA y gráficos del informe`  
  `tests/`

## Esquema del dataset

Una fila por nota, en Parquet, con el mismo esquema para los tres medios.

| Campo | Tipo | Descripción |
| :---- | :---- | :---- |
| id | string | Hash de la URL canónica |
| medio | string | infobae, lanacion o misionesonline |
| url | string | URL canónica de la nota |
| fecha\_publicacion | datetime | En hora de Argentina (UTC-3) |
| titulo | string | Título de la nota |
| bajada | string | Copete o resumen, si existe |
| cuerpo | string | Texto plano, sin HTML |
| autor | string | Si existe |
| seccion | string | Sección o categoría original del medio |
| tags | list\[string\] | Etiquetas del medio, si existen |
| fecha\_scraping | datetime | Cuándo se obtuvo la nota |

El asset de sentimiento agrega sentimiento (positivo, neutral, negativo), score y modelo, separado del dataset base para poder comparar modelos sin volver a scrapear.

## Análisis de sentimiento

Propuesta: arrancar con pysentimiento (modelo en español, salida positivo, neutral o negativo) como baseline, y compararlo contra un modelo multilingüe o un LLM en modo zero-shot sobre una muestra etiquetada a mano.

* **Unidad de análisis:** título \+ bajada como señal principal, porque los modelos tipo BERT cortan en 512 tokens. El cuerpo se analiza por párrafos y se promedia, como variante.  
* **Validación:** etiquetar a mano unas 300 notas (100 por medio) y reportar accuracy y F1 macro de cada modelo.  
* **Agregación:** score medio y proporción de notas negativas por medio y por semana, con los hitos políticos marcados en el gráfico.  
* **Opcional:** distinguir tono general de tono hacia el gobierno, filtrando notas que mencionen al Presidente o a ministros.

## Pasos de ejecución

Seis fases en orden; la 2 y la 3 se pueden repartir entre los dos integrantes.

1. **Base del proyecto.** Crear el repo copiando de mcd-ua-text-mining el docker-compose.yaml (solo Postgres), dagster.yaml, dagster-up.sh y la estructura uv \+ defs/. Validar con dagster definitions validate.  
2. **Exploración de fuentes.** Para cada medio, un notebook que confirme cómo listar notas de Política desde 12/2023, qué campos vienen y cuántas notas hay por mes.  
   1. Infobae y La Nación: documentar los endpoints de /pf/api que usa el frontend (listado por sección y detalle de nota) y cómo se pagina hacia atrás.  
   2. MisionesOnline: paginar /wp-json/wp/v2/posts por fecha con la categoría 7\.  
3. **Clientes de scraping.** Un módulo por medio en sources/, con rate limit, reintentos y User-Agent identificable. Tests con respuestas guardadas.  
4. **Assets de Dagster.** raw\_\* particionados por mes, noticias\_politica con limpieza y deduplicado, y un schedule diario. Backfill desde 12/2023.  
5. **Sentimiento.** Etiquetar la muestra, correr el baseline y el modelo alternativo, elegir uno y materializar sentimiento\_noticias y evolucion\_tono.  
6. **Informe.** EDA del dataset (volumen por medio y mes, largo de notas), gráficos de evolución con hitos, conclusiones y limitaciones.

## Riesgos y decisiones abiertas

* **Historia de La Nación.** El sitemap histórico solo llega a 09/2025, así que las notas anteriores dependen de la API. Hay que confirmar en la fase 2 que pagina hasta 12/2023.  
* **robots.txt.** Las APIs de Arc son públicas y sin auth, pero el robots.txt de La Nación prohíbe /pf/api/ para bots. Conviene mencionarlo en el informe y usar un rate limit bajo.  
* **Volumen.** MisionesOnline tiene 55.895 notas de Política en total; Infobae y La Nación probablemente superen eso en el período. Hay que estimarlo en la fase 2 antes del backfill.  
* **Sentimiento no es postura.** Una nota negativa puede serlo hacia la oposición. El informe debe aclarar qué mide el modelo.  
* **A decidir:** qué modelo de sentimiento usar, si se incluye el cuerpo o solo título \+ bajada, y dónde se guarda el dataset (Parquet local o tabla en el mismo Postgres).
