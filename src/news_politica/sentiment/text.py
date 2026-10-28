"""The text a sentiment model (or a human annotator) sees for one note."""

from __future__ import annotations


TERMINAL_PUNCTUATION = (".", "?", "!", "…")


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_paragraph(cuerpo: str) -> str:
    for paragraph in cuerpo.split("\n\n"):
        if paragraph.strip():
            return paragraph.strip()
    return ""


def analysis_text(titulo: str, bajada: str, cuerpo: str) -> tuple[str, str]:
    """Return `(texto, fuente_texto)` for one note.

    The text is the title plus the bajada. When the bajada is empty it is the
    title plus the first non-empty paragraph of the body; when both are empty,
    the title alone. A title that already ends in terminal punctuation
    (`.`, `?`, `!`, `…`, `...`) gets no extra period and an ellipsis is kept.
    `fuente_texto` is `bajada`, `cuerpo` or `titulo` and records which field
    completed the title.
    """
    title = _clean(titulo)
    complement, source = _clean(bajada), "bajada"
    if not complement:
        complement, source = _first_paragraph(_clean(cuerpo)), "cuerpo"
    if not complement:
        return title, "titulo"
    if not title:
        return complement, source
    separator = " " if title.endswith(TERMINAL_PUNCTUATION) else ". "
    return f"{title}{separator}{complement}", source
