# Decisión de análisis de sentimiento (fase 5)

Registro de cómo se elige el modelo de sentimiento. Este documento se completa por etapas: hoy tiene la sección "Spike" (dependencias); el cierre con números (macro F1, matriz de confusión, modelo elegido, máquina usada) se agrega en la tarea 7.3.

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
