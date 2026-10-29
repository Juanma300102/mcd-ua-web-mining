# Presentación (15 minutos)

Diapositivas del proyecto en claude.ai: https://claude.ai/artifact/XPKkUuYY2cjKZwV46GLhXr

El link es privado hasta que su dueño lo comparte desde el menú Share de la página. Desde ahí también se exporta a PowerPoint (.pptx) o PDF.

Esta carpeta guarda la fuente de la presentación, en el formato del tipo Slides:

- `project/deck.json`: título, orden de las 16 diapositivas y secciones.
- `project/slides/<id>.html`: una diapositiva por archivo, con las notas del orador en el `<aside>` final.

Las dos capturas de Dagster (`/_blob/...`) están subidas a la presentación; sus originales están en `docs/img/`. Las cifras salen del bloque de datos de `docs/informe.html` (`scripts/build_report.py`) y del dataset (`data/noticias_politica.parquet`).

Orden (16 diapositivas): portada, medios, datos, pipeline, tecnologia, procesamiento, assets, ml, tiempo, comparacion, modelos, hitos, provincial, limites, cierre, preguntas.
