# Decisión de análisis de sentimiento (fase 5)

Registro de cómo se elige el modelo de sentimiento. Este documento se completa por etapas: hoy tiene la sección "Spike" (dependencias); el cierre con números (macro F1, matriz de confusión, modelo elegido, máquina usada) se agrega en la tarea 7.3.

## Dataset congelado

La fase 5 trabaja sobre un único `data/noticias_politica.parquet`, compartido entre los integrantes y sin volver a materializarse hasta cerrar la fase: rehacerlo cambia la muestra de etiquetado y deja las etiquetas desalineadas.

- Filas: 9.261 (MisionesOnline 7.245, La Nación 1.020, Infobae 996), sin ids duplicados.
- Período: 2023-12-10 09:03 a 2026-09-30 23:37 (hora argentina).
- SHA-256: `ab5de8cbf09e7eee8418f4acf6653a2e90c38cc6f818b12ea42e45b585ebd7fc`

Para comprobar la copia local: `sha256sum data/noticias_politica.parquet`.

Limitación conocida: el 99 % de las notas de Infobae y La Nación cae en los días 4–5 y 19–20 de cada mes, porque los catálogos leen solo los sitemaps de los días 5 y 20. En la serie semanal, esos medios tienen datos en 77 de unas 147 semanas, y cada semana con datos refleja un solo día.

## Etiquetado

Las 300 notas de la muestra de validación no las etiquetaron los integrantes del equipo: las etiquetó un modelo de Anthropic, **Claude Opus 5.5** (`claude-opus-5-5`), dentro de una sesión de Claude Code, el 2026-10-29.

- **Procedimiento.** El modelo leyó el texto de cada nota en `data/etiquetado/anotador_a.csv` y `anotador_b.csv` (el mismo texto que ven los modelos de sentimiento: título más bajada, o primer párrafo) y completó `etiqueta` siguiendo `docs/guia-etiquetado.md`: valencia del texto, no postura, con `pos`, `neu`, `neg` o `descartar`. Fue una sola pasada, sin código de API, sin más ingeniería de prompts que la guía y sin revisión humana de las etiquetas.
- **Qué no vio.** Ni el medio de cada nota ni la salida de ningún modelo de sentimiento.
- **Planillas.** La división `a`/`b` se conserva solo como nombre de archivo; ambas las etiquetó el mismo modelo. Se unieron con `read_labels` en `anotaciones/etiquetas.csv` (300 filas: `id, anotador, etiqueta`) y se validaron con `load_labels`.
- **Resultado.** 134 `neg`, 121 `neu`, 45 `pos` y 0 `descartar`.

| Grupo | neg | neu | pos |
|---|---|---|---|
| Infobae | 43 | 46 | 11 |
| La Nación | 62 | 30 | 8 |
| MisionesOnline | 29 | 45 | 26 |
| Planilla a | 68 | 59 | 23 |
| Planilla b | 66 | 62 | 22 |

**Limitación.** Son etiquetas generadas por un modelo ("silver"), no verdad de terreno humana. La accuracy y el F1 macro de pysentimiento y del modelo alternativo miden, por lo tanto, **concordancia con Claude Opus 5.5**, no con una lectura humana. Claude no es uno de los modelos evaluados, así que no hay autoacuerdo. No hay control humano de las etiquetas y el acuerdo entre anotadores queda fuera del alcance. El informe debe declarar esta limitación.

## Spike

Hecho el 28/10/2026 con uv 0.11.6, Python 3.12.3 y pandas 3.1.0. Solo se tocaron PyPI, el índice CPU de PyTorch y Hugging Face; ningún pedido a los medios.

### 1.1 Resolución del lock

Grupo `sentiment` con `torch`, `transformers` y `pysentimiento`, torch desde `https://download.pytorch.org/whl/cpu` (marcador `sys_platform != 'darwin'`).

| Rango | Resultado |
| :---- | :---- |
| `requires-python = ">=3.11,<3.15"` | `uv lock` resuelve sin errores, sin necesidad de `python_version < '3.14'` en pysentimiento |

Lo que resolvió uv (bifurca por versión de Python):

| Paquete | Python 3.11 | Python 3.12 a 3.14 |
| :---- | :---- | :---- |
| pysentimiento | 0.7.3 | 0.7.3 |
| transformers | 4.57.6 | 5.21.0 |
| datasets | 2.14.4 | 5.1.0 |
| torch | 2.14.1+cpu (Linux y Windows), 2.14.1 de PyPI (macOS) | igual |
| spacy / thinc | 3.8.18 / 8.3.14 | 3.8.18 / 8.3.14 (también resuelve para 3.14) |

La resolución cubre todo el rango. El import y la predicción se probaron únicamente en 3.12 (el Python del proyecto).

### 1.2 Import y predicción con Python 3.12

`uv sync --group sentiment` instala sin problemas (unos 19 s con caché de uv). Con pandas 3.1.0, transformers 5.21.0 y torch 2.14.1+cpu:

- `import pysentimiento` funciona.
- `create_analyzer(task="sentiment", lang="es")` descarga `pysentimiento/robertuito-sentiment-analysis` y predice 5 textos (título más bajada de `noticias_politica`) con probabilidades que suman 1, por ejemplo `NEG {NEG 0.563, NEU 0.393, POS 0.044}`.
- Orden de etiquetas del checkpoint (`config.id2label`): `0: NEG, 1: NEU, 2: POS`.

**Veredicto**: se mantiene pysentimiento. Cumple las tres condiciones de la regla del diseño (decisión 3): resuelve en todo el rango, importa con pandas 3 y el transformers bloqueado, y predice los 5 textos. No hace falta el camino `AutoTokenizer` / `AutoModelForSequenceClassification`.

### 1.3 pysentimiento contra transformers directo

Se compararon 20 textos (título más bajada, 10 de Infobae y 10 de La Nación, elegidos por hash SHA-1 con sal `spike-1`, sin notas en vivo ni bajada vacía). MisionesOnline no está en el `noticias_politica.parquet` local de esta máquina, así que no entró en la comparación. El camino alternativo usa `AutoTokenizer` y `AutoModelForSequenceClassification` con softmax y `max_length=128`.

| Medidas | Resultado |
| :---- | :---- |
| Etiqueta coincidente | 20 de 20 |
| Diferencia máxima de probabilidad (por texto) | de 0,000 a 0,068 |

| # | Medio | pysentimiento | transformers | Dif. máx. probs |
| :-: | :---- | :---- | :---- | :-: |
| 1 | infobae | NEG | NEG | 0,000 |
| 2 | infobae | NEG | NEG | 0,016 |
| 3 | infobae | NEU | NEU | 0,000 |
| 4 | infobae | NEG | NEG | 0,000 |
| 5 | infobae | NEG | NEG | 0,068 |
| 6 | infobae | NEG | NEG | 0,016 |
| 7 | infobae | NEU | NEU | 0,000 |
| 8 | infobae | NEU | NEU | 0,000 |
| 9 | infobae | NEU | NEU | 0,000 |
| 10 | infobae | NEU | NEU | 0,000 |
| 11 | lanacion | NEU | NEU | 0,000 |
| 12 | lanacion | NEU | NEU | 0,000 |
| 13 | lanacion | NEU | NEU | 0,007 |
| 14 | lanacion | NEU | NEU | 0,015 |
| 15 | lanacion | POS | POS | 0,040 |
| 16 | lanacion | POS | POS | 0,000 |
| 17 | lanacion | NEG | NEG | 0,000 |
| 18 | lanacion | NEU | NEU | 0,000 |
| 19 | lanacion | POS | POS | 0,001 |
| 20 | lanacion | NEG | NEG | 0,000 |

**Conclusión**: el preprocesamiento de pysentimiento no cambia la etiqueta en ninguno de los 20 textos y mueve las probabilidades como mucho 0,068. En noticias, entonces, no es material. Con la muestra de 20 no se puede descartar una diferencia en textos con emojis, menciones o hashtags (que casi no hay en prensa); la pregunta abierta del diseño se da por respondida para este corpus.

### 1.4 Ollama: logprobs y GPU

Pendiente. Tarea humana en la máquina con GPU (RTX 4060): `ollama pull qwen2.5:7b-instruct`, pedido a `POST /api/generate` con `logprobs: true, top_logprobs: 5, num_predict: 2` y `GET /api/ps` con `size_vram > 0`. Si faltan los logprobs se aplica la salida one-hot del diseño. Hay que registrar acá la versión de Ollama y los dos resultados.
