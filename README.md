# Basket News — Rassegna stampa LBA / Serie A2 2026–27

## Cosa comprende (versione 3 — fonti aggiornate)

- Albero con **16 società LBA + 20 A2**, per stagione 2026/27, aggiornate con le liste ufficiali delle leghe (19/10/2026).
- Lettura RSS: notizie da Google News per ogni squadra, ricerche mirate sulle **testate locali** e ricerche per sito del club quando configurato; cinque feed RSS diretti opzionali.
- Archivio SQLite persistente **solo se installato su disco persistente**; archivio degli articoli, link, data, fonte e squadra, deduplicazione di URL e titoli molto simili.
- Classificazione automatica tramite **parole chiave**: infortuni, mercato, allenamenti, società, dichiarazioni, risultati. Le etichette NON equivalgono a una verifica giornalistica/medica. Le notizie prioritarie sono una selezione euristica, non una validazione delle voci di mercato.
- Ricerca per testo (incluso nome di un giocatore quando compare in titolo/estratto), filtri 1/3/7/30 giorni, tipo fonte, argomento, notizie rilevanti; export CSV.
- Aggiornamento manuale (richiede token in produzione), aggiornamento programmato alle **08:00 e 20:00 Europe/Rome** soltanto se l'app rimane in esecuzione.
- Pannello sorgenti, errori di acquisizione e link esterni all'editore o a Google News.
- **Fonti V3 aggiunte:** SuperBasket, BasketUniverso, RealOlimpiaMilano; 17 associazioni a testate locali, secondo le proposte della revisione fonti V3. Tutti i domini aggiunti sono interrogati mediante Google News, **senza presupporre l'esistenza di RSS diretti**.
- **Social V3:** link consultabili per BasketNoLimits (Instagram), Mondo a Spicchi (Telegram e Instagram) e Pep Malaguti (Facebook profilo + pagina, Instagram, X). **Solo Telegram** dispone di un lettore sperimentale dei messaggi pubblici; gli altri social non vengono scaricati automaticamente.

## Avvio locale (Python 3.10+)

Non ci sono pacchetti da installare.

```bash
python app.py
```

Apri http://localhost:8000 . La prima raccolta parte in background all'avvio e può impiegare diversi minuti. Se la tua rete blocca RSS/Google News non verranno create notizie inventate: vedrai archivio vuoto/errori. Tutte le funzioni di navigazione e ricerca funzionano anche con un archivio vuoto.

Per impedire il primo aggiornamento automatico:

```bash
AUTO_INITIAL_REFRESH=0 python app.py
```

## Pubblicazione su Render

1. **Estrai lo ZIP** sul computer, crea o apri un repository GitHub e carica **i file estratti nella radice del repository** (`app.py`, `catalog.py`, `collector.py`, `static/`, ecc.). Non caricare soltanto lo ZIP, perché Render non lo esegue direttamente. Collega il repository a **Render > New > Web Service**.
2. Runtime Python; comando di avvio: `python app.py`; health check `/health`. La variabile `PORT` è gestita da Render.
3. Aggiungi una variabile d'ambiente `REFRESH_TOKEN` con una password lunga e casuale. Il pulsante **Aggiorna** la richiederà: resta solo nella memoria del browser fino alla chiusura della pagina. Non inserire il token nel repository.
4. **Persistenza dati:** Render può eliminare l'archivio su riavvii/redeploy se il servizio non ha un disco persistente. Configura una directory persistente e `DATABASE_PATH=/var/data/basket_news.db`, se il piano Render la supporta. In alternativa serve database esterno: questa versione usa SQLite, non PostgreSQL.
5. **Aggiornamenti programmati:** 08:00/20:00 (fuso Europe/Rome) sono reali SOLO con servizio sempre acceso. Se il piano sospende l'istanza, programma un trigger HTTPS esterno al percorso `POST /api/refresh` con header `X-Refresh-Token: ...` o configura un servizio sempre acceso. Non dichiarare attive le schedulazioni prima di testarle sul provider.

**Attenzione:** le politiche di costo del cloud variano: verifica i prezzi Render prima di attivare un'istanza a pagamento. Questo pacchetto non effettua acquisti o pubblicazioni automatiche.

## Fonte e limiti

- Elenco squadre: https://www.legabasket.it/protagonisti/squadre e https://www.legapallacanestro.com/serie/1/squadre
- RSS Google News: indice di copertura **non garantita**; alcuni feed possono restituire 429, 403 o nessuna notizia. La ricerca sui siti locali tramite Google News non equivale allo scraping integrale dei siti.
- I campi `official` e `local` del file `catalog.py` sono **candidati editoriali**, da controllare periodicamente: nomi dominio/assetti societari cambiano. Alcuni sono stati verificati, altri no. Gli errori di rete vengono riportati nei log e nel pannello di stato.
- Gli articoli a pagamento non vengono copiati, i paywall non vengono aggirati. Si salvano soltanto titolo/estratto RSS e link.
- Il canale pubblico Telegram di Mondo a Spicchi viene tentato con una lettura HTML **sperimentale** a ogni ciclo. Non usa login né API private e potrebbe smettere di funzionare per cambiamenti al sito o blocchi d'accesso. Gli altri social sono **solo collegamenti**: per acquisirli regolarmente occorrono API/autorizzazioni e verifica delle condizioni delle piattaforme.
- Gli articoli social e le notizie di mercato non equivalgono a conferme ufficiali: aprire sempre la fonte e verificare le dichiarazioni originali.
- Nessuna notifica push, nessuna sintesi generativa del testo integrale; classificazione per regole. Per una sintesi AI serve un'ulteriore integrazione autorizzata.
- Questa versione **non modifica LBASCRAP**. È predisposta per essere collegata tramite un tab/link, ma il codice corrente del tuo progetto deve essere esaminato per l'integrazione reale.

## Configurazione

Modifica `catalog.py` per aggiungere/correggere domini locali o siti club; le squadre si presentano come `Team(id, name, league, query, aliases, official, local)`.

Variabili:

| Variabile | Default | Descrizione |
|---|---|---|
| `PORT` | `8000` | Porta web |
| `DATABASE_PATH` | `data/basket_news.db` | Percorso SQLite |
| `REFRESH_TOKEN` | vuoto | Obbligatorio in produzione per `/api/refresh` |
| `AUTO_INITIAL_REFRESH` | `1` | `0` disabilita avvio raccolta iniziale |
| `PRODUCTION` | vuoto | `1` impone il controllo token |

API JSON: `/api/teams`, `/api/news?team=a2-fortitudo&days=7`, `/api/status`, `/api/sources`. Per aggiornare: `POST /api/refresh` con header X-Refresh-Token. `/health` health check. `/api/export.csv` esporta max 200 risultati per richiesta.

## Integrazioni fonti V3

- SuperBasket: https://www.superbasket.eu/ (ricerca mirata Google News).
- BasketUniverso: https://www.basketuniverso.it/ (ricerca mirata Google News).
- RealOlimpiaMilano: https://realolimpiamilano.com/ (ricerca mirata Google News, attribuzione all'Olimpia Milano).
- Mondo a Spicchi: https://t.me/s/mondoaspicchicanale (lettura sperimentale dei messaggi pubblici) e https://www.instagram.com/mondoaspicchi/ (solo link da confermare).
- BasketNoLimits: https://www.instagram.com/_basketnolimits_/ (solo link).
- Pep Malaguti: https://www.facebook.com/giuseppe.malaguti.7/ , https://www.facebook.com/PepMalaguti/ , https://www.instagram.com/giuseppemalaguti/ , https://x.com/GiuseppeMalagu2 (tutti solo link).
- Stampa locale aggiuntiva: vedere `EXTRA_LOCAL_DOMAINS` in `catalog.py`. Alcuni domini erano proposte non verificate in tempo reale e vanno controllati prima di considerare la copertura affidabile.

**Verifiche:** test automatici offline superati; non è stato possibile verificare la raggiungibilità dei feed esterni da questo ambiente. È necessario un controllo online dopo l'avvio.

## Come si integra in LBASCRAP

Per ora pubblica il servizio come web app separata e aggiungi un link o tab «Rassegna stampa» in LBASCRAP. L'integrazione nello stesso processo richiederà il codice effettivo dell'ultima versione e una verifica delle route/import; **non sovrascrivere** i file esistenti con `app.py` di questo pacchetto.

## Prove effettuabili offline

```bash
python -m unittest discover -s tests -v
```

I test usano RSS sintetici chiaramente etichettati, senza fingere una verifica della connessione alle fonti online.
