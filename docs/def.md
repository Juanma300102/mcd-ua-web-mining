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

La Nación e Infobae publican sitemaps diarios con todas las notas del día, y el HTML de cada nota trae embebido el JSON estructurado de Arc XP, así que no hace falta su API interna. MisionesOnline, al estar hecho en WordPress, expone su API REST pública (/wp-json/wp/v2/posts), pero desde 10/2026 responde con un desafío de Cloudflare (ver Riesgos).

## Tecnologias

- Dagster para orquestación de datos  
- Python  
- UV package manager  
- Requests library para sitemaps, HTML de notas y la API de WordPress  
- Playwright solo como respaldo, sin usarlo para pasar desafíos anti-bot.

## Planteamiento

El proyecto construye un dataset de noticias de política argentina publicadas desde la asunción de Javier Milei (10/12/2023) en tres medios, y mide cómo evoluciona el tono de esa cobertura en el tiempo.  
**Pregunta principal:** ¿cómo cambió el sentimiento de las noticias de política desde diciembre de 2023, y difiere entre un medio nacional digital (Infobae), un diario nacional tradicional (La Nación) y un medio provincial (MisionesOnline)?  
**Preguntas secundarias:**

* ¿Hay quiebres de tono alrededor de hitos políticos (DNU 70/2023, Ley Bases, elecciones legislativas de octubre de 2025, al menos un hito de Misiones)?  
* ¿El medio provincial cubre la política con un tono distinto al de los nacionales?

**Alcance:** sección Política de cada medio, del 10/12/2023 a una fecha de corte fija del scraping. Se trabaja con título, bajada y cuerpo de cada nota.  
**Fuera de alcance (por tiempo):** actualización diaria, clasificador de temas nacional vs provincial, acuerdo entre anotadores, modelos de series temporales o de puntos de quiebre, y tono hacia el gobierno.

## Fuentes de datos

Todo se consume con requests, por rutas que el robots.txt de cada medio permite. Infobae y La Nación usan Arc XP: se listan las notas con el sitemap diario, se filtran las URLs de /politica/ y se descarga el HTML de cada nota, que trae el JSON de la nota en `Fusion.globalContent` (título, bajada, cuerpo por bloques, autor, sección, tags, fechas). No se usa la API interna del frontend (/pf/api/v3/content/fetch/...): el robots.txt de La Nación la prohíbe para todos los user agents, y usar el mismo patrón en los dos medios simplifica los clientes. MisionesOnline es WordPress y expone su API REST.

| Medio | Cómo listar notas | Cómo obtener el texto | Observaciones |
| :---- | :---- | :---- | :---- |
| Infobae | Sitemap diario /arc/outboundfeeds/sitemap/\<AAAA-MM-DD\>/, filtrando URLs /politica/ | HTML de la nota, JSON en Fusion.globalContent | Responde para 2023-12-11 (1375 URLs, 23 de Política). El sitemap por categoría (/sitemap2/category/politica/) solo trae las últimas 100 y no pagina. Hay notas "en vivo" largas. robots.txt solo prohíbe /buscador |
| La Nación | Sitemap diario /sitemap-articles-from\<AAAA-MM-DD\>T00:00:00Z-to\<día siguiente\>T00:00:00Z.xml, filtrando URLs /politica/ | HTML de la nota, JSON en Fusion.globalContent | El índice histórico solo lista los últimos ~2 años, pero los archivos diarios anteriores responden: 2023-12-11 trae 364 URLs, 41 de Política. Muestra de 10 notas: content\_code "comun" y cuerpo completo (477 a 1483 palabras). robots.txt prohíbe /pf/api/ y /buscador para User-agent: \* |
| MisionesOnline | API REST de WordPress: /wp-json/wp/v2/posts?categories=7\&after=2023-12-10 | El mismo JSON trae content.rendered (HTML del cuerpo) | Categoría Política (id 7), 55.895 notas en total, hija de Política y Economía (id 93796\). Desde 10/2026 todo el sitio, robots.txt incluido, responde 403 con desafío de Cloudflare |

Consultado el 01/10/2026: misionesonline.net/wp-json/wp/v2/categories, robots.txt de Infobae y La Nación, infobae.com/arc/outboundfeeds/sitemap-index-static y lanacion.com.ar/sitemap-index-historico.xml.  
Revisado el 27/10/2026 con un User-Agent identificable: robots.txt de los tres medios, sitemaps diarios de 2023-12-11 y 2024-10-27, HTML de 1 nota de Infobae y 11 de La Nación, y la API de MisionesOnline (bloqueada).

## Arquitectura

Se reutiliza el marco del repo mcd-ua-text-mining: proyecto Dagster con uv, assets cargados desde defs/ con load\_from\_defs\_folder, Postgres en docker-compose como storage de Dagster y el script dagster-up.sh para levantar todo. Se descarta lo específico de fake news (LightGBM, BERT, SearXNG, webapp).  
Flujo de assets:

1. raw\_infobae, raw\_lanacion y raw\_misionesonline: una descarga por medio, particionada por mes. Un mes fallido se reintenta solo y el backfill histórico corre por partes.  
2. noticias\_politica: une las tres fuentes con un esquema común, limpia el HTML y deduplica.  
3. sentimiento\_noticias: score de sentimiento por nota.  
4. evolucion\_tono: agregados por medio y semana, y gráficos.

No hay schedule diario: un job de backfill descarga desde 12/2023 hasta la fecha de corte. Estructura propuesta del repo:  
`news-politica/`  
  `docker-compose.yaml        # postgres (copiado del repo anterior)`  
  `pyproject.toml / uv.lock`  
  `scripts/dagster-up.sh`  
  `src/news_politica/`  
    `definitions.py`  
    `dagster_home/dagster.yaml`  
    `sources/                 # un cliente por medio`  
    `defs/assets/             # raw_*, noticias_politica, sentimiento, evolucion`  
    `defs/jobs.py             # job de backfill`  
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
* **Validación:** escribir una guía corta de etiquetado (qué cuenta como positivo, neutral o negativo, con ejemplos), etiquetar a mano unas 300 notas (100 por medio) y reportar accuracy y F1 macro de cada modelo.  
* **Agregación:** score medio y proporción de notas negativas por medio y por semana, con los hitos políticos marcados en el gráfico. Los hitos y sus fechas van en un archivo versionado, y para cada uno se comparan las 2 semanas anteriores con las 2 posteriores.

## Pasos de ejecución

Seis fases en orden; la 2 y la 3 se pueden repartir entre los dos integrantes.

1. **Base del proyecto.** Crear el repo copiando de mcd-ua-text-mining el docker-compose.yaml (solo Postgres), dagster.yaml, dagster-up.sh y la estructura uv \+ defs/. Validar con dg check defs.  
2. **Exploración de fuentes.** Para cada medio, un notebook que confirme cómo listar notas de Política desde 12/2023, qué campos vienen y cuántas notas hay por mes. Se empieza por MisionesOnline, que hoy es la fuente más riesgosa por el bloqueo de Cloudflare.  
   1. MisionesOnline: confirmar si el bloqueo sigue (otro día, otra red) y, si se levanta, paginar /wp-json/wp/v2/posts por fecha con la categoría 7 y medir qué parte son notas de agencia (autor o firma). Si sigue bloqueado, evaluar el plan B (ver Riesgos).  
   2. Infobae: muestrear sitemaps diarios a lo largo del período para estimar notas de Política por mes, mapear los campos de Fusion.globalContent al esquema y medir cuántas notas son "en vivo".  
   3. La Nación: lo mismo que Infobae, más buscar notas con content\_code distinto de "comun" para confirmar que tampoco vienen truncadas.  
   4. Nota de decisión: rate limit, duración estimada del backfill, fecha de corte, plan B para MisionesOnline, qué hacer con las notas de agencia y con las notas "en vivo".  
3. **Clientes de scraping.** Un cliente HTTP compartido (rate limit, reintentos y User-Agent identificable) y un modelo común de nota, más un módulo por medio en sources/. Tests con respuestas guardadas.  
4. **Assets de Dagster.** raw\_\* particionados por mes, noticias\_politica con limpieza y deduplicado, y un job de backfill desde 12/2023 hasta la fecha de corte. Cierra con el EDA del dataset (volumen por medio y semana, largo de notas, proporción con bajada), que alimenta las decisiones de la fase 5.  
5. **Sentimiento.** Guía de etiquetado y muestra etiquetada, baseline y modelo alternativo, elegir uno y materializar sentimiento\_noticias y evolucion\_tono con la comparación antes y después de cada hito.  
6. **Informe.** Gráficos de evolución con hitos, tabla antes y después de cada hito, comparación provincial vs nacional, conclusiones y limitaciones.

## Riesgos y decisiones abiertas

* **Bloqueo de MisionesOnline (abierto).** Desde 10/2026 el sitio entero responde 403 con un desafío de Cloudflare (`cf-mitigated: challenge`), incluso para robots.txt. No se intenta pasar el desafío (ni con Playwright ni cambiando el User-Agent). Opciones, en orden: esperar y reintentar desde otra red, pedir acceso al medio, cambiar por otro medio provincial (rehace la exploración de esa fuente) o seguir solo con los dos nacionales (se pierde la comparación provincial vs nacional).  
* **Paywall de La Nación.** Las notas muestreadas traen el cuerpo completo en el HTML, pero todas eran content\_code "comun". Falta confirmarlo con notas exclusivas para suscriptores.  
* **Fecha de los sitemaps.** No está confirmado si cada sitemap diario agrupa por fecha de publicación o por última modificación. Una nota editada podría aparecer en más de un día, así que el deduplicado por URL canónica es obligatorio.  
* **Notas "en vivo".** Infobae publica minuto a minuto de miles de palabras. Se decide en la fase 2 si se excluyen o se marcan.  
* **Notas de agencia.** Parte de las notas de MisionesOnline son de agencias nacionales. Se decide en la fase 2 si se excluyen o se marcan con una columna es\_agencia.  
* **robots.txt.** El robots.txt de La Nación prohíbe /pf/api/ para todos los user agents, por eso se usan solo sitemaps y el HTML de las notas. Conviene mencionarlo en el informe y usar un rate limit bajo.  
* **Volumen.** MisionesOnline tiene 55.895 notas de Política en total. Los días muestreados de Infobae y La Nación tienen entre 20 y 40 notas de Política, es decir entre 25.000 y 40.000 notas por medio en el período: con una request cada 2 segundos son unas 15 a 22 horas de backfill por medio. Hay que afinarlo en la fase 2.  
* **Sentimiento no es postura.** Una nota negativa puede serlo hacia la oposición. El informe debe aclarar qué mide el modelo.  
* **A decidir:** qué modelo de sentimiento usar, si se incluye el cuerpo o solo título \+ bajada, dónde se guarda el dataset (Parquet local o tabla en el mismo Postgres) y la fecha de corte.
