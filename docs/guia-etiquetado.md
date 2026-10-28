# Guía de etiquetado de sentimiento

Cada integrante etiqueta 150 notas políticas (unas 1,7 horas). Las etiquetas sirven para elegir el modelo de sentimiento (ver `docs/decision-sentimiento.md`), así que importa más la consistencia que la velocidad.

## Qué se etiqueta

Se etiqueta **la valencia del texto**: si lo que se dice, tal como está redactado, es negativo, neutro o positivo. **No** se etiqueta la postura hacia el gobierno ni si el hecho le conviene a algún sector. Una nota que informa con tono neutro que el gobierno perdió una votación es `neu`; una nota que describe con lenguaje de crisis, conflicto o daño es `neg`, sin importar quién la escribe ni a quién favorece.

El texto que se ve es el título más la bajada (o el primer párrafo si no hay bajada). Se etiqueta solo ese texto, sin buscar la nota completa.

## Etiquetas

| Etiqueta | Cuándo |
|---|---|
| `pos` | El texto expresa o describe algo favorable: logros, acuerdos, mejoras, celebraciones. |
| `neu` | El texto informa sin carga valorativa clara, o mezcla aspectos favorables y desfavorables sin predominio. |
| `neg` | El texto expresa o describe algo desfavorable: conflictos, críticas, pérdidas, crisis, violencia, denuncias. |
| `descartar` | No se puede juzgar el tono: texto ilegible o cortado, sin contenido (por ejemplo solo un titular de agenda), o no es una nota (aviso, error de extracción). |

Ante la duda entre dos etiquetas, se elige la que mejor refleja la lectura de una persona que solo ve ese texto. `descartar` no es un atajo para los casos difíciles: se usa solo cuando el texto no permite juzgar.

## Ejemplos

| Texto | Etiqueta | Motivo |
|---|---|---|
| "El Senado aprobó la ley con amplio apoyo. Se destacó el acuerdo entre los bloques." | `pos` | Describe un acuerdo y un logro. |
| "El Gobierno publicó el decreto en el Boletín Oficial. Entra en vigencia mañana." | `neu` | Informa un hecho sin valoración. |
| "Fuerte caída del consumo y cierre de comercios. Comerciantes denuncian una situación crítica." | `neg` | Lenguaje de pérdida y crisis. |
| "Milei vetó la ley. El Congreso insistirá" | `neu` | Hecho institucional descrito sin carga; la postura sobre el veto no cuenta. |
| "Ver más" | `descartar` | No hay contenido. |

## Cómo completar el archivo

1. Abrir tu archivo (`anotador_a.csv` o `anotador_b.csv`) en una planilla (Excel, LibreOffice, Google Sheets). Está en UTF-8.
2. El archivo tiene tres columnas: `id`, `texto` y `etiqueta`. No tocar `id` ni `texto`.
3. Completar `etiqueta` en cada fila con exactamente una de estas cuatro palabras, en minúscula: `pos`, `neu`, `neg`, `descartar`.
4. No dejar filas vacías, no agregar ni borrar filas, no reordenar por `id`.
5. Guardar como CSV (UTF-8) con el mismo nombre y devolverlo.

El paso de unión valida el archivo y rechaza etiquetas desconocidas, vacías, ids ajenos o repetidos.

## Reglas para no sesgar las etiquetas

- No consultar la salida de ningún modelo de sentimiento antes ni durante el etiquetado.
- No ver el medio de origen: el archivo no lo incluye y no hay que buscarlo.
- No comparar etiquetas entre integrantes hasta terminar: las dos mitades no se solapan.
