from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from clinic_agent.domain.models import (
    ChatTurn,
    Page,
    Snapshot,
    is_opening_question,
    last_user_message,
)

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def page(url: str, text: str = "conținut") -> Page:
    return Page(url=url, title=url, text=text)


def test_snapshotul_e_imutabil() -> None:
    snapshot = Snapshot.from_pages([page("/a")], NOW)
    with pytest.raises(Exception):
        snapshot.id = "altceva"  # type: ignore[misc]


def test_acelasi_continut_da_aceeasi_amprenta() -> None:
    # Un scraping care nu a schimbat nimic nu trebuie să invalideze cache-ul.
    first = Snapshot.from_pages([page("/a"), page("/b")], NOW)
    second = Snapshot.from_pages([page("/a"), page("/b")], NOW + timedelta(days=1))
    assert first.id == second.id


def test_ordinea_paginilor_nu_conteaza() -> None:
    forward = Snapshot.from_pages([page("/a"), page("/b")], NOW)
    reverse = Snapshot.from_pages([page("/b"), page("/a")], NOW)
    assert forward.id == reverse.id
    assert [p.url for p in reverse.pages] == ["/a", "/b"]


def test_continut_schimbat_da_alta_amprenta() -> None:
    before = Snapshot.from_pages([page("/preturi", "250 RON")], NOW)
    after = Snapshot.from_pages([page("/preturi", "300 RON")], NOW)
    assert before.id != after.id


def test_snapshot_gol() -> None:
    empty = Snapshot.from_pages([], NOW)
    assert empty.is_empty
    assert empty.total_chars == 0


def test_varsta_snapshotului() -> None:
    snapshot = Snapshot.from_pages([page("/a")], NOW)
    assert snapshot.age(NOW + timedelta(hours=30)) == timedelta(hours=30)


def test_doar_primul_mesaj_e_intrebare_de_deschidere() -> None:
    opening = [ChatTurn("user", "Care e programul?")]
    follow_up = [
        ChatTurn("user", "Cat costa un detartraj?"),
        ChatTurn("assistant", "..."),
        ChatTurn("user", "Si albirea?"),
    ]
    assert is_opening_question(opening)
    assert not is_opening_question(follow_up)
    assert not is_opening_question([])


def test_ultimul_mesaj_al_utilizatorului() -> None:
    turns = [
        ChatTurn("user", "prima"),
        ChatTurn("assistant", "raspuns"),
        ChatTurn("user", "a doua"),
    ]
    assert last_user_message(turns) == "a doua"
    assert last_user_message([]) is None
