"""F102: crypto-newsletter parsing.

The fixture below is a synthetic issue that mirrors the real CryptoCrunch structure
(section headings, bullet wrapping, ad placement, beehiiv link shapes) without
reproducing the publisher's text — CLAUDE.md keeps paid-publication full text out of
the repo, and a hand-built fixture also lets each filter be tested in isolation.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from src.db.models import NewsletterItem
from src.ingestion.crypto_newsletter import (
    NewsletterConfig,
    extract_issue_url,
    identify_newsletter,
    load_newsletters,
    parse_newsletter,
    sync_newsletter_items,
)

ISSUE = """\U0001f5f3️, liebe Cruncher!

Eine Petition zur Haltefrist hat das [Quorum geknackt](https://www.btc-echo.de/news/x-1/) – der
Bundestag muss sich damit befassen.

_Egal wie es ausgeht, handelst du alles am besten mit
__[Partner Advanced](https://partner-consumer.sjv.io/xJr7JR)___

Bild anzeigen: (https://media.beehiiv.com/uploads/asset/file/abc.png?t=1)
Caption:

———————————

###### COIN SNAPSHOT

==**\U0001f449 Crunch-Take:**== Im US-Senat steht heute eine
[Abstimmung](https://www.theblock.co/post/1/) an, danach folgt der
Arbeitsmarktbericht – Volatilitaet koennte zurueckkehren

* \U0001f9d8 **BTC-Bottoming:** $BTC ( - 0.3% )
 bei $64.800. [Whale-Bestaende wachsen](https://www.theblock.co/post/2/) seit Dezember, die
 1-Monats-Volatilitaet steht auf historischem Tief

* ⚖️ **ETH-Calming:** $ETH ( - 0.2% )
 bleibt bei $1.900. Aktive Adressen liegen bei 400.000 im 14-Tages-Schnitt

* \U0001f3ad **HYPE-Diverging:** $HYPE ( - 1.4% )
 bei $56 mit 3 % Tagesverlust. ETF-Zufluesse sind seit Juli versiegt

———————————

###### TOP STORY

## ==Tokenisierungs-Boom: Debatte ueber die Risiken==

Bild anzeigen: (https://media.beehiiv.com/uploads/asset/file/def.jpg?t=2)
Caption: Eine Bildunterschrift.

**Was ist passiert:** Waehrend die [Boersen ihre Papiere on-chain bringen](https://m6.morningcrunch.de/p/134-260716),
hat der Fonds durchgerechnet, was die neue Geschwindigkeit kostet

* **Slow by Design:** Das heutige System ist langsam, weil erst am Feierabend
 abgerechnet wird – genau diese Traegheit verschafft allen Beteiligten Zeit

———————————

###### BEZAHLTE PARTNERSCHAFT MIT PARTNER ADVANCED

## Trading Journey Week #2: Warum ich long gegangen bin

**Meine These:** Je mehr Maerkte entstehen, desto mehr Token werden gebunden – deshalb
bin ich mit kleinem Hebel long gegangen

[Direkt zum Partner!](https://partner-consumer.sjv.io/xJr7JR)

———————————

###### QUICK CATCH-UP

\U0001f3db️ **Dem Gesetz** laeuft die Zeit ab: Der Senat sollte am Freitag in die Sommerpause
gehen, das noetige Verfahren ist nicht eingeleitet. (_[Deep Dive](https://www.coindesk.com/policy/1/)_)

\U0001f6a8 **Die Aufseher** schlagen Alarm: Betrueger geben sich als lizenzierte Boersen aus
und koedern Kunden mit gefaelschten Webseiten. (_[Deep Dive](https://www.theblock.co/post/3/)_)

———————————

###### ANZEIGE

———————————

###### HEADLINES

* **Erste Boerse:** Die Kryptoboerse rollt 24/5-Handel mit fast 4.000 Aktien aus,
 provisionsfrei und ab 1 Pfund (_[Deep Dive](https://www.theblock.co/post/4/)_)

* **Zweite Firma:** Der Analyst meldet ein Rekordjahr, mit deutlich mehr gestohlenen
 Mitteln als im Vorjahr (_[Deep Dive](https://www.theblock.co/post/5/)_)

———————————

###### MORE BRIEFINGS

\U0001f4b8 **[marketscrunch:](https://magic.beehiiv.com/v1/abc?email=x@example.de)**
Dein taeglicher Overview.

\U0001f91d **[dealscrunch:](https://magic.beehiiv.com/v1/def?email=x@example.de)**
Taegliche Insights.

———————————

###### \U0001f921 WHAT DO YOU MEME?

Bild anzeigen: (https://media.beehiiv.com/uploads/asset/file/ghi.png?t=3)
Caption:

———————————

———

Du liest eine reine Textversion dieses Beitrags. Kopiere diesen Link:
https://m6.morningcrunch.de/p/150-260807
"""


@pytest.fixture
def newsletter() -> NewsletterConfig:
    """The live config, not a hand-made one — a drop_sections/ticker_map entry removed
    in config/ingestion.yaml has to fail these tests, not pass them silently."""
    configs = load_newsletters()
    return next(n for n in configs if n.slug == "cryptocrunch")


def test_config_is_loadable(newsletter: NewsletterConfig) -> None:
    assert newsletter.sender == "cryptocrunch@m6.morningcrunch.de"
    assert newsletter.ticker_map["BTC"] == "BTC/USD"


def test_identify_newsletter_matches_on_sender(newsletter: NewsletterConfig) -> None:
    configs = load_newsletters()
    assert (
        identify_newsletter("cryptocrunch <cryptocrunch@m6.morningcrunch.de>", configs)
        == newsletter
    )
    assert (
        identify_newsletter("Cryptocrunch <CRYPTOCRUNCH@M6.MorningCrunch.DE>", configs)
        == newsletter
    )
    assert identify_newsletter("noreply@boersenmedien.de", configs) is None


def test_parses_impulses_from_every_editorial_section(newsletter: NewsletterConfig) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    sections = {i.section for i in impulses}
    assert sections == {"INTRO", "COIN SNAPSHOT", "TOP STORY", "QUICK CATCH-UP", "HEADLINES"}
    assert [i.seq for i in impulses] == list(range(len(impulses)))


def test_paid_sections_are_dropped(newsletter: NewsletterConfig) -> None:
    """The single most important rule: an ad must never reach the research pool, or a
    persona reads "warum ich long gegangen bin" as an analyst impulse."""
    impulses = parse_newsletter(ISSUE, newsletter)
    joined = " ".join(i.text for i in impulses)
    assert "Trading Journey" not in joined
    assert "Meine These" not in joined
    assert not any("PARTNERSCHAFT" in i.section for i in impulses)
    assert not any("ANZEIGE" in i.section for i in impulses)
    assert not any("MORE BRIEFINGS" in i.section for i in impulses)


def test_affiliate_block_inside_editorial_intro_is_dropped(newsletter: NewsletterConfig) -> None:
    """The intro mixes a genuine impulse with an affiliate plug. The petition survives,
    the plug does not — the filter works per block, not per section."""
    impulses = parse_newsletter(ISSUE, newsletter)
    intro = [i for i in impulses if i.section == "INTRO"]
    assert len(intro) == 1
    assert "Quorum geknackt" in intro[0].text
    assert "Partner Advanced" not in intro[0].text


def test_no_blocked_link_is_ever_persisted(newsletter: NewsletterConfig) -> None:
    """magic.beehiiv.com carries Ralf's address and logs him in on click,
    unsub.beehiiv.com cancels the subscription. Neither may end up in the DB."""
    impulses = parse_newsletter(ISSUE, newsletter)
    all_links = [link for i in impulses for link in i.links] + [
        i.url for i in impulses if i.url is not None
    ]
    assert all_links, "fixture should yield links at all"
    for link in all_links:
        assert "beehiiv.com" not in link
        assert "sjv.io" not in link


def test_top_story_is_one_item_but_still_loses_its_scaffolding(
    newsletter: NewsletterConfig,
) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    top = [i for i in impulses if i.section == "TOP STORY"]
    assert len(top) == 1
    assert "Was ist passiert" in top[0].text
    assert "Slow by Design" in top[0].text
    assert "Bild anzeigen" not in top[0].text
    assert "Eine Bildunterschrift" not in top[0].text
    # beehiiv renders the top-story headline as `## ==Titel==` — the heading marker
    # must not survive into the title, or every top story is titled "##".
    assert top[0].title.startswith("Tokenisierungs-Boom")
    assert "#" not in top[0].text


def test_coin_snapshot_yields_one_item_per_bullet(newsletter: NewsletterConfig) -> None:
    """Bullets wrap onto continuation lines without a blank line between them — each
    bullet has to stay whole, including the price that sits on the wrapped line."""
    impulses = parse_newsletter(ISSUE, newsletter)
    snapshot = [i for i in impulses if i.section == "COIN SNAPSHOT"]
    assert len(snapshot) == 4  # Crunch-Take lead + BTC + ETH + HYPE
    btc = next(i for i in snapshot if "BTC-Bottoming" in i.text)
    assert "64.800" in btc.text
    assert btc.title == "\U0001f9d8 BTC-Bottoming"


def test_only_tradable_tickers_become_instruments(newsletter: NewsletterConfig) -> None:
    """$HYPE is discussed but not tradable in ATLAS — it must not create a dangling
    instrument reference that persona_analysis then tries to join companions on."""
    impulses = parse_newsletter(ISSUE, newsletter)
    btc = next(i for i in impulses if "BTC-Bottoming" in i.text)
    hype = next(i for i in impulses if "HYPE-Diverging" in i.text)
    assert btc.instruments == ["BTC/USD"]
    assert hype.instruments == []


def test_markdown_and_urls_are_stripped_from_text(newsletter: NewsletterConfig) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    for impulse in impulses:
        assert "**" not in impulse.text
        assert "==" not in impulse.text
        assert "http" not in impulse.text
        assert "](" not in impulse.text


def test_link_targets_are_kept_for_lineage(newsletter: NewsletterConfig) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    btc = next(i for i in impulses if "BTC-Bottoming" in i.text)
    assert btc.url == "https://www.theblock.co/post/2/"
    assert btc.links == ["https://www.theblock.co/post/2/"]


def test_extract_issue_url_prefers_the_footer_permalink_over_cited_back_issues() -> None:
    """The top story cites an earlier issue on the same domain — taking the first
    match would file today's impulses under a three-week-old issue URL."""
    assert extract_issue_url(ISSUE) == "https://m6.morningcrunch.de/p/150-260807"
    assert extract_issue_url("kein Permalink hier") is None


def test_markdown_emphasis_leaves_no_residue_in_titles(newsletter: NewsletterConfig) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    for impulse in impulses:
        assert not impulse.title.startswith(("#", "*", "_", "="))
        assert "_" not in impulse.title


def test_empty_body_yields_nothing(newsletter: NewsletterConfig) -> None:
    assert parse_newsletter("", newsletter) == []
    assert parse_newsletter("   \n\n  ", newsletter) == []


def test_sync_persists_and_is_idempotent(session, newsletter: NewsletterConfig) -> None:
    impulses = parse_newsletter(ISSUE, newsletter)
    received_at = datetime.datetime(2026, 8, 7, 4, 1, 35)

    written = sync_newsletter_items(
        session,
        "cryptocrunch",
        "<msg-1@example>",
        "Wall Street: Preis und Risiken",
        "https://m6.morningcrunch.de/p/150-260807",
        received_at,
        impulses,
    )
    assert written == len(impulses)

    # Re-delivery of the same mail (n8n retry / IMAP replay) must not duplicate.
    sync_newsletter_items(
        session,
        "cryptocrunch",
        "<msg-1@example>",
        "Wall Street: Preis und Risiken",
        "https://m6.morningcrunch.de/p/150-260807",
        received_at,
        impulses,
    )
    rows = session.scalars(select(NewsletterItem)).all()
    assert len(rows) == len(impulses)
    assert {row.newsletter_slug for row in rows} == {"cryptocrunch"}


def test_sync_with_no_impulses_writes_nothing(session, newsletter: NewsletterConfig) -> None:
    written = sync_newsletter_items(
        session, "cryptocrunch", "<msg-2@example>", "s", None, datetime.datetime.now(), []
    )
    assert written == 0
    assert session.scalars(select(NewsletterItem)).all() == []


# --- F106: materialscrunch / marketscrunch ---
#
# Same publisher and the same beehiiv plain-text layout as the issue above, only with
# other section names. The fixture is synthetic for the same reason as ISSUE: the real
# issues are paid-subscription content and stay out of the repo (verified separately
# against the real 2026-08-11 issues, see docs/features/F106 §5).

MARKETS_ISSUE = """\U0001f40e, liebe Cruncher!

Ein Autobauer plant eine neue Variante seines Klassikers, die Idee ist 60 Jahre alt
und die alte Umfrage dazu liest sich heute reichlich schräg.

———————————

###### **APP-PFIFF**

==Letzte Chance: Wir schließen die Waitlist für unsere App ==
_[Hier entlang zum Sign-up!](https://app.morningcrunch.de/?_bhlid=abc)_

———————————

###### WHAT TO WATCH

\U0001f1fa\U0001f1f8** Makro:** Verbraucherpreise

\U0001f4b8** Earnings:** ==Beispiel AG, Muster SE==

———————————

###### MARKET MOVER

## ==Ein Konglomerat kauft wieder zu==

**Was ist passiert:** Der neue Chef investierte im zweiten Quartal wieder in Aktien
und beendete damit eine jahrelange Verkaufsserie des Vorgängers.

* **Cash-Reserven:** Der Barbestand fiel, liegt aber weiter im dreistelligen
 Milliardenbereich und damit über dem Niveau von 2023

———————————

###### QUICK CATCH-UP

\U0001f48a Ein Pharmakonzern $LLY ( + 3.9% ) hält am neuen Werk fest und investiert
dort einen weiteren Milliardenbetrag in zusätzliche Produktionslinien.

———————————

Diese Ausgabe online: https://markets-crunch.beehiiv.com/p/151-260811
"""


@pytest.fixture
def markets() -> NewsletterConfig:
    return next(n for n in load_newsletters() if n.slug == "marketscrunch")


@pytest.fixture
def materials() -> NewsletterConfig:
    return next(n for n in load_newsletters() if n.slug == "materialscrunch")


def test_new_newsletters_are_configured(
    markets: NewsletterConfig, materials: NewsletterConfig
) -> None:
    assert markets.sender == "markets@m.morningcrunch.de"
    assert materials.sender == "hello@morningcrunch.de"
    assert "DEEP DIVE" in materials.single_item_sections
    assert "MARKET MOVER" in markets.single_item_sections


def test_identify_newsletter_separates_the_three_senders() -> None:
    configs = load_newsletters()
    cases = {
        "materialscrunch <hello@morningcrunch.de>": "materialscrunch",
        "marketscrunch <markets@m.morningcrunch.de>": "marketscrunch",
        "CryptoCrunch <cryptocrunch@m6.morningcrunch.de>": "cryptocrunch",
    }
    for sender, expected in cases.items():
        identified = identify_newsletter(sender, configs)
        assert identified is not None
        assert identified.slug == expected


def test_short_calendar_entries_survive_as_one_merged_impulse(markets: NewsletterConfig) -> None:
    """F106: `WHAT TO WATCH` is the day's macro/earnings calendar — one-liners that
    each fall below the per-block minimum. Filtering them individually dropped the
    whole section; as a `single_item_section` they merge into one usable impulse."""
    impulses = parse_newsletter(MARKETS_ISSUE, markets)

    watch = [impulse for impulse in impulses if impulse.section == "WHAT TO WATCH"]
    assert len(watch) == 1
    assert "Verbraucherpreise" in watch[0].text
    assert "Beispiel AG" in watch[0].text


def test_short_blocks_outside_single_item_sections_are_still_dropped(
    markets: NewsletterConfig,
) -> None:
    """The counterpart to the test above — the per-block floor still removes leftover
    captions and dividers everywhere else."""
    issue = MARKETS_ISSUE.replace("###### QUICK CATCH-UP", "###### QUICK CATCH-UP\n\nKurz.\n")
    impulses = parse_newsletter(issue, markets)

    assert all("Kurz." != impulse.text for impulse in impulses)


def test_single_item_section_below_the_floor_yields_nothing(markets: NewsletterConfig) -> None:
    issue = "###### WHAT TO WATCH\n\nMakro\n\nEarnings\n"

    assert parse_newsletter(issue, markets) == []


def test_app_promo_section_is_dropped(markets: NewsletterConfig) -> None:
    """APP-PFIFF is the publisher's own app waitlist ad and opens every issue."""
    impulses = parse_newsletter(MARKETS_ISSUE, markets)

    assert all("APP-PFIFF" not in impulse.section for impulse in impulses)
    assert all("app.morningcrunch.de" not in link for impulse in impulses for link in impulse.links)


def test_market_mover_section_merges_into_one_analysis(markets: NewsletterConfig) -> None:
    impulses = parse_newsletter(MARKETS_ISSUE, markets)

    mover = [impulse for impulse in impulses if impulse.section == "MARKET MOVER"]
    assert len(mover) == 1
    assert "Verkaufsserie" in mover[0].text and "Barbestand" in mover[0].text


def test_ticker_map_tags_configured_symbols(markets: NewsletterConfig) -> None:
    impulses = parse_newsletter(MARKETS_ISSUE, markets)

    tagged = [impulse for impulse in impulses if impulse.instruments]
    assert [impulse.instruments for impulse in tagged] == [["LLY"]]


def test_company_names_are_tagged_alongside_tickers(markets: NewsletterConfig) -> None:
    """F107: the newsletters name companies in prose far more often than as $TICKER —
    both mechanisms feed `instruments`, tickers first."""
    issue = MARKETS_ISSUE.replace(
        "Der neue Chef investierte",
        "Berkshire Hathaway: Der neue Chef investierte",
    )

    impulses = parse_newsletter(issue, markets)

    mover = next(impulse for impulse in impulses if impulse.section == "MARKET MOVER")
    assert mover.instruments == ["BRK.B"]
    catch_up = next(impulse for impulse in impulses if impulse.section == "QUICK CATCH-UP")
    assert catch_up.instruments == ["LLY"]


def test_explicit_alias_map_overrides_the_shared_one(markets: NewsletterConfig) -> None:
    impulses = parse_newsletter(MARKETS_ISSUE, markets, aliases={"Konglomerat": "AAPL"})

    mover = next(impulse for impulse in impulses if impulse.section == "MARKET MOVER")
    assert mover.instruments == ["AAPL"]
