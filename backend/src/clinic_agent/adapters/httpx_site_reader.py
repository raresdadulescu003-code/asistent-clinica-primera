"""Scraper-ul site-ului: httpx pentru rețea, BeautifulSoup pentru HTML.

Funcțiile de la începutul fișierului sunt pure și se testează cu HTML salvat
local, fără nicio cerere reală.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from clinic_agent.domain.models import Page

logger = logging.getLogger(__name__)

# Elemente care apar pe fiecare pagină și n-ar aduce decât zgomot repetat.
STRIPPED_TAGS = ("script", "style", "nav", "header", "footer", "form", "svg", "noscript")

MAX_CRAWL_PAGES = 60
# Plafoane care mărginesc costul. Tot conținutul intră în prompt la FIECARE
# întrebare, deci o pagină scăpată de sub control scumpește fiecare cerere,
# nu doar scraping-ul. Site-ul real: 17 pagini, ~60.000 de caractere.
MAX_PAGES = 80
MAX_PAGE_CHARS = 30_000
MAX_TOTAL_CHARS = 200_000
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


def canonical_url(url: str) -> str:
    """`/about` și `/about/` sunt aceeași pagină. Fără asta, conținutul se dublează."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def same_host(url: str, host: str) -> bool:
    """Acceptă doar paginile clinicii, inclusiv după redirect.

    SECURITATE: conținutul scrapat ajunge în system prompt. O pagină de pe alt
    domeniu — printr-un redirect, o intrare greșită în sitemap sau un site
    compromis — ar însemna ca altcineva să scrie instrucțiuni în promptul
    agentului. Comparăm gazda finală, nu pe cea cerută.
    """
    actual = urlparse(url).netloc.lower()
    expected = host.lower()
    return actual == expected or actual == expected.removeprefix("www.")


def is_excluded(url: str, excluded_slugs: Iterable[str]) -> bool:
    """Paginile juridice și galeria: 18% din tokeni pentru zero întrebări utile."""
    path = urlparse(url).path.strip("/").lower()
    segments = set(path.split("/"))
    return any(slug.lower() in segments for slug in excluded_slugs)


def extract_page(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(STRIPPED_TAGS)):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else url
    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    # Colapsăm liniile goale: altfel plătim tokeni pentru spațiere.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return Page(url=url, title=title, text="\n".join(lines))


def _local_name(tag: str) -> str:
    """Sitemap-urile folosesc namespace-uri; ne interesează doar numele local."""
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml_text: str) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    urls: list[str] = []
    for entry in root.iter():
        if _local_name(entry.tag) not in ("url", "sitemap"):
            continue
        # DOAR primul <loc> copil direct. Squarespace pune și imaginile în
        # sitemap, ca <image:image><image:loc>; o căutare recursivă după „loc"
        # ar întoarce 156 de intrări în loc de pagini și ar descărca poze.
        for child in entry:
            if _local_name(child.tag) == "loc" and child.text:
                urls.append(child.text.strip())
                break
    return urls


def extract_internal_links(base_url: str, html: str, host: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(base_url, anchor["href"])
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https") and parsed.netloc.lower() == host:
            links.append(canonical_url(absolute))
    return links


class HttpxSiteReader:
    def __init__(
        self,
        *,
        site_url: str,
        sitemap_url: str,
        excluded_slugs: tuple[str, ...],
        min_text_chars: int,
        timeout_seconds: float,
    ) -> None:
        self._site_url = site_url
        self._sitemap_url = sitemap_url
        self._excluded_slugs = excluded_slugs
        self._min_text_chars = min_text_chars
        self._timeout = timeout_seconds

    async def fetch_pages(self) -> list[Page]:
        headers = {"User-Agent": "ClinicaPrimeraBot/1.0 (+asistent informational)"}
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True, headers=headers
        ) as client:
            urls = await self._discover(client)
            return await self._fetch_all(client, urls)

    async def _discover(self, client: httpx.AsyncClient) -> list[str]:
        try:
            response = await client.get(self._sitemap_url)
            response.raise_for_status()
            urls = parse_sitemap(response.text)
            if urls:
                logger.info("sitemap: %s URL-uri descoperite", len(urls))
                return urls
        except httpx.HTTPError as exc:
            logger.warning("sitemap indisponibil (%s), trec pe crawl", exc)
        return await self._crawl(client)

    async def _crawl(self, client: httpx.AsyncClient) -> list[str]:
        """Fallback BFS din pagina principală, dacă sitemap-ul lipsește."""
        host = urlparse(self._site_url).netloc.lower()
        start = canonical_url(self._site_url)
        seen = {start}
        queue = [start]
        discovered = []

        while queue and len(discovered) < MAX_CRAWL_PAGES:
            url = queue.pop(0)
            discovered.append(url)
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            for link in extract_internal_links(url, response.text, host):
                if link not in seen:
                    seen.add(link)
                    queue.append(link)
        return discovered

    async def _fetch_all(
        self, client: httpx.AsyncClient, urls: list[str]
    ) -> list[Page]:
        host = urlparse(self._site_url).netloc.lower()
        pages: dict[str, Page] = {}
        total_chars = 0

        if len(urls) > MAX_PAGES:
            logger.warning(
                "%s URL-uri descoperite, mă opresc la %s", len(urls), MAX_PAGES
            )
            urls = urls[:MAX_PAGES]

        for url in urls:
            if is_excluded(url, self._excluded_slugs) or not same_host(url, host):
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("pagina %s nu a putut fi citită: %s", url, exc)
                continue

            # Plasă de siguranță: dacă totuși ajunge un PDF sau o imagine în
            # listă, nu are rost să-l dăm pe BeautifulSoup.
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                continue
            if len(response.content) > MAX_DOWNLOAD_BYTES:
                logger.warning("pagina %s ignorată: %s octeți", url, len(response.content))
                continue

            # Cheia e URL-ul FINAL, de după redirect — altfel /about și /about/
            # ajung două intrări cu același conținut.
            final_url = canonical_url(str(response.url))
            # Redirectul poate duce în afara domeniului clinicii; conținutul de
            # acolo ar ajunge în promptul agentului. Verificăm gazda finală.
            if not same_host(final_url, host):
                logger.warning("redirect în afara site-ului, ignorat: %s", final_url)
                continue
            if final_url in pages or is_excluded(final_url, self._excluded_slugs):
                continue

            page = extract_page(final_url, response.text)
            if page.char_count < self._min_text_chars:
                logger.info("pagina %s ignorată (%s caractere)", final_url, page.char_count)
                continue
            if page.char_count > MAX_PAGE_CHARS:
                logger.warning(
                    "pagina %s trunchiată: %s → %s caractere",
                    final_url, page.char_count, MAX_PAGE_CHARS,
                )
                page = Page(url=page.url, title=page.title, text=page.text[:MAX_PAGE_CHARS])
            if total_chars + page.char_count > MAX_TOTAL_CHARS:
                logger.error(
                    "buget de conținut depășit la %s caractere — restul paginilor "
                    "sunt ignorate. Verifică dacă site-ul a crescut neașteptat.",
                    total_chars,
                )
                break

            pages[final_url] = page
            total_chars += page.char_count

        logger.info("scraping: %s pagini utile, %s caractere", len(pages), total_chars)
        return list(pages.values())
