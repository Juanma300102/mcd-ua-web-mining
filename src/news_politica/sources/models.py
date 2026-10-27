"""What the clients return: catalog entries, raw documents and parsed articles."""

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class CatalogEntry:
    """A Política URL listed in an Arc daily sitemap."""

    medio: str
    url: str
    url_date: date
    lastmod: str
    sitemap_day: date


@dataclass(frozen=True)
class Catalog:
    entries: list[CatalogEntry]
    failed_days: list[date] = field(default_factory=list)
    dropped: int = 0


@dataclass(frozen=True)
class RawDoc:
    """One note as the source returned it: the story or post JSON, or the reason it is missing."""

    medio: str
    url: str
    final_url: str
    status: int
    fetched_at: datetime
    payload: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Article:
    """One row of the dataset (schema in docs/def.md)."""

    id: str
    medio: str
    url: str
    fecha_publicacion: datetime
    titulo: str
    bajada: str
    cuerpo: str
    autor: str
    seccion: str
    tags: list[str]
    fuente_externa: str
    es_en_vivo: bool
    fecha_scraping: datetime
