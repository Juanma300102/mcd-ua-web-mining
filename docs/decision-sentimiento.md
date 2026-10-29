# Decisión de análisis de sentimiento (fase 5)

Registro de cómo se elige el modelo de sentimiento. El documento tiene tres partes: el etiquetado de la muestra, el spike de dependencias y la evaluación con la decisión del modelo (al final).

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

Hecho el 29/10/2026 en la máquina con GPU (NVIDIA GeForce RTX 4060 Laptop, 8 GB, WSL2), con Ollama 0.24.0 en el servicio `ollama` de `docker-compose.yaml` (perfil `ollama`, GPU reservada) y el modelo `qwen2.5:7b-instruct` (4,7 GB).

- **Logprobs:** `POST /api/generate` con `logprobs: true`, `top_logprobs: 3`, `num_predict: 2`, `temperature: 0` y `seed: 42` devuelve `logprobs`, y el primer token generado es el dígito de la respuesta, con los tres dígitos entre sus `top_logprobs`. Se usa el camino de probabilidades del diseño; la salida one-hot queda solo como respaldo.
- **GPU:** `GET /api/ps` informa `size_vram` = `size` = 4,92 GB: el modelo corre entero en la GPU.
- **Prueba con el código del proyecto:** `SentimentModels.alternative()` eligió `qwen2.5-7b` sin configuración extra. Sobre los tres ejemplos de la guía de etiquetado devolvió (pos, neu, neg): suba de la pobreza → neg 1,00; ley aprobada con amplio apoyo → pos 0,94; decreto publicado en el Boletín Oficial → neu 1,00.

## Evaluación y decisión

Las métricas salen del notebook `notebooks/05_sentimiento.ipynb` (sección "Evaluación"). No se volvió a puntuar la muestra: se evalúa desde `data/sentimiento_noticias.parquet`, que tiene los tres modelos sobre las 9.261 notas, y se filtra a las 300 notas etiquetadas. Se excluyen las notas `descartar` (0 en esta muestra). Todas las cifras miden concordancia con las etiquetas de Claude Opus 5.5 (ver "Etiquetado"), no con una lectura humana.

### Máquina y modelos

- **Máquina:** Linux sobre WSL2, NVIDIA GeForce RTX 4060 Laptop de 8 GB, Ollama 0.24.0 en el servicio `ollama` de `docker-compose.yaml`.
- **Alternativa elegida por el código:** `SentimentModels.alternative()` eligió `qwen2.5-7b` (Ollama alcanzable, modelo descargado, `size_vram > 0`).
- **`mdeberta-xnli`:** se corrió aparte, a mano, en la misma máquina y en CPU, como el respaldo que `alternative()` usaría sin GPU. Se incluye para comparar los tres.
- Los tres modelos puntuaron las 9.261 notas, sin etiquetas faltantes.

### Métricas por modelo

| Modelo | n | Exactitud | F1 macro | F1 pos | F1 neu | F1 neg |
|---|---|---|---|---|---|---|
| **robertuito** | 300 | **0,703** | **0,686** | **0,623** | 0,676 | **0,757** |
| mdeberta-xnli | 300 | 0,603 | 0,579 | 0,493 | 0,500 | 0,744 |
| qwen2.5-7b | 300 | 0,580 | 0,549 | 0,576 | 0,659 | 0,412 |

### Matrices de confusión

Filas: etiqueta. Columnas: predicción del modelo (no hubo salidas sin interpretar).

| robertuito | neg | neu | pos |
|---|---|---|---|
| neg | 95 | 39 | 0 |
| neu | 21 | 92 | 8 |
| pos | 1 | 20 | 24 |

| mdeberta-xnli | neg | neu | pos |
|---|---|---|---|
| neg | 96 | 20 | 18 |
| neu | 25 | 49 | 47 |
| pos | 3 | 6 | 36 |

| qwen2.5-7b | neg | neu | pos |
|---|---|---|---|
| neg | 35 | 97 | 2 |
| neu | 1 | 120 | 0 |
| pos | 0 | 26 | 19 |

### Por medio (F1 macro, exactitud entre paréntesis; 100 notas por medio)

| Modelo | Infobae | La Nación | MisionesOnline |
|---|---|---|---|
| **robertuito** | **0,776** (0,79) | **0,618** (0,64) | **0,672** (0,68) |
| mdeberta-xnli | 0,541 (0,58) | 0,614 (0,68) | 0,562 (0,55) |
| qwen2.5-7b | 0,527 (0,60) | 0,532 (0,49) | 0,600 (0,65) |

### Con y sin bajada

El texto de análisis es la bajada para 274 de las 300 notas y el primer párrafo del cuerpo para 26 (ninguna cayó en el título solo). Con n = 26, el grupo "cuerpo" tiene mucho ruido.

| Modelo | Fuente | n | Exactitud | F1 macro |
|---|---|---|---|---|
| robertuito | bajada | 274 | 0,719 | 0,697 |
| robertuito | cuerpo | 26 | 0,538 | 0,550 |
| mdeberta-xnli | bajada | 274 | 0,602 | 0,575 |
| mdeberta-xnli | cuerpo | 26 | 0,615 | 0,612 |
| qwen2.5-7b | bajada | 274 | 0,573 | 0,543 |
| qwen2.5-7b | cuerpo | 26 | 0,654 | 0,619 |

### Decisión: `robertuito`

Se elige **robertuito** (`MODELO_FINAL = "robertuito"` en `src/news_politica/defs/sentiment.py`):

- Tiene el mejor F1 macro (0,686) y la mejor exactitud (0,703) en el total y el mejor F1 macro en cada uno de los tres medios (en La Nación `mdeberta-xnli` queda casi empatado: 0,614 contra 0,618).
- Los otros dos tienen sesgos sistemáticos. `qwen2.5-7b` tiende a `neu`: predice neutro en 243 de 300 notas de la muestra (7.426 de 9.261 en el corpus) y manda 97 de las 134 notas `neg` a `neu`, por eso su F1 de `neg` es 0,412. `mdeberta-xnli` tiende a `pos`: 101 de 300 predicciones (4.220 de 9.261 en el corpus) y 47 de las 121 notas `neu` pasan a `pos`, lo que hunde su F1 de `neu` (0,500).
- No necesita Ollama ni GPU: corre en CPU con el grupo `sentiment`.

La diferencia con la alternativa que `alternative()` eligió es de 0,137 de F1 macro, mucho más que el ruido esperable con 300 notas.

### Advertencias

- **Cambio de dominio.** robertuito se entrenó con tweets en español; se usa sobre titulares y bajadas de prensa. Que rinda mejor que los otros dos en esta muestra no garantiza que lo haga bien en otros textos. Su error principal es pasar a `neu` notas que la etiqueta marca como `neg` (39 de 134) o `pos` (20 de 45), es decir, tiende a subestimar el tono.
- **Deriva por la bajada.** La bajada no está en todas las notas: cuando falta, el texto de análisis pasa a ser el primer párrafo del cuerpo, un texto distinto. En la muestra robertuito rinde peor sobre "cuerpo" (F1 macro 0,550 contra 0,697), aunque con 26 notas no es concluyente. En las series semanales, `prop_bajada` permite ver si un cambio de tono coincide con un cambio en la cobertura de la bajada.
- **Etiquetas "silver".** Las etiquetas las generó un modelo, no personas, y no hay control humano ni acuerdo entre anotadores. Todas las métricas son concordancia con Claude Opus 5.5 y el informe debe declararlo (ver "Etiquetado").
- **Muestra chica.** 300 notas, 100 por medio; las diferencias entre medios (por ejemplo, el mejor desempeño en Infobae) no se deben leer como finas.
