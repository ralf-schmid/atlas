"""Crypto-Boersenbrief (CryptoCrunch, morningcrunch.de via beehiiv) -> `newsletter_item`.

See docs/features/F102-crypto-newsletter-ingestion.md.

Same shape as F014's Musterdepot path: n8n recognises the mail by sender/subject and
POSTs it to the ATLAS webhook (src/api/routes_ingestion.py), which calls the pure
parser here and persists the result. Agents read from the DB only, never from the
mailbox (ARCHITECTURE.md §3.5).

Parsed from the mail's **text/plain** part, not the HTML one. beehiiv's plain part is
already a clean markdown-ish rendering with the links inline as `[text](url)` — the
HTML part is 4.5x larger and would need tag stripping first, for no gain. Note this
differs from the Musterdepot branch in n8n, which sends `textHtml || textPlain`.

Two things this module deliberately drops rather than stores:

- **Ad blocks.** The issue carries a paid partnership section, an `ANZEIGE` slot, and
  affiliate plugs woven into the editorial intro. A block linking to a blocked domain
  (affiliate networks, beehiiv's own subscribe/unsubscribe machinery) is dropped whole.
  Without this, CRYPTOR would read "warum ich bei HYPE long gegangen bin" as research
  and not as the ad it is.
- **The publisher's own link URLs beyond the first.** Nothing here fetches any link.
  The newsletter already summarises every linked story in 1-3 sentences — that summary
  *is* the impulse Ralf pays for. Fetching the targets would add robots.txt/paywall/
  copyright surface for a longer version of the same fact (Ralf's call, 08.08.2026).

Untrusted content (Invariant #9): everything here is publisher-controlled text that
reaches personas only as a tagged data block via the shared research pool, never as a
system prompt and never near an order tool.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import NewsletterItem
from src.orchestrator.instrument_names import load_instrument_aliases, match_instruments

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ingestion.yaml"

# `###### COIN SNAPSHOT` / `###### TOP STORY` — beehiiv renders every section label as
# an h6 in the plain part, which makes them the only reliable structural anchor.
_SECTION_RE = re.compile(r"^#{4,6}\s+(?P<name>.+?)\s*$", re.MULTILINE)
_MARKDOWN_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<url>[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"https?://\S+")
# `$BTC ( - 0.3% )` in the Coin Snapshot, `$HYPE` inline elsewhere.
_TICKER_RE = re.compile(r"\$([A-Z]{2,6})\b")
_PERMALINK_RE = re.compile(r"https://[^\s]*/p/(?P<slug>[0-9a-z\-]+)", re.IGNORECASE)
# beehiiv heading markers that survive into the plain part (`## ==Top-Story==`).
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
# Image/caption scaffolding beehiiv emits into the plain part; never content.
_SCAFFOLD_PREFIXES = ("Bild anzeigen:", "Caption:", "Du liest eine reine Textversion")
_SEPARATOR_RE = re.compile(r"^[\s—\-–_]{3,}$")
_EMPHASIS_RE = re.compile(r"(\*\*|==|__|_)")
# A block shorter than this after cleanup is a leftover caption/emoji/divider, not an
# impulse. Measured against the real issue: the shortest genuine Headlines bullet is
# ~110 chars, the longest piece of scaffolding that survives the other filters is ~25.
_MIN_ITEM_CHARS = 40
_TITLE_MAX_CHARS = 180
# One issue is ~30 items; the cap only exists so a malformed/HTML-in-plain mail can't
# write thousands of junk rows before anyone notices.
_MAX_ITEMS_PER_ISSUE = 200


@dataclass(frozen=True, slots=True)
class NewsletterImpulse:
    seq: int
    section: str
    title: str
    text: str
    url: str | None
    instruments: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NewsletterConfig:
    slug: str
    sender: str
    subject_marker: str
    drop_sections: list[str]
    blocked_link_domains: list[str]
    ticker_map: dict[str, str]
    single_item_sections: list[str]


def load_newsletters(config_path: Path = _DEFAULT_CONFIG_PATH) -> list[NewsletterConfig]:
    config = yaml.safe_load(config_path.read_text())
    return [
        NewsletterConfig(
            slug=n["slug"],
            sender=n["sender"],
            subject_marker=n.get("subject_marker", ""),
            drop_sections=[s.upper() for s in n.get("drop_sections", [])],
            blocked_link_domains=n.get("blocked_link_domains", []),
            ticker_map=n.get("ticker_map", {}),
            single_item_sections=[s.upper() for s in n.get("single_item_sections", [])],
        )
        for n in config["newsletters"]
    ]


def identify_newsletter(
    sender: str, newsletters: list[NewsletterConfig]
) -> NewsletterConfig | None:
    """Matched on the sender address, not the subject: every issue carries a different
    subject line (the day's top story), while `cryptocrunch@m6.morningcrunch.de` is
    constant. `subject_marker` stays available as an optional extra guard."""
    sender_lower = sender.lower()
    for newsletter in newsletters:
        if newsletter.sender.lower() in sender_lower:
            return newsletter
    return None


def _is_blocked(url: str, blocked_domains: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in blocked_domains)


def _extract_links(text: str) -> list[str]:
    links = [match.group("url") for match in _MARKDOWN_LINK_RE.finditer(text)]
    stripped = _MARKDOWN_LINK_RE.sub("", text)
    links.extend(match.group(0).rstrip(").,") for match in _BARE_URL_RE.finditer(stripped))
    return links


def _clean(text: str) -> str:
    """Markdown -> plain prose: link targets go away (they are kept separately), and
    beehiiv's emphasis markers (`**`, `==`, `__`) are noise once the text is a DB row."""
    text = _MARKDOWN_LINK_RE.sub(lambda m: m.group("text"), text)
    text = _BARE_URL_RE.sub("", text)
    # Headings before emphasis: `## ==Titel==` needs the `##` gone as a line prefix,
    # which no longer matches once the `==` collapse has shifted the line.
    text = _HEADING_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    text = text.replace("​", "")
    return re.sub(r"\s+", " ", text).strip(" *_-–—\t")


def _derive_title(text: str) -> str:
    """A block reads `🧘 BTC-Bottoming: $BTC ( - 0.3% ) bei $64.800. ...` after cleanup,
    so the label before the first colon is the publisher's own headline for that
    impulse. Falls back to the leading sentence where there is no such label."""
    head = text.split(". ")[0]
    colon_index = head.find(":")
    if 0 < colon_index <= _TITLE_MAX_CHARS:
        candidate = head[:colon_index].strip()
        if candidate:
            return candidate[:_TITLE_MAX_CHARS]
    return head[:_TITLE_MAX_CHARS].strip() or text[:_TITLE_MAX_CHARS]


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Returns (section_name, section_body) in document order. Text before the first
    heading is the editorial intro — it carries real impulses (the issue at hand opens
    with a Bundestag petition on the Bitcoin holding period), so it gets a synthetic
    section name rather than being discarded."""
    matches = list(_SECTION_RE.finditer(body))
    sections: list[tuple[str, str]] = []

    intro = body[: matches[0].start()] if matches else body
    if intro.strip():
        sections.append(("INTRO", intro))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group("name").strip(), body[match.end() : end]))
    return sections


def _split_blocks(section_body: str) -> list[str]:
    """Blank-line separated blocks. beehiiv wraps a long bullet onto continuation lines
    without a blank line between them, so this keeps each bullet whole."""
    blocks = []
    for raw_block in re.split(r"\n\s*\n", section_body):
        lines = [
            line
            for line in raw_block.splitlines()
            if not line.strip().startswith(_SCAFFOLD_PREFIXES)
            and not _SEPARATOR_RE.match(line.strip())
        ]
        block = "\n".join(lines).strip()
        if block:
            blocks.append(block)
    return blocks


def _resolve_instruments(
    text: str, ticker_map: dict[str, str], aliases: dict[str, str] | None = None
) -> list[str]:
    """Only tickers the config maps to a symbol ATLAS actually trades end up in
    `instruments` — that field drives the companion-item join in persona_analysis, so
    an unmapped `$JPYC` there would be a dangling reference, not information. Unmapped
    tickers still survive in `raw` for lineage.

    F107: plain-text company names are resolved on top of that, from the shared
    `config/instrument_names.yaml`. These newsletters name companies in prose far more
    often than as `$TICKER` — measured on the 2026-08-11 issues, four tickers against
    dozens of names. Tickers stay first in the list: an explicit `$LLY` is the stronger
    signal than a name mentioned in passing.
    """
    resolved = []
    for ticker in _TICKER_RE.findall(text):
        symbol = ticker_map.get(ticker)
        if symbol is not None and symbol not in resolved:
            resolved.append(symbol)
    for symbol in match_instruments(text, aliases or {}):
        if symbol not in resolved:
            resolved.append(symbol)
    return resolved


def parse_newsletter(
    text: str, newsletter: NewsletterConfig, aliases: dict[str, str] | None = None
) -> list[NewsletterImpulse]:
    """Splits one issue's plain-text body into individual impulses.

    Ad handling happens at block level and before the single-item merge, so a paid
    plug sitting inside an otherwise editorial section takes only its own block with
    it — not the whole section.

    The minimum-length filter, by contrast, runs *after* the merge for
    `single_item_sections` (F106): marketscrunch's `WHAT TO WATCH` is a calendar of
    one-line entries ("Makro: Verbraucherpreise", "Earnings: Salzgitter, Uniper"),
    each below the per-block floor but a usable impulse once merged. Filtering them
    individually first dropped the whole section.

    `aliases` defaults to the shared company-name map (F107); pass an explicit dict to
    test the matching in isolation.
    """
    if aliases is None:
        aliases = load_instrument_aliases()

    impulses: list[NewsletterImpulse] = []
    seq = 0

    for section_name, section_body in _split_sections(text):
        if any(marker in section_name.upper() for marker in newsletter.drop_sections):
            continue

        is_single_item = any(
            marker in section_name.upper() for marker in newsletter.single_item_sections
        )

        kept_blocks: list[tuple[str, list[str]]] = []
        for block in _split_blocks(section_body):
            links = _extract_links(block)
            if any(_is_blocked(link, newsletter.blocked_link_domains) for link in links):
                continue
            cleaned = _clean(block)
            if not is_single_item and len(cleaned) < _MIN_ITEM_CHARS:
                continue
            if not cleaned:
                continue
            kept_blocks.append((cleaned, links))

        if not kept_blocks:
            continue

        if is_single_item:
            merged_text = " ".join(cleaned for cleaned, _ in kept_blocks)
            merged_links = [link for _, links in kept_blocks for link in links]
            if len(merged_text) < _MIN_ITEM_CHARS:
                continue
            kept_blocks = [(merged_text, merged_links)]

        for cleaned, links in kept_blocks:
            if seq >= _MAX_ITEMS_PER_ISSUE:
                return impulses
            impulses.append(
                NewsletterImpulse(
                    seq=seq,
                    section=section_name[:100],
                    title=_derive_title(cleaned),
                    text=cleaned,
                    url=links[0] if links else None,
                    instruments=_resolve_instruments(cleaned, newsletter.ticker_map, aliases),
                    links=links,
                )
            )
            seq += 1

    return impulses


def extract_issue_url(text: str) -> str | None:
    """beehiiv closes every plain-text issue with the canonical web permalink — the one
    link worth keeping as the issue's own source reference.

    Deliberately the *last* `/p/<slug>` match, not the first: the editorial text links
    back to earlier issues of the same newsletter on the same domain, so `search()`
    returned the referenced back-issue instead of the issue at hand (live-hit on the
    2026-08-07 issue, which cites `/p/134-260716` in its top story).
    """
    matches = list(_PERMALINK_RE.finditer(text))
    return matches[-1].group(0) if matches else None


def sync_newsletter_items(
    session: Session,
    newsletter_slug: str,
    message_id: str,
    subject: str,
    issue_url: str | None,
    received_at: datetime.datetime,
    impulses: list[NewsletterImpulse],
) -> int:
    """Idempotent on (message_id, seq): a re-delivered mail (n8n retry, IMAP replay)
    updates its rows in place instead of duplicating the issue into the research pool.

    Unlike F011's publication pipeline this does *not* delete-then-insert, because
    `seq` here is assigned after all filtering, not before it — re-parsing the same
    body yields the same count, so there are no orphan high-seq rows to clean up.
    """
    if not impulses:
        return 0

    rows: list[dict[str, Any]] = [
        {
            "newsletter_slug": newsletter_slug,
            "message_id": message_id,
            "seq": impulse.seq,
            "subject": subject,
            "section": impulse.section,
            "title": impulse.title,
            "text": impulse.text,
            "url": impulse.url,
            "issue_url": issue_url,
            "instruments": impulse.instruments,
            "links": impulse.links,
            "received_at": received_at,
        }
        for impulse in impulses
    ]

    stmt = insert(NewsletterItem).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_newsletter_item_message_seq",
        set_={
            "section": stmt.excluded.section,
            "title": stmt.excluded.title,
            "text": stmt.excluded.text,
            "url": stmt.excluded.url,
            "issue_url": stmt.excluded.issue_url,
            "instruments": stmt.excluded.instruments,
            "links": stmt.excluded.links,
            "synced_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        },
    )
    session.execute(stmt)
    session.flush()
    return len(rows)
