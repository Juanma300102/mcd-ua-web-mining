## ADDED Requirements

### Requirement: Long-running assets log their progress
Every catalog, raw and dataset asset SHALL log at INFO a start line and a summary with the same counts as its metadata. An asset that loops over sitemaps or notes itself (the catalogs and the Arc raw assets) SHALL also log a progress line every `LOG_EVERY` (10) of them; `raw_misionesonline` paginates inside its source client and logs only the start and summary. Assets SHALL NOT log per request, nor below INFO.

#### Scenario: Arc month with 25 notes
- **WHEN** `raw_infobae` is materialized for a month that lists 25 notes
- **THEN** it logs "fetching 25 of 25 listed notes", progress at 10/25 and 20/25, and "25 notes stored, 0 lost"

#### Scenario: Catalog
- **WHEN** a catalog reads 11 sitemap days
- **THEN** it logs progress at 10/11 and at the last one, 11/11
- **AND** the asset logs a start line and a summary with its entries, failed days and dropped

#### Scenario: Dataset
- **WHEN** `noticias_politica` is materialized over one month of `raw_misionesonline` with four notes
- **THEN** it logs "parsing 1 months" and "4 rows (4 parsed, 0 parse errors)"
