"""Teste pe adapters: scraper cu HTML salvat local, cache, limitator, disc."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from clinic_agent.adapters.file_repo import FileKnowledgeRepo
from clinic_agent.adapters.httpx_site_reader import (
    canonical_url,
    extract_internal_links,
    extract_page,
    is_excluded,
    parse_sitemap,
)
from clinic_agent.adapters.memory_cache import MemoryResponseCache
from clinic_agent.adapters.memory_rate_limiter import MemoryRateLimiter
from clinic_agent.domain.models import Page, Snapshot

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

PAGE_HTML = """
<html>
  <head><title>Prețuri — Clinica Primera</title></head>
  <body>
    <nav>Acasă Servicii Contact</nav>
    <header>Meniu</header>
    <script>ga('send');</script>
    <style>body { color: red; }</style>
    <main>
      <h1>Prețuri</h1>
      <p>Consultație stomatologică: 250 RON</p>
      <p>Detartraj: 200 RON</p>
    </main>
    <form><input name="email"></form>
    <footer>© 2026 Clinica Primera</footer>
  </body>
</html>
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.clinicaprimera.ro/</loc></url>
  <url><loc>https://www.clinicaprimera.ro/preturi</loc></url>
  <url><loc>https://www.clinicaprimera.ro/politica-de-cookies</loc></url>
</urlset>
"""


# --- scraper (funcții pure, fără rețea) ------------------------------------


def test_zgomotul_din_html_dispare() -> None:
    page = extract_page("https://x.ro/preturi", PAGE_HTML)

    assert "250 RON" in page.text
    assert "ga('send')" not in page.text  # script
    assert "color: red" not in page.text  # style
    assert "Meniu" not in page.text  # header
    assert "© 2026" not in page.text  # footer
    assert page.title == "Prețuri — Clinica Primera"


def test_url_urile_cu_si_fara_slash_final_sunt_aceeasi_pagina() -> None:
    assert canonical_url("https://x.ro/about/") == canonical_url("https://x.ro/about")
    assert canonical_url("https://X.RO/about") == "https://x.ro/about"


def test_paginile_juridice_sunt_excluse() -> None:
    excluded = ("termeni-si-conditii", "politica-de-cookies", "galerie")

    assert is_excluded("https://x.ro/politica-de-cookies", excluded)
    assert is_excluded("https://x.ro/galerie/", excluded)
    assert not is_excluded("https://x.ro/preturi", excluded)
    # Regresie: potrivirea e pe segment de cale, nu pe subșir — altfel
    # „/servicii/galerie-foto-dentara" ar fi exclusă din greșeală.
    assert not is_excluded("https://x.ro/galerie-foto-dentara", excluded)


def test_sitemap_ul_se_parseaza_in_ciuda_namespace_ului() -> None:
    urls = parse_sitemap(SITEMAP_XML)
    assert len(urls) == 3
    assert "https://www.clinicaprimera.ro/preturi" in urls


def test_imaginile_din_sitemap_sunt_ignorate() -> None:
    """Regresie prinsă pe site-ul real: Squarespace listează și pozele.

    O căutare recursivă după orice element „loc" întorcea 156 de intrări
    în loc de pagini, iar scraper-ul descărca fișiere .jpg.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url>
        <loc>https://x.ro/medici</loc>
        <image:image><image:loc>https://cdn.x.ro/doctor.jpg</image:loc></image:image>
        <image:image><image:loc>https://cdn.x.ro/echipa.png</image:loc></image:image>
      </url>
    </urlset>
    """
    assert parse_sitemap(xml) == ["https://x.ro/medici"]


def test_sitemap_stricat_nu_arunca() -> None:
    assert parse_sitemap("<nu e xml") == []


def test_crawl_ul_urmareste_doar_linkuri_interne() -> None:
    html = """
    <a href="/preturi">Prețuri</a>
    <a href="https://facebook.com/clinica">Facebook</a>
    <a href="mailto:office@x.ro">Email</a>
    """
    links = extract_internal_links("https://x.ro/", html, "x.ro")
    assert links == ["https://x.ro/preturi"]


# --- cache -----------------------------------------------------------------


def test_cache_ul_numara_hit_uri_si_miss_uri() -> None:
    cache = MemoryResponseCache(ttl_seconds=60, max_entries=10)

    assert cache.get("k") is None
    cache.set("k", "răspuns")
    assert cache.get("k") == "răspuns"

    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.entries) == (1, 1, 1)
    assert stats.hit_rate == 0.5


def test_intrarile_expira() -> None:
    now = [0.0]
    cache = MemoryResponseCache(ttl_seconds=10, max_entries=10, clock=lambda: now[0])
    cache.set("k", "v")

    now[0] = 11
    assert cache.get("k") is None


def test_cache_ul_arunca_cele_mai_vechi_intrari() -> None:
    cache = MemoryResponseCache(ttl_seconds=3600, max_entries=2)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.get("a")  # „a" devine cea mai recent folosită
    cache.set("c", "3")

    assert cache.get("b") is None
    assert cache.get("a") == "1"


# --- rate limiter ----------------------------------------------------------


def test_limita_orara() -> None:
    limiter = MemoryRateLimiter(per_hour=2, per_day=100, clock=lambda: 0.0)

    assert limiter.check("ip").allowed
    assert limiter.check("ip").allowed
    verdict = limiter.check("ip")
    assert not verdict.allowed
    assert verdict.window == "hour"
    assert verdict.retry_after_seconds is not None


def test_fereastra_gliseaza() -> None:
    now = [0.0]
    limiter = MemoryRateLimiter(per_hour=1, per_day=100, clock=lambda: now[0])

    assert limiter.check("ip").allowed
    assert not limiter.check("ip").allowed

    now[0] = 3601
    assert limiter.check("ip").allowed


def test_limita_zilnica() -> None:
    now = [0.0]
    limiter = MemoryRateLimiter(per_hour=100, per_day=3, clock=lambda: now[0])

    for i in range(3):
        now[0] = i * 3700  # peste o oră între ele, deci limita orară nu se atinge
        assert limiter.check("ip").allowed

    now[0] = 4 * 3700
    verdict = limiter.check("ip")
    assert not verdict.allowed
    assert verdict.window == "day"


def test_ip_uri_diferite_au_bugete_diferite() -> None:
    limiter = MemoryRateLimiter(per_hour=1, per_day=10, clock=lambda: 0.0)
    assert limiter.check("1.1.1.1").allowed
    assert limiter.check("2.2.2.2").allowed


# --- persistare ------------------------------------------------------------


def test_snapshotul_face_dus_intors_prin_disc(tmp_path: Path) -> None:
    repo = FileKnowledgeRepo(tmp_path)
    snapshot = Snapshot.from_pages(
        [Page("https://x.ro/a", "A", "conținut cu diacritice: ă â î ș ț")], NOW
    )

    repo.save(snapshot)
    loaded = repo.load()

    assert loaded is not None
    assert loaded.id == snapshot.id
    assert loaded.pages[0].text == snapshot.pages[0].text


def test_lipsa_fisierului_nu_e_o_eroare(tmp_path: Path) -> None:
    assert FileKnowledgeRepo(tmp_path).load() is None


def test_fisier_corupt_nu_darama_pornirea(tmp_path: Path) -> None:
    (tmp_path / "snapshot.json").write_text("{ stricat", encoding="utf-8")
    assert FileKnowledgeRepo(tmp_path).load() is None


def test_scrierea_nu_lasa_fisiere_temporare(tmp_path: Path) -> None:
    repo = FileKnowledgeRepo(tmp_path)
    repo.save(Snapshot.from_pages([Page("https://x.ro/a", "A", "text")], NOW))
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]
