"""Scraping clients for the three outlets (phase 3).

Arc outlets (Infobae, La Nación) are listed with build_catalog() and fetched
note by note with fetch_story(); MisionesOnline is fetched a month at a time
with fetch_month(). Both return RawDoc, and the assets turn raw documents into
dataset rows with parse().
"""

from news_politica.sources.http import TooManyLosses

MAX_LOSS_SHARE = 0.10


def check_losses(docs, max_share=MAX_LOSS_SHARE):
    """Number of raw documents with an error; raises TooManyLosses above max_share of them."""
    losses = sum(1 for doc in docs if doc.error)
    if docs and losses / len(docs) > max_share:
        raise TooManyLosses(f"{losses} of {len(docs)} notes lost (more than {max_share:.0%})")
    return losses
