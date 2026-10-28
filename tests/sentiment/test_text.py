from news_politica.sentiment.text import analysis_text


def test_note_with_bajada():
    texto, fuente = analysis_text("Milei vetó la ley", "El Congreso insistirá", "Cuerpo largo.")
    assert texto == "Milei vetó la ley. El Congreso insistirá"
    assert fuente == "bajada"


def test_note_without_bajada_uses_first_paragraph_only():
    cuerpo = "\n\nPrimer párrafo.\n\nSegundo párrafo."
    texto, fuente = analysis_text("Titulo", "  ", cuerpo)
    assert texto == "Titulo. Primer párrafo."
    assert fuente == "cuerpo"
    assert "Segundo" not in texto


def test_note_with_neither_bajada_nor_body():
    assert analysis_text("Solo título", "", "") == ("Solo título", "titulo")
    assert analysis_text("Solo título", None, "  \n\n ") == ("Solo título", "titulo")


def test_title_trailing_period_is_not_doubled():
    texto, _ = analysis_text("Milei vetó la ley.", "El Congreso insistirá", "")
    assert texto == "Milei vetó la ley. El Congreso insistirá"
