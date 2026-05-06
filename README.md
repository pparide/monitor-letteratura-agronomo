# monitor-letteratura-agronomo

Motore automatico per la sorveglianza settimanale della letteratura scientifica e delle risorse continuative gratuite per lo Studio dell'Agronomo Paride Porpora (Salerno).

**Strato 2** dell'architettura ibrida — la knowledge base concettuale (strato 1) vive in `Agronomo_Claude/monitoraggio-letteratura/` sul Mac di Paride.

---

## Cosa fa

Ogni lunedì alle 7:00 UTC il workflow GitHub Actions:

1. **Legge** `config/sources.json` (riviste OA, autori-chiave, query strutturate, RSS feeds).
2. **Interroga** OpenAlex + CrossRef + EuropePMC + RSS feeds delle riviste.
3. **Deduplica** i risultati per DOI.
4. **Filtra** i paper già visti (presenti in `config/seen.json`).
5. **Punteggia** ogni paper applicando `config/rules.json` (keyword × pesi + bonus OA + bonus autore-chiave + bonus citazioni).
6. **Genera** `digest/<aaaa-Wnn>_digest.md` raggruppato per area, ordinato per score.
7. **Aggiorna** `seen.json` e committa il digest.

Paride apre il digest su Obsidian (via `git pull` nella cartella locale `Agronomo_Claude/monitoraggio-letteratura/digest/repo/`), fa triage in 10-15 minuti, scarica i PDF promettenti in `_inbox/`, Cowork li indicizza in sessione successiva.

---

## Struttura

```
monitor-letteratura-agronomo/
├── README.md                          ← sei qui
├── .gitignore
├── requirements.txt                   · python deps minime: requests + feedparser
├── .github/workflows/
│   └── weekly-digest.yml              · cron lunedì 7:00 UTC + workflow_dispatch
├── src/
│   ├── main.py                        · entry point
│   ├── fetchers/
│   │   ├── openalex.py                · API api.openalex.org/works
│   │   ├── crossref.py                · API api.crossref.org/works
│   │   ├── europepmc.py               · API ebi.ac.uk/europepmc/webservices/rest/search
│   │   └── rss_journals.py            · feedparser su RSS riviste OA
│   ├── scoring.py                     · applica rules.json
│   ├── deduplicate.py                 · per DOI o (title, year)
│   ├── digest_writer.py               · genera markdown
│   └── seen.py                        · gestisce seen.json
├── config/
│   ├── sources.json                   · 4 riviste + 5 autori + 5 query (Fase 1)
│   ├── rules.json                     · scoring per area (verde_urbano, vta)
│   └── seen.json                      · DOI già processati (cumulativo)
├── digest/
│   └── <aaaa-Wnn>_digest.md           · output committato dal workflow
└── tests/
    └── test_smoke.py                  · smoke test E2E
```

---

## Setup (one-time)

### 1. Crea il repo su GitHub

```bash
# Sul tuo Mac
cd ~/repo                                    # o dove tieni i tuoi repo
mkdir monitor-letteratura-agronomo
cd monitor-letteratura-agronomo

# Copia qui dentro tutto il contenuto di
# Agronomo_Claude/_monitor-letteratura-bootstrap/

git init -b main
git add .
git commit -m "Initial commit: bootstrap Fase 1 (4 riviste + 5 autori + 5 query)"

# Su github.com crea il repo `pparide/monitor-letteratura-agronomo`
# e poi:
git remote add origin https://github.com/pparide/monitor-letteratura-agronomo.git
git push -u origin main
```

### 2. Verifica che il workflow sia abilitato

Su GitHub: `Settings → Actions → General → Allow all actions and reusable workflows`.

### 3. Trigger manuale del primo digest

Su GitHub: `Actions → Weekly Literature Digest → Run workflow → Branch: main → Run`.

Tempo atteso: ~3-5 minuti. Al termine vedrai un commit automatico con `digest/<aaaa-Wnn>_digest.md`.

### 4. Sync locale

Sul Mac:

```bash
cd "/Users/parideporpora/Documents/Documenti - Paride's MacBook Pro/Paride Porpora/Lavoro (agronomo)/Libera professione/Agronomo_Claude/monitoraggio-letteratura/digest"
git clone https://github.com/pparide/monitor-letteratura-agronomo.git repo
```

Da allora in poi:

```bash
cd "/Users/.../monitoraggio-letteratura/digest/repo"
git pull
```

Il digest è in `digest/repo/digest/<aaaa-Wnn>_digest.md`.

### 5. (Opzionale) Cron locale per pull automatico

```cron
# Lunedì 8:30 (motore gira alle 7:00 UTC = 8:00/9:00 CET, lascia 90 min margine)
30 8 * * 1 cd "/Users/.../monitoraggio-letteratura/digest/repo" && git pull >/dev/null 2>&1
```

---

## Uso settimanale (15 minuti)

1. **Lunedì 9:00** — `git pull` nella cartella locale.
2. **Apri** `digest/repo/digest/<settimana>_digest.md` in Obsidian.
3. **Triage 10-15 min**: scorri per area, score decrescente. Per ogni hit decidi:
   - 👍 Da indicizzare → scarica PDF (link OA in digest), drop in `_inbox/`, due righe contesto. Cowork lo indicizza alla prossima sessione.
   - 📌 Salva per dopo → annota con `<<<` nel digest stesso, o aggiungi a `monitoraggio-letteratura/archivio-promossi/da_processare.md`.
   - 🗑️ Ignora → niente, va in `seen.json` (non riproposto).

---

## Calibrazione

### Quando aggiungere una rivista / autore / query

1. Aggiungi la voce in `Agronomo_Claude/monitoraggio-letteratura/fonti/0X_*.md` (strato 1, governo).
2. Aggiungi la voce in `config/sources.json` (qui, strato 2, motore).
3. Aggiorna lo `Stato repo:` a `✅ in repo` nel file dello strato 1.
4. Commit + push.

### Quando una keyword genera troppi falsi positivi

1. Aggiorna `config/rules.json` (peso ridotto, sposta a `negative`, o rimuovi).
2. Aggiorna `monitoraggio-letteratura/00_glossario_keywords.md` (specchio commentato).
3. Commit + push con messaggio `calibration: <area> <keyword> <reasoning>`.

### Quando un autore-chiave cambia affiliazione

L'OpenAlex `author_id` resta lo stesso. Solo la nota in `sources.json` va aggiornata. Niente da fare nel motore.

---

## Test locale (senza GitHub Actions)

Sul Mac o in qualsiasi macchina con Python 3.11+:

```bash
cd /path/to/monitor-letteratura-agronomo
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# dry-run: chiama API ma NON aggiorna seen.json
python -m src.main --since-days 30 --dry-run

# Smoke test E2E
pytest tests/
```

---

## Integrazione con Strato 1 (knowledge base locale)

Il file [`Agronomo_Claude/monitoraggio-letteratura/00_INDICE.md`](#) è il punto di ingresso concettuale. Spiega le 6 aree dello studio, la matrice 3D, i 7 file di fonti.

L'allineamento Strato 1 ↔ Strato 2 è **manuale** ma tracciabile:

- Ogni voce di `fonti/0X_*.md` (Strato 1) ha un campo `Stato repo:` che indica `✅ in repo` / `🟡 da aggiungere` / `🔴 rimossa`.
- Ogni voce di `config/sources.json` (Strato 2, qui) corrisponde 1:1 a una voce dello Strato 1.

In **Fase 1** (oggi) sono in repo:
- 4 riviste (Forests, iForest, npj Urban Sustainability, Forest@) — su 18+ in Strato 1
- 5 autori-chiave (Sjöman, Konijnendijk, Salbitano, Ferrini, Sanesi) — su 35 in Strato 1
- 5 query anchor (Q01-Q05 dal piano-studio) — su 31 in Strato 1
- 2 aree (verde_urbano, vta) — su 6 in Strato 1

In Fase 2-3 espanderemo progressivamente.

---

## Limiti noti

- **OpenAlex updated weekly**: paper appena pubblicati possono non essere ancora indicizzati. Per gli autori uso `since_days * 2` di lookback.
- **CrossRef abstract spesso assenti** o in JATS XML grezzo. OpenAlex e EuropePMC sono migliori per gli abstract.
- **Google Scholar non ha API ufficiale**: le 5 query anchor del piano-studio funzionano via OpenAlex search + EuropePMC, **non via Google Scholar**. Per coprire il gap, valuta in Fase 3 il parsing email delle Google Scholar Alerts (richiede account dedicato + IMAP setup).
- **Riviste paywall**: il motore vede metadata + abstract via OpenAlex/CrossRef, ma il PDF NON è scaricabile automaticamente. Il triage manuale prosegue come prima (ResearchGate, email autore, biblioteca).
- **Sci-Hub non integrato**: rispettiamo le restrizioni legali italiane sul DRM circumvention.

---

## Storico

- **2026-05-06** — Bootstrap Fase 1. Codice Python testato in sandbox Cowork (vedi `tests/test_smoke.py`). Da pushare su GitHub manualmente da Paride.
