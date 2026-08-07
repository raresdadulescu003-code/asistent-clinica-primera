# Asistent Clinica Primera

Chatbot informațional integrat ca widget pe site-ul unei clinici medicale.
Răspunde vizitatorilor la întrebări despre servicii, prețuri, medici,
specializări și program, folosind exclusiv conținutul public al site-ului.
Bilingv: română și engleză.

**Stack:** Python 3.11+, FastAPI, Claude Haiku 4.5, JavaScript vanilla.
Fără bază de date, fără vector store, fără build step.

---

## Ce face și ce nu face

| Face | Nu face |
|---|---|
| Răspunde despre servicii, prețuri, medici, program | Programări |
| Detectează limba și răspunde în ea | Sfaturi medicale sau diagnostice |
| Își actualizează singur informațiile, zilnic | Nu inventează ce nu e pe site |
| Streaming: textul apare pe măsură ce e generat | Nu reține conversațiile |

Când nu știe ceva, spune asta și dă datele de contact ale clinicii.

## Cum funcționează

```
Vizitator → widget (shadow DOM, pe site)
              │  POST /api/chat → Server-Sent Events
              ▼
         FastAPI ── gardieni ── cache ── Claude Haiku 4.5
              │                              ▲
              │              tot conținutul site-ului, într-un
              │              singur bloc cu prompt caching
              ▼
      scheduler: scraping zilnic + keep-alive cache
```

Un job zilnic citește site-ul, curăță HTML-ul și salvează un *snapshot*. Tot
conținutul (17 pagini, ~24.000 de tokeni) se trimite la fiecare întrebare,
într-un bloc marcat pentru cache. Nu există căutare semantică: la dimensiunea
asta, trimiterea integrală e mai ieftină și mai precisă decât RAG.

## Pornire rapidă

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"    # Linux/macOS: .venv/bin/python
cp .env.example .env                                    # completează ANTHROPIC_API_KEY
.venv/Scripts/python.exe -m uvicorn clinic_agent.api.app:create_app_from_env --factory --reload
```

La prima pornire nu există snapshot, deci scraping-ul rulează automat (~15
secunde). Până termină, `/api/chat` răspunde cu `503`.

Widget de test: <http://localhost:8000/widget/demo.html>

## Structura proiectului

Arhitectură **ports & adapters**: miezul aplicației nu știe că există Anthropic,
httpx sau discul. Un test parsează AST-ul și rupe build-ul dacă granițele sunt
încălcate.

```
backend/src/clinic_agent/
├── domain/      pur, zero I/O — modele, normalizare, prompt, cost, filtru
├── ports/       interfețe (typing.Protocol)
├── adapters/    Anthropic, httpx + BeautifulSoup, disc, memorie, FakeLLM
├── services/    ChatService, KnowledgeService — logica de business
├── api/         rute subțiri, injecție de dependențe, contractul SSE
└── config/      setări grupate pe domenii
```

`create_app(settings, *, llm=..., site_reader=..., repo=...)` e o funcție-fabrică:
testele construiesc o aplicație completă care nu atinge nici rețeaua, nici ceasul.

## Decizii de proiectare

### Costul

Trei mecanisme, cu cifre măsurate în producție pe un bloc de 24.195 de tokeni:

| Operațiune | Cost |
|---|---|
| Scriere în cache (TTL 1h) | 4,84 cenți |
| Citire din cache | 0,24 cenți |
| Un răspuns generat | ~0,03 cenți |

1. **Prompt caching** — conținutul se procesează o dată, apoi se citește la o
   zecime din preț.
2. **Keep-alive** — o citire resetează TTL-ul, deci un job trimite la fiecare 50
   de minute o cerere cu `max_tokens=0`. Costă 0,24 cenți și evită o rescriere
   de 4,84.
3. **Cache de răspunsuri** — întrebările de deschidere se repetă masiv; a doua
   persoană care întreabă „care e programul?" nu atinge deloc API-ul.

### Cheia de cache

```
cheie = hash(snapshot_id + prompt_version + întrebare_normalizată)
```

Amprenta conținutului și versiunea promptului fac parte din cheie, nu doar
întrebarea. Consecința: o cerere pornită înainte de o actualizare de conținut
scrie sub o cheie care nu mai e citită niciodată, iar modificarea instrucțiunilor
invalidează automat răspunsurile vechi. Două categorii de bug rezolvate
structural, fără sincronizare.

Se memorează doar **primul mesaj** al unei conversații (un follow-up depinde de
context) și doar întrebări sub **200 de caractere** (cele lungi sunt unicate și
pot conține date personale).

### Filtrul de întrebări din alt domeniu

Prinde întrebările vădit fără legătură cu clinica — vreme, sport, glume, cereri
de cod — și răspunde instantaneu, fără apel către model. Motivul e experiența,
nu costul: un răspuns fix e identic de fiecare dată și vine imediat.

Filtrul e **îngust deliberat**. Un fals pozitiv costă infinit mai mult decât cele
0,28 de cenți economisite, așa că `primar` nu e pe lista de termeni politici
(există „medic primar"). Un test verifică explicit că 16 întrebări legitime nu
sunt prinse.

## API

`POST /api/chat` — primește `{"messages": [{"role": "user", "content": "..."}]}`,
răspunde cu `text/event-stream`:

```
data: {"type": "token", "text": "..."}
data: {"type": "done"}
data: {"type": "error", "message": "..."}
```

Gardieni, în ordine, înainte de orice apel către model:

| Condiție | Răspuns |
|---|---|
| Bază de cunoștințe goală | `503` |
| Peste 24 de mesaje | `400` |
| Peste 30/oră sau 150/zi de la același IP | `429` |
| Întrebare din alt domeniu | răspuns fix, fără apel |
| Răspuns în cache | servit gratuit |

`GET /api/health` — stare, vârsta conținutului, eșecuri consecutive de scraping,
statistici de cache.

`POST /api/refresh` — actualizare manuală, protejată cu token.

## Configurare

Toate setările au valori implicite rezonabile; în `.env` se pun doar cele care
diferă. Vezi [.env.example](backend/.env.example).

| Variabilă | Implicit |
|---|---|
| `ANTHROPIC_API_KEY` | — (obligatorie) |
| `SERVER_ALLOWED_ORIGINS` | domeniile clinicii (niciodată `*`) |
| `SCRAPER_INTERVAL_HOURS` | `24` |
| `RATE_LIMIT_PER_HOUR` / `_PER_DAY` | `30` / `150` |
| `ANTHROPIC_KEEPALIVE_MINUTES` | `50` |

## Teste

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
```

178 de teste, toate offline. **Niciunul nu apelează API-ul Anthropic** — testele
injectează `FakeLLM` prin constructor.

Evaluarea pe model real e separată și rulează doar manual:

```bash
cd backend && RUN_EVAL=1 python evals/run_eval.py
```

## Publicare

Instrucțiuni complete: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Două cerințe nu sunt negociabile: **HTTPS** (altfel browserul blochează cererile
ca *mixed content*, și o face tăcut) și un host care **nu adoarme** (pe tier-ul
gratuit, scheduler-ul moare odată cu procesul). Se rulează cu **un singur
worker** — cache-ul, limitatorul și conținutul stau în memorie.

## Confidențialitate

Contextul e o clinică medicală, deci vizitatorii vor scrie simptome în chat.

**Nu se stochează nimic.** Conversațiile trăiesc doar în browserul vizitatorului
și în memoria cererii curente. Nu se scriu în bază de date, nu se scriu în
fișiere, nu se loghează textul întrebărilor. E o decizie deliberată de
conformitate, nu o simplificare.

Cache-ul de răspunsuri reține doar **amprenta** întrebării (un hash), nu textul
ei, iar întrebările peste 200 de caractere nu ajung niciodată în el. Pentru
limitarea de trafic se reține temporar adresa IP, în memorie, maximum 24 de ore.
Widget-ul nu folosește cookie-uri.

Mesajele sunt procesate de un furnizor extern pentru generarea răspunsului.
Politica de confidențialitate a site-ului trebuie completată corespunzător
înainte de punerea în funcțiune.
