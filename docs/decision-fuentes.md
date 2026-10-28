# Decisión de fuentes (T2.4)

Cierre de la fase 2: cómo se obtiene cada medio, cuánto hay, cuánto tarda el backfill y qué se decide sobre fecha de corte, MisionesOnline, notas de agencia y notas en vivo. Cada número sale de un notebook en [`notebooks/`](../notebooks/) (las referencias son a sus secciones). Exploración hecha el 27/10/2026, con un User-Agent identificable, 2 s entre requests y solo rutas permitidas por robots.txt.

## Rutas por medio

| Medio | Listado | Texto | Evidencia |
| :---- | :---- | :---- | :---- |
| MisionesOnline | API REST de WordPress: `/wp-json/wp/v2/posts?categories=7&after=…&before=…&per_page=100&_embed=author,wp:term` (fechas en hora del sitio, UTC-3) | El mismo JSON: `content.rendered` | `01_misionesonline` §1–3 |
| Infobae | Sitemap diario `/arc/outboundfeeds/sitemap/<AAAA-MM-DD>/`, URLs `/politica/AAAA/MM/DD/…` | HTML de la nota, JSON de Arc en `Fusion.globalContent` | `02_infobae` §1, §3 |
| La Nación | Sitemap diario `/sitemap-articles-from<día>T00:00:00Z-to<día+1>T00:00:00Z.xml`, URLs `/politica/…` | HTML de la nota, JSON de Arc en `Fusion.globalContent` | `03_lanacion` §1, §3 |

Los 68 sitemaps muestreados de cada medio Arc respondieron 200, incluidos los de diciembre de 2023. No se usa `/pf/api/`, que el robots.txt de La Nación prohíbe para todos los user agents.

### Mapa de campos

Proporción de notas de la muestra con valor (`§3` de cada notebook). `medio` es constante y `fecha_scraping` la pone el cliente.

| Columna | MisionesOnline | Infobae | La Nación |
| :---- | :---- | :---- | :---- |
| url / id | `link`: 100 % | `canonical_url`: 100 % | `canonical_url`: 100 % |
| fecha\_publicacion | `date_gmt`: 100 % | `first_publish_date`: 100 % | `first_publish_date`: 100 % |
| titulo | `title.rendered`: 100 % | `headlines.basic`: 100 % | `headlines.basic`: 100 % |
| bajada | `excerpt.rendered` escrito a mano: 68 % (el resto es el inicio del cuerpo y se deja vacío) | `subheadlines.basic`: 100 % | `subheadlines.basic`: 98,5 % |
| cuerpo | `content.rendered`: 100 % | bloques `text`, `header` y `list`: 100 % | bloques `text`, `header` y `list`: 98,5 % |
| autor | autor de WordPress: 100 % ("Redacción" en el 28 %) | `credits.by`: 60 % | `credits.by`: 50 % |
| seccion | categorías: 100 % | `taxonomy.primary_section`: 100 % | `taxonomy.primary_section`: 100 % |
| tags | tags: 87,5 % | `taxonomy.tags`: 100 % | `taxonomy.tags`: 80 % |

En los medios Arc, el cuerpo tiene que incluir los bloques `header` y `list` (los ítems de una lista vienen anidados como bloques). Contando solo `text`, algunas notas de La Nación hechas de listas de frases quedaban con 37 palabras en lugar de 205 o más. En La Nación, el 1,5 % de la muestra (2 notas, `subtype` 9) son notas especiales armadas con bloques `raw_html` y sin texto: quedan con cuerpo vacío.

## Volumen y duración del backfill

| Medio | Notas de Política, 10/12/2023 a 30/09/2026 | Por día | Requests estimadas hasta el 31/10/2026 | Descarga estimada | Duración a 1 request / 2 s |
| :---- | :---- | :---- | :---- | :---- | :---- |
| MisionesOnline | 7.245 (conteo exacto, `X-WP-Total`) | ~7 | ~80 páginas de 100 | ~6 MB | < 5 min |
| Infobae | ~23.100 (estimado) | 22,6 | ~1.060 sitemaps + ~23.800 notas | ~0,9 GB de sitemaps + ~5 GB de HTML | ~14 h |
| La Nación | ~26.600 (estimado) | 26,1 | ~1.060 sitemaps + ~27.400 notas | ~0,1 GB de sitemaps + ~10 GB de HTML | ~16 h |

Fuentes: `01_misionesonline` §2, `02_infobae` §2, `03_lanacion` §2. Los tamaños medios son 897 KB por sitemap y 215 KB por nota en Infobae, 85 KB por sitemap y 380 KB por nota en La Nación, y 78 KB por página de 100 notas en MisionesOnline. Los estimados de Arc usan los días 10 y 25 de cada mes; los meses marcados con `spread_over_2x` (por ejemplo, diciembre por el 25) son los menos precisos.

Consecuencias para las fases 3 y 4:

- **Rate limit:** 1 request cada 2 s por host, sin requests en paralelo al mismo host. No hubo errores 429 ni 5xx en la exploración. Los tres medios pueden correr a la vez porque son hosts distintos.
- **No guardar el HTML.** El backfill bajaría unos 15 GB de HTML. Los `raw_*` guardan solo el JSON de la nota (o los campos del esquema), no la página.
- **Particiones mensuales:** unas 700 a 900 notas por mes y medio Arc, es decir, de 25 a 30 minutos por partición.

## Fecha de los sitemaps y deduplicado

- **La Nación** agrupa por `display_date` en UTC: el `lastmod` coincide con `display_date` en el 100 % de las notas leídas, y ninguna URL aparece también en el día anterior o en el siguiente (5 días revisados). Pero `display_date` difiere de `first_publish_date` en el 46 % de las notas, y hay URLs listadas meses después de su fecha (hasta 338 días). El 22 % de las URLs tiene en el `nid` el día anterior al del sitemap, por la diferencia entre UTC y la hora argentina (`03_lanacion` §5, §7).
- **Infobae** agrupa por última modificación: el `lastmod` coincide con `display_date` solo en el 26 % de las notas, y hay URLs listadas hasta 492 días después de su fecha. El 94 % cae en el mismo día y el 5 % en el anterior (`02_infobae` §5–6).

**Decisión:** los clientes recorren los sitemaps desde el 10/12/2023 hasta el día del scraping, no hasta la fecha de corte, y filtran por `first_publish_date`. Así no se pierden notas del período que fueron editadas después. `noticias_politica` deduplica por URL canónica.

## Fecha de corte

**Actualización (27/10/2026, cambio `add-dagster-assets`):** el corte pasa al 30/09/2026 23:59, porque la entrega es antes de que termine octubre.

**Decisión original:** 31/10/2026 23:59 (hora argentina), con `fecha_publicacion` como criterio. El backfill entra en un día de corrida por medio, y el período queda en casi 35 meses e incluye las legislativas de octubre de 2025.

## MisionesOnline

El 27/10/2026 a la mañana todo el sitio respondía 403 con un desafío de Cloudflare. A la tarde del mismo día, robots.txt y la API respondían 200 con el mismo tipo de User-Agent (`01_misionesonline` §1).

**Decisión:** MisionesOnline sigue en el proyecto. El cliente detecta un desafío y se detiene sin reintentar ni cambiar de User-Agent (lo mismo que `probe.py`). Como el backfill tarda menos de 5 minutos, conviene correrlo primero y guardar el resultado. Si el bloqueo vuelve y no se levanta en unos días, se aplican las alternativas de `docs/def.md`.

El volumen es menor que lo esperado: 7.245 notas en el período (el total de 55.895 de `def.md` es de toda la historia de la categoría), unas 50 por semana. Para la fase 5 puede convenir agregar MisionesOnline por quincena o por mes.

## Notas de agencia y reescrituras

En MisionesOnline casi no hay firmas de agencia al inicio de la nota (0 %), pero sí reescrituras de medios nacionales (`01_misionesonline` §4, 545 notas):

- 11,4 % termina con "Fuente: X": Infobae 27 notas, TN 18, Ámbito 7, Télam 4, y otros.
- 12,7 % también está en la categoría Nacionales.
- 22,6 % tiene alguna de las dos señales.
- 0,7 % enlaza a un sitio hermano (por ejemplo, argentinaforestal.com).

**Decisión:** se conservan y se marcan. El esquema suma `fuente_externa` (string, el medio citado en "Fuente: X", vacío si no hay). La sección "Nacionales" queda en `seccion`. En el informe, la comparación provincial vs nacional se hace con y sin las notas con `fuente_externa` o en Nacionales, porque una reescritura de Infobae no mide el tono propio del medio provincial.

## Notas en vivo

- Infobae: 2,2 % de la muestra (3 de 136), todas con `subtype` = `live-blogging` y "en vivo" en la URL y el título. Son más largas (mediana de 1.069 palabras frente a 811).
- La Nación: ninguna en la muestra.

**Decisión:** se conservan con una columna `es_en_vivo` (Infobae: `subtype == "live-blogging"`; La Nación: "en vivo" en la URL o el título). Quedan fuera de los agregados de `evolucion_tono` por defecto, porque mezclan muchos temas en una sola nota.

## Paywall de La Nación

En 186 notas (136 de la muestra y 50 más al azar): 181 tienen `content_code` `comun` y 5 `abierta`, todas con el cuerpo completo (mínimo de 205 palabras fuera de las notas especiales). No apareció ninguna nota con un código de acceso pago, así que **la truncación por paywall no está verificada**. Queda abierta para el EDA (T4.4): largo del cuerpo por `content_code` en el dataset completo (`03_lanacion` §6).

## Pendientes

- Paywall de La Nación (arriba).
- Si el bloqueo de MisionesOnline vuelve durante el backfill.
- Columnas nuevas en el esquema: `fuente_externa` y `es_en_vivo` (se agregan en `docs/def.md`).
- ~~Borrar `data/probe_cache/` al cerrar la fase 2~~: se borró el 27/10/2026 al cerrar la fase 3, después de armar con ella los fixtures de los tests (`tests/fixtures/sources/`).
