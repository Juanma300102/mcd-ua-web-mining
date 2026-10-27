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

La Nación e Infobae publican sitemaps diarios con todas las notas del día, y el HTML de cada nota trae embebido el JSON estructurado de Arc XP, así que no hace falta su API interna. MisionesOnline, al estar hecho en WordPress, expone su API REST pública (/wp-json/wp/v2/posts). El 27/10/2026 estuvo unas horas detrás de un desafío de Cloudflare (ver Riesgos).

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
| MisionesOnline | API REST de WordPress: /wp-json/wp/v2/posts?categories=7\&after=2023-12-10 | El mismo JSON trae content.rendered (HTML del cuerpo) | Categoría Política (id 7), 55.895 notas en toda su historia y 7.245 entre el 10/12/2023 y el 30/09/2026, hija de Política y Economía (id 93796\). El 27/10/2026 a la mañana respondió 403 con desafío de Cloudflare y a la tarde volvió a responder 200 |

Consultado el 01/10/2026: misionesonline.net/wp-json/wp/v2/categories, robots.txt de Infobae y La Nación, infobae.com/arc/outboundfeeds/sitemap-index-static y lanacion.com.ar/sitemap-index-historico.xml.  
Revisado el 27/10/2026 con un User-Agent identificable: robots.txt de los tres medios, sitemaps diarios de 2023-12-11 y 2024-10-27, HTML de 1 nota de Infobae y 11 de La Nación, y la API de MisionesOnline (bloqueada a la mañana).  
Exploración de la fase 2 (27/10/2026): volumen, mapa de campos, notas de agencia, notas en vivo, paywall y agrupación de los sitemaps en [`docs/decision-fuentes.md`](decision-fuentes.md), con la evidencia en `notebooks/`.

## Arquitectura

Se reutiliza el marco del repo mcd-ua-text-mining: proyecto Dagster con uv, assets cargados desde defs/ con load\_from\_defs\_folder, Postgres en docker-compose como storage de Dagster y el script dagster-up.sh para levantar todo. Se descarta lo específico de fake news (LightGBM, BERT, SearXNG, webapp).  
Flujo de assets:

1. catalogo\_infobae y catalogo\_lanacion: recorren los sitemaps diarios desde el 10/12/2023 hasta el día del scraping y guardan las URLs de Política con la fecha de su URL, que coincide con la de primera publicación. MisionesOnline no lo necesita: su API filtra por fecha de publicación.  
2. raw\_infobae, raw\_lanacion y raw\_misionesonline: una descarga por medio, particionada por mes (los medios Arc toman del catálogo las URLs de ese mes). Guardan el JSON de la nota tal como viene del medio, no el HTML, así que un cambio en el parseo no obliga a volver a scrapear. Un mes fallido se reintenta solo, salvo que el sitio responda con un desafío anti-bot, y el backfill histórico corre por partes.  
3. noticias\_politica: parsea el JSON de los tres medios al esquema común (el texto plano y las fechas salen de `sources/`), filtra el período por fecha de publicación y deduplica.  
4. sentimiento\_noticias: score de sentimiento por nota.  
5. evolucion\_tono: agregados por medio y semana, y gráficos.

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
| fuente\_externa | string | Medio citado al final de la nota ("Fuente: X"), si existe. Solo aparece en MisionesOnline |
| es\_en\_vivo | bool | Nota en vivo o minuto a minuto. Queda fuera de los agregados de tono por defecto |
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
2. **Exploración de fuentes (hecha, ver [`docs/decision-fuentes.md`](decision-fuentes.md)).** Para cada medio, un notebook que confirme cómo listar notas de Política desde 12/2023, qué campos vienen y cuántas notas hay por mes. Se empieza por MisionesOnline, que era la fuente más riesgosa por el bloqueo de Cloudflare.  
   1. MisionesOnline: confirmar si el bloqueo sigue (otro día, otra red) y, si se levanta, paginar /wp-json/wp/v2/posts por fecha con la categoría 7 y medir qué parte son notas de agencia (autor o firma). Si sigue bloqueado, evaluar el plan B (ver Riesgos).  
   2. Infobae: muestrear sitemaps diarios a lo largo del período para estimar notas de Política por mes, mapear los campos de Fusion.globalContent al esquema y medir cuántas notas son "en vivo".  
   3. La Nación: lo mismo que Infobae, más buscar notas con content\_code distinto de "comun" para confirmar que tampoco vienen truncadas.  
   4. Nota de decisión: rate limit, duración estimada del backfill, fecha de corte, plan B para MisionesOnline, qué hacer con las notas de agencia y con las notas "en vivo".  
3. **Clientes de scraping (hecha, cambio OpenSpec `add-scraping-clients`).** Un cliente HTTP compartido (rate limit, reintentos y User-Agent identificable), los modelos comunes (entrada de catálogo, documento crudo y nota) y un módulo por medio en sources/. Tests con respuestas guardadas y texto recortado.  
4. **Assets de Dagster.** raw\_\* particionados por mes, noticias\_politica con limpieza y deduplicado, y un job de backfill desde 12/2023 hasta la fecha de corte. Cierra con el EDA del dataset (volumen por medio y semana, largo de notas, proporción con bajada), que alimenta las decisiones de la fase 5.  
5. **Sentimiento.** Guía de etiquetado y muestra etiquetada, baseline y modelo alternativo, elegir uno y materializar sentimiento\_noticias y evolucion\_tono con la comparación antes y después de cada hito.  
6. **Informe.** Gráficos de evolución con hitos, tabla antes y después de cada hito, comparación provincial vs nacional, conclusiones y limitaciones.

## Riesgos y decisiones abiertas

* **Bloqueo de MisionesOnline.** El 27/10/2026 a la mañana el sitio entero respondió 403 con un desafío de Cloudflare (`cf-mitigated: challenge`), y a la tarde volvió a responder. No se intenta pasar el desafío (ni con Playwright ni cambiando el User-Agent): el cliente se detiene. Su backfill tarda menos de 5 minutos, así que se corre primero. Si el bloqueo vuelve y no se levanta, opciones en orden: pedir acceso al medio, cambiar por otro medio provincial (rehace la exploración de esa fuente) o seguir solo con los dos nacionales (se pierde la comparación provincial vs nacional).  
* **Paywall de La Nación (abierto).** En 186 notas solo aparecieron los códigos de acceso libre `comun` y `abierta`, todas con el cuerpo completo. La truncación de notas pagas no está verificada: se revisa en el EDA (largo del cuerpo por content\_code).  
* **Fecha de los sitemaps (decidido).** La Nación agrupa por `display_date` y Infobae por última modificación, y las dos listan notas meses después de su publicación. Los clientes recorren los sitemaps hasta el día del scraping, filtran por fecha de primera publicación y deduplican por URL canónica.  
* **Notas "en vivo" (decidido).** Son el 2,2 % de Infobae y no aparecieron en La Nación. Se conservan con `es_en_vivo` y quedan fuera de los agregados de tono por defecto.  
* **Notas de agencia y reescrituras (decidido).** En MisionesOnline casi no hay firmas de agencia, pero el 11,4 % de las notas cierra con "Fuente: X" (sobre todo Infobae y TN) y el 12,7 % está también en Nacionales. Se conservan con `fuente_externa`, y la comparación provincial vs nacional se reporta con y sin esas notas.  
* **robots.txt.** El robots.txt de La Nación prohíbe /pf/api/ para todos los user agents, por eso se usan solo sitemaps y el HTML de las notas. Conviene mencionarlo en el informe y usar un rate limit bajo.  
* **Volumen.** Entre el 10/12/2023 y el 30/09/2026: 7.245 notas de MisionesOnline (unas 50 por semana; para la fase 5 puede convenir agregar por quincena o por mes), unas 23.100 de Infobae y unas 26.600 de La Nación. A una request cada 2 s, el backfill de cada medio Arc tarda unas 14 a 16 horas y baja de 5 a 10 GB de HTML, así que los raw guardan solo el JSON de la nota.  
* **Sentimiento no es postura.** Una nota negativa puede serlo hacia la oposición. El informe debe aclarar qué mide el modelo.  
* **Fecha de corte (decidido).** 31/10/2026 23:59, hora argentina, por fecha de publicación.  
* **A decidir:** qué modelo de sentimiento usar, si se incluye el cuerpo o solo título \+ bajada, y dónde se guarda el dataset (Parquet local o tabla en el mismo Postgres).
