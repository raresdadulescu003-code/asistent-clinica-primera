# Deployment

Botul trebuie să ruleze non-stop, pe o adresă publică, pe HTTPS.

---

## Două cerințe blocante

### 1. HTTPS obligatoriu

Site-ul clinicii e pe HTTPS. Dacă backend-ul răspunde pe HTTP, browserul
blochează cererile ca *mixed content* — și o face **tăcut**: widget-ul apare,
arată perfect, dar niciun mesaj nu pleacă și nu se vede nicio eroare în
interfață. E cel mai greu mod de a depana.

Orice host modern dă HTTPS gratuit. `data-api-url` din snippet trebuie să
folosească `https://`. Widget-ul verifică asta la pornire și refuză să se
încarce dacă găsește `http://` pe o pagină `https://`, cu un mesaj în consolă.

### 2. Hostingul nu are voie să adoarmă

Tier-ul gratuit Render oprește procesul după 15 minute de inactivitate.
Consecințele sunt mai grave decât par:

- primul vizitator după pauză așteaptă 30–50 de secunde și pleacă;
- **scheduler-ul moare odată cu procesul.** Nu mai rulează nici keep-alive-ul
  de cache (deci se plătește o rescriere de 4,84 cenți la fiecare trezire), nici
  scraping-ul programat. Botul ar servi prețuri vechi la nesfârșit, fără ca
  cineva să observe.

---

## Ce plan să alegi

| Opțiune | Preț/lună | Ce presupune |
|---|---|---|
| **Render, plan Starter** | ~7 USD | Cel mai simplu. Conectezi repo-ul GitHub, Render detectează Python, îi dai comanda de pornire, pui variabilele în panou. HTTPS și restart la crash automat. Recomandat dacă vrei să termini repede. |
| **Railway** | ~5 USD | Similar cu Render, facturare la consum. Aceleași avantaje. |
| **VPS (Hetzner, DigitalOcean)** | ~5 EUR | Control total, dar necesită instalarea manuală a Python, `systemd` pentru repornire automată și Caddy sau nginx pentru HTTPS. |

**Recomandat: Render Starter** — cel mai mic efort de administrare pentru
aceleași garanții (HTTPS, repornire la crash, proces care nu adoarme).

---

## Render, pas cu pas

1. Urcă proiectul pe GitHub. Verifică întâi că `.env` **nu** e în repo:
   ```bash
   git check-ignore -v backend/.env
   ```
   Dacă nu afișează nimic, `.env` NU e ignorat — oprește-te și rezolvă.

2. Render → **New** → **Web Service** → conectează repo-ul.

3. Setări:

   | Câmp | Valoare |
   |---|---|
   | Root Directory | `backend` |
   | Build Command | `pip install -r requirements.txt && pip install -e . --no-deps` |
   | Start Command | `uvicorn clinic_agent.api.app:create_app_from_env --factory --host 0.0.0.0 --port $PORT --workers 1` |
   | Instance Type | **Starter** (nu Free) |

4. **Environment** → adaugă variabilele. Nu urca niciodată fișierul `.env`
   pe server; panoul host-ului e locul lor.

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   SERVER_ALLOWED_ORIGINS=https://www.clinicaprimera.ro,https://clinicaprimera.ro
   SERVER_REFRESH_TOKEN=<generează cu: python -c "import secrets;print(secrets.token_urlsafe(32))">
   ENVIRONMENT=production
   ```

5. Deploy. Apoi verifică:
   ```bash
   curl https://BACKEND.onrender.com/api/health
   ```
   Trebuie să vezi `"status": "ok"` și `page_count: 17`. Prima pornire durează
   ~15 secunde în plus, cât rulează scraping-ul inițial.

6. **Persistent Disk** (opțional, ~1 USD): montează un disc la
   `/opt/render/project/src/backend/data`. Fără el, snapshot-ul se pierde la
   fiecare redeploy și botul face un scraping în plus la pornire — supărător,
   dar nu grav.

---

## De ce un singur worker

`--workers 1` nu e o omisiune. Cache-ul de răspunsuri, limitatorul de trafic și
conținutul site-ului stau în memoria procesului. Cu doi workeri ai două
cache-uri independente: rata de acoperire se înjumătățește, limita de 30 de
mesaje pe oră devine 60, iar scheduler-ul ar rula de două ori, plătind două
keep-alive-uri.

Un worker duce fără probleme traficul unei clinici. Dacă vreodată devine
insuficient, soluția e Redis pentru starea partajată — nu mai mulți workeri cu
stare în memorie.

---

## Instalarea widget-ului pe site

Squarespace → **Settings** → **Advanced** → **Code Injection** → caseta
**Footer**:

```html
<script
  src="https://BACKEND.onrender.com/widget/widget.js"
  data-api-url="https://BACKEND.onrender.com"
  data-title="Asistent Clinica Primera"
  data-lang="ro"
  defer></script>
```

Înlocuiește `BACKEND.onrender.com` cu domeniul real, în **ambele** locuri.
`defer` face ca scriptul să nu blocheze randarea paginii.

Culorile și fontul sunt deja cele ale site-ului (`#05534E`, crem `#F7F0DB`,
Montserrat) — nu trebuie setate. Se pot suprascrie cu `data-accent`,
`data-surface` și `data-font` dacă identitatea vizuală se schimbă.

După Save, deschide site-ul și verifică:

- [ ] butonul de chat apare în dreapta-jos;
- [ ] panoul se deschide și afișează mesajul de întâmpinare;
- [ ] cele patru butoane sugerate răspund;
- [ ] o întrebare scrisă manual primește răspuns care apare cuvânt cu cuvânt;
- [ ] pe telefon: tastatura nu acoperă câmpul de scris;
- [ ] în consola browserului (F12) nu apar erori CORS.

Dacă apar erori CORS, `SERVER_ALLOWED_ORIGINS` nu conține exact originea
site-ului. Atenție: `https://www.clinicaprimera.ro` și
`https://clinicaprimera.ro` sunt origini **diferite** — trebuie amândouă.

---

## După instalare

- Verifică `/api/health` peste 24 de ore: `age_hours` trebuie să fie sub 24 și
  `consecutive_failures` să fie 0.
- Urmărește `cache.hit_rate` după o săptămână de trafic. Sub 0,3 înseamnă că
  vizitatorii pun întrebări foarte variate — normal, dar costul crește.
- Pune un monitor extern gratuit (UptimeRobot) pe `/api/health`, la 15 minute.
  Te anunță pe email dacă botul cade.
