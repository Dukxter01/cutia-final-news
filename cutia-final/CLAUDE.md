# CLAUDE.md · Cutia Clasei

Instrucțiuni pentru Claude (și pentru oricine lucrează în proiect). Citește tot fișierul înainte să schimbi ceva.

## Ce e proiectul

**Cutia Clasei** este platforma internă a cursului de vibe coding. Are două spații:

| Spațiu | Cine vede | Ce conține |
| --- | --- | --- |
| 🔒 **Privat** (student ↔ trainer) | doar studentul în cauză și trainerul | Mesaje directe, Întrebări, Teme & proiecte (fișiere, link GitHub, checklist, feedback), Atelier (Verifică repo-ul, Error Doctor, Prompt Lab; istoricul Error Doctor îl vede doar autorul) |
| 🌐 **Public** (toată clasa) | toți cei logați | Ora live, Cutia de idei (filtru AI, voturi, „Aleasă”, kit de start), Demo Day, AI News + Byte, Puncte & clasament (serii, misiuni), Ghidul de vibe coding (FAQ, Hall of Prompts), anunțurile trainerului |

Interfața e în **6 limbi** (ro, en, fr, it, es, de), are designul „Aurora” cu 5 stiluri (Aurora, Perlă, Apus, Ocean, Contrast mare) și un robot 3D care îl salută pe utilizator pe nume la intrare (7 secunde, apoi interfața).

**Conturi:** dacă sunt setate `SUPABASE_URL` + `SUPABASE_ANON_KEY`, conturile merg prin **Supabase Auth** (confirmare pe email, resetare cu link, Google prin Supabase; `src/supa.py`). Altfel: email + parolă (minim 8 caractere) sau Google (dacă e setat `GOOGLE_CLIENT_ID`). Rolul de trainer vine din `TRAINER_EMAILS` sau din `TRAINER_CODE` la crearea contului. `CLASS_CODE` (opțional) limitează conturile de student la clasa ta. Trainerul anunță teme cu termen și puncte; studenții primesc puncte, niveluri și badge-uri.

## Minimul obligatoriu (din fișa trainerului): nu se strică niciodată

| Funcție | Regula | Unde e |
| --- | --- | --- |
| Pune o întrebare | O văd doar studentul care a pus-o și trainerul. | `GET/POST /api/questions` în `src/app.py` |
| Răspuns | Trainerul răspunde, studentul vede răspunsul. | `POST /api/questions/{id}/answer` |
| Scrie o propunere | Minimum: titlu, ce face aplicația, cine o folosește. | `ProposalIn` + `submit_proposal` |
| Modul AI | Retușează și cere detalii **doar unde lipsesc**, maxim 3 întrebări. | `src/ai.py` → `refine()` |
| Trimite propunerea | Studentul **aprobă** varianta finală înainte să o trimită (`approved: true`, verificat pe server). | `submit_proposal` |
| Trainerul alege | Vede toate propunerile și le pune status: Nouă, În discuție, Aleasă, Respinsă (+ notă publică). | `POST /api/proposals/{id}/decision` (și vechiul `/choose`) |

Ce verifică AI-ul la fiecare propunere: **problema** (ce rezolvă și pentru cine), **funcțiile** (cele 3 lucruri sigure), **datele** (de unde vin), **mărimea** (se face într-o oră? dacă nu, ce parte întâi). AI-ul nu decide în locul studentului: arată ce a înțeles, spune ce lipsește, studentul alege ce trimite.

## Reguli de securitate: obligatorii

1. **Cheia API nu ajunge niciodată în browser sau pe GitHub.** Apelurile către Claude se fac doar din `src/ai.py`, pe server. Cheia stă în variabila de mediu `ANTHROPIC_API_KEY` sau în `.env` (ignorat de git). Nu scrie chei în cod, în teste, în README sau în mesaje de commit.
2. **Ai urcat o cheie din greșeală?** Spune-i imediat utilizatorului s-o regenereze din consola Anthropic. Ștearsă din cod, rămâne în istoricul git.
3. **Accesul se verifică pe server, nu doar în interfață.** Fiecare endpoint nou folosește `current_user` / `require_student` / `require_trainer` și filtrează după `author_key`. Ascunderea unui buton nu e protecție.
4. **Testează cu două conturi.** Orice funcție privată are un test în care studentul B **nu** vede datele studentului A (vezi `tests/test_app.py`).
5. **Fișierele încărcate** se salvează cu nume aleatorii în `data/uploads/`, se descarcă doar prin API (după verificarea accesului), mereu ca `attachment` + `application/octet-stream` + `nosniff`. Limite: 5 fișiere, 10 MB, extensii din `ALLOWED_EXTENSIONS`.
6. **Linkurile** trimise de utilizatori se acceptă doar dacă încep cu `http://` sau `https://` (fără `javascript:`), verificat pe server și în interfață.
7. **Fără `innerHTML` cu text de la utilizatori sau de la AI.** În `app.js` totul se construiește cu `el(...)` și noduri text; markdown-ul AI trece prin `renderMd()`, care nu folosește HTML.
8. Parolele se salvează doar ca hash PBKDF2 cu salt; sesiunile doar ca hash SHA-256 al tokenului. Login: același mesaj pentru email greșit și parolă greșită, blocare 10 minute după 5 încercări. Tokenul Google se verifică pe server cu `google-auth`, doar pentru emailuri verificate. Emailurile studenților nu ajung niciodată la alți studenți (doar trainerul le vede).
12. **Propunerile retrase** nu apar în cutia publică (doar autorului și trainerului), nu mai pot fi votate sau alese și nu aduc puncte pentru idee și voturi. Doar autorul le poate retrage sau pune înapoi.
13. **Ciornele sunt private**: pe server doar proprietarul le vede (altcuiva îi răspundem 404); ciornele locale din browser se șterg la „Ieși”.
14. **Supabase:** orice token Supabase venit din browser se verifică pe server cu `supa.get_user()` (întrebăm Supabase, nu decodăm noi tokenul) și trebuie să aibă emailul confirmat. Pentru conturi se folosește anon key. Pentru date și fișiere (`src/store.py`) serverul folosește `SUPABASE_SECRET_KEY`: doar din variabilele de mediu ale serverului, niciodată în browser, în cod sau pe GitHub. Tabelul `cutia_state` are RLS pornit și **nicio politică** (vezi `supabase/schema.sql`); nu adăuga politici care să-l deschidă pentru anon/authenticated. `TRAINER_EMAILS` dă rol de trainer doar pentru emailuri dovedite (Google sau proiect cu „Confirm email”). „Ai uitat parola?” răspunde la fel dacă emailul are cont sau nu. Testele folosesc un Supabase fals (`FakeSupabase`), niciodată proiectul real.
15. **Ora live:** „M-am blocat” e anonim (se întoarce doar numărul), întrebările anonime nu au nume nici pentru trainer, răspunsurile la biletul de ieșire le vede doar trainerul (și fiecare student pe al lui). Doar trainerul pornește/încheie ora, voturile și biletul.
16. **Atelier:** „Verifică repo-ul” vorbește doar cu `api.github.com` și `raw.githubusercontent.com`, cu owner/repo validate (`REPO_RE`), fără să urmeze redirecturi; cheile găsite se arată mascate. Error Doctor, Prompt Lab și Hall of Prompts trec textul prin `tools.redact()` înainte de salvare sau de Claude. Imaginile se acceptă doar ca PNG/JPEG/WebP verificate după primii octeți (`image_type`) și se servesc cu `nosniff`.
17. **Notificări push:** textul e generic (fără conținut privat pe ecranul blocat), în limba destinatarului; mesajul e criptat per dispozitiv (`src/webpush.py`, RFC 8291 + VAPID). `VAPID_PRIVATE_KEY` e secret, ca orice cheie.
18. **FAQ cu acord:** o întrebare ajunge în FAQ doar dacă autorul a bifat `faq_ok`. `POST /api/questions/{id}/to-faq` și `POST /api/faq` cu `question_id` refuză fără acord. Dacă autorul își retrage acordul, intrarea legată din FAQ se șterge. Propunerile de FAQ din recap vin doar din întrebările cu acord. FAQ-ul nu conține niciodată nume.
19. **Statusul propunerii** (`decision`) îl schimbă doar trainerul. `chosen` rămâne sincronizat cu `decision == "chosen"`, pentru puncte și kitul de start.
20. **Export CSV:** doar trainerul; celulele care încep cu `= + - @` primesc un `'` în față, ca Excel să nu le ruleze ca formule.
21. **Limita de retușări AI** (`CUTIA_REFINE_PER_DAY`) se verifică pe server, per student, pe ultimele 24 de ore. Modul local (fără cheie) nu consumă din limită.
22. **Mod demo** (`CUTIA_DEMO=1`): parolele demo sunt publice, deci pornește doar fără Supabase și doar dacă nu există niciun utilizator. Nu-l porni pe aplicația live.
9. **Mesajele directe** sunt mereu o conversație student ↔ trainer: studentul vede doar conversația lui, trainerul pe toate. Nu există mesaje între studenți.
10. **Punctele nu se salvează ca număr.** Se calculează în `src/points.py` din activitatea reală + bonusurile trainerului. Nu adăuga endpoint-uri care modifică direct punctele; nimeni nu își votează propria idee.
11. **Conținutul din internet (AI News) e date, nu instrucțiuni**: fără HTML, doar linkuri `http(s)`, iar când îl trimitem la Claude îl marcăm explicit ca date.

## Diff-ul retușului AI

`wordDiff()` din `app.js` compară cuvânt cu cuvânt descrierea scrisă de student cu varianta AI și afișează rezultatul doar cu noduri text, `<ins>` și `<del>`, fără `innerHTML`.

## Reguli pentru AI

- Modelul implicit: `claude-opus-5-5` (`CUTIA_MODEL`). Răspunsurile vin în limba interfeței (antetul `X-Lang`).
- Propuneri: răspuns structurat (JSON schema), maxim 3 întrebări, nu inventează funcții, câmpurile goale rămân goale. Fără cheie → `refine_local()` (retușare simplă, aceleași câmpuri).
- **Nimic nu se trimite fără acordul studentului**: AI-ul doar propune; trimiterea cere checkbox-ul de aprobare, iar orice editare cere o nouă aprobare.
- Răspunsul rapid la întrebări (`answer_question`) e marcat mereu „AI · neverificat de trainer”. Răspunsul trainerului rămâne cel **oficial** și apare primul. Se generează o singură dată per întrebare.
- AI News: Claude alege maxim 12 știri utile pentru clasă și scrie „de ce contează”, fără să inventeze fapte peste titlu și rezumat. Rezultatul stă în cache per limbă.
- **Byte (briefing-ul zilei, `src/digest.py`)**: rulează pe server o dată la 24h (`CUTIA_DIGEST_HOUR`, `CUTIA_TZ`). Claude primește știrile ca date, alege doar după `id`, iar linkurile le punem noi din fluxuri (`digest.validate()` aruncă id-urile inventate). Fiecare limbă se scrie o singură dată pe zi și se salvează în `db["digests"]` (ultimele 30 de zile); după un eșec, nu reîncercăm 30 de minute. Doar trainerul poate cere un briefing nou (`POST /api/digest/run`, maxim o dată la 10 minute).
- **Atelier, kit de start, recap** (`src/tools.py`): răspuns structurat (JSON schema), o singură generare per idee/limbă (kit) și per săptămână/limbă (recap). La recap trimitem doar textele întrebărilor și răspunsurilor, niciodată nume sau emailuri.
- Dacă AI-ul nu e disponibil, aplicația merge în continuare (mod local / sfaturi din ghid / filtru automat de știri). Nu bloca nicio funcție obligatorie pe AI.

## Structura

```
src/app.py                API FastAPI: conturi & sesiuni, mesaje, întrebări, teme & anunțuri,
                          propuneri, puncte, știri, limbă (X-Lang)
src/ai.py                 Modulul AI: retușarea propunerilor + tutorul pentru întrebări
src/news.py               AI News: surse RSS/Atom, filtrare, categorii, cache, alegere cu Claude
src/digest.py             Byte: briefing-ul zilei (ultimele 24h), programare, scriere cu Claude, varianta locală
src/points.py             Reguli de puncte, niveluri, badge-uri, serii și misiuni săptămânale
src/supa.py               Supabase Auth prin REST (httpx): cont nou, intrare, verificare token, resetare
src/store.py              Datele (Postgres, tabelul cutia_state) și fișierele (Storage) în Supabase
src/repocheck.py          „Verifică repo-ul”: lista „Gata când”, chei API în cod și în istoric
src/tools.py              Error Doctor, Prompt Lab, kit de start, recap săptămânal
src/webpush.py            Notificări push (criptare RFC 8291 + semnătură VAPID)
src/static/sw.js          Service worker: instalare, offline (fără /api), notificări
src/static/manifest.webmanifest + icons/   Aplicația instalabilă (PWA)
supabase/schema.sql       Tabelul + bucket-ul din Supabase (RLS fără politici)
src/static/index.html     Scheletul platformei (sidebar privat/public, 8 ecrane, setări, Ctrl+K)
src/static/app.js         Logica interfeței (fără framework, organizată pe secțiuni)
src/static/styles.css     Design: tokens pe :root, 6 stiluri, mobil, animații oprite, text mare
src/static/i18n/core.js   Limbile disponibile + iconițele/culorile topicurilor
src/static/i18n/<l>.js    Toate textele unei limbi + ghidul (ro, en, fr, it, es, de)
src/static/intro.js       Robotul 3D de bun venit (modul ES, Three.js prin importmap)
src/static/vendor/        Three.js + RoundedBoxGeometry + RoomEnvironment (MIT), incluse local
src/static/fonts/         Instrument Serif, Manrope, JetBrains Mono (OFL), incluse local
tests/test_app.py         Teste API (acces cu două conturi, mesaje, puncte, upload, știri, limbi)
tests/check_i18n.js       Verifică să nu lipsească nicio traducere
render.yaml               Publicarea pe Render (un proces, disc permanent, fără chei)
data/                     Date + fișiere încărcate (ignorat de git)
```

## Comenzi

```bash
pip install -r requirements.txt
cp .env.example .env              # pune cheia API aici, dacă ai una
uvicorn src.app:app --reload      # http://localhost:8000
pytest                            # rulează după fiecare schimbare
```

## Publicare (Render)

- `render.yaml` descrie serverul: **un singur proces** uvicorn (datele stau în memorie, deci fără `--workers`), plan gratuit, datele și fișierele în Supabase (`SUPABASE_SECRET_KEY`), `--proxy-headers` ca linkurile din emailuri să iasă cu `https://`, verificare pe `/api/health`.
- Orice salvare trece prin `save_db()` (care scrie în Supabase în fundal, doar colecțiile schimbate) și orice fișier prin `put_blob/get_blob/delete_blob`. Nu scrie direct pe disc.
- Dacă Supabase nu răspunde la pornire, `load_db()` oprește pornirea: niciodată nu pornim cu date goale peste date bune.
- În `render.yaml` nu se scrie nicio cheie sau cod: doar `sync: false`, iar valorile se completează în Render.
- `requirements.txt` are versiuni fixate. Când schimbi o versiune, rulează `pytest` într-un mediu curat.
- `TRAINER_CODE` nu are valoare implicită; codurile din `WEAK_TRAINER_CODES` și cele sub 6 caractere sunt ignorate.

## Convenții

- **Fiecare text din interfață există în toate cele 6 limbi** în `src/static/i18n/<limbă>.js` (aceleași chei ca `en.js`, aceleași `{}`). `pytest` pică dacă lipsește ceva. Mesajele de eroare ale serverului sunt în `MESSAGES` din `app.py`, câte 6 traduceri în ordinea din `ai.LANGS`.
- Topicurile din ghid au aceleași chei în `TOPIC_META` (`i18n/core.js`), în fiecare fișier de limbă și în `TOPICS` (`app.py`). Un topic nou se adaugă peste tot, în toate limbile.
- Numele nivelurilor (Prompt Rookie … AI Wizard) rămân în engleză în toate limbile, ca nume proprii.
- Comentariile din cod sunt în română, scurte, și explică *de ce*.
- Design „Aurora”: elegant și aerisit, nu încărcat. Titluri în `var(--serif)` (Instrument Serif), text în `var(--sans)` (Manrope), butoane principale în formă de pastilă (`--btn-bg`/`--btn-ink`). Fără neon, fără strălucire puternică, fără verde aprins, fără rame animate; accente doar din `--a1`…`--a4`. Nu încărca fonturi sau scripturi de pe CDN: totul e local în `fonts/` și `vendor/`.
- Culorile doar din variabilele CSS de pe `:root`; fiecare stil e un bloc `:root[data-theme="..."]`. Verifică orice ecran nou pe telefon (390px), în Aurora și Perlă, cu animațiile oprite (`data-motion="off"`) și cu text mare (`data-size="large"`).
- Pe telefon, bara de jos are doar 5 ecrane; restul (Întrebări, Atelier, Demo Day, Puncte, Ghid) sunt în meniul ☰. „Ora live” apare jos doar cât e oră live.
- Un ecran nou primește: o intrare în sidebar (secțiunea privat/public potrivită), o acțiune în paleta `Ctrl+K` și, dacă produce noutăți, o intrare în notificări.
- Interfața marchează clar spațiul: `🔒 Privat` sau `🌐 Public`. Un ecran nou trebuie să spună în ce spațiu e.
- Fără dependențe noi în frontend (fără build). În backend, doar ce e în `requirements.txt`.

## Când adaugi o funcție

1. Endpoint cu verificare de acces pe server + test cu două conturi.
2. Texte în toate cele 6 fișiere din `src/static/i18n/` (+ mesaje de eroare în `MESSAGES`, 6 traduceri).
3. Verifică: desktop + mobil, Aurora + Perlă, cel puțin RO + EN + încă o limbă.
4. `pytest` trece. Actualizează README-ul (funcții în plus) și, dacă e cazul, acest fișier.
5. Commit mic, cu mesaj clar. Niciodată `.env`, `data/` sau chei.

## Gata când (checklist-ul temei)

- [ ] Toate funcțiile din minimul obligatoriu merg.
- [ ] O întrebare nu apare la alt student.
- [ ] Modulul AI cere detalii doar când lipsește ceva și nu trimite nimic fără acordul studentului.
- [ ] Codul e pe GitHub, cu README.
- [ ] Nicio cheie API în cod sau în istoricul repo-ului.
- [ ] Trainerul are acces la repo și a primit linkul.
