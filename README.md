# salva_img

Piccolo programma con finestra (Tkinter) che scarica le immagini JPG di una pagina web, una dopo l'altra, con una pausa impostabile tra un download e il successivo.

## Cosa fa

1. Chiede l'indirizzo della pagina, la pausa tra i download (in millisecondi, default 400) e la cartella di destinazione.
2. Analizza la pagina e trova le immagini JPG/JPEG, cercando:
   - nei tag `<img>` (anche `data-src`, `srcset`);
   - nei link `<a>` che puntano a file `.jpg`/`.jpeg` (maiuscolo o minuscolo);
   - nei `<link rel="preload" as="image">` e nei dati JSON incorporati nella pagina (chiavi tipo `imageUrl`).
   Le immagini vengono riconosciute anche se l'URL non termina in `.jpg`, controllando il tipo di file dichiarato dal server (`image/jpeg`).
3. Le scarica in ordine, dall'alto verso il basso, rispettando la pausa, e mostra le anteprime numerate.
4. Se premi **OK**, crea nella cartella di destinazione una sottocartella dedicata e ci salva le immagini rinominate `001.jpg`, `002.jpg`, ...
   Premendo **Annulla** (o chiudendo la finestra) le immagini temporanee vengono eliminate.

### Nome della cartella creata

- Se nell'indirizzo c'è un codice univoco (UUID): `sito codice`, ad esempio
  `https://ourdream.ai/comic-studio/3bfceae8-f30f-40c0-8565-94575acea09a/read`
  → `ourdream.ai 3bfceae8-f30f-40c0-8565-94575acea09a`
- Altrimenti: `sito ultimo-segmento-del-percorso` (ignorando parole generiche come `read`, `view`, `gallery`).
- Se l'indirizzo non ha percorso: solo il nome del sito.
- Se la cartella esiste già e contiene file, **di default il salvataggio viene saltato** (le anteprime restano, non viene scritto nulla).
  Con la spunta **Chiedi se presente** il programma chiede cosa fare:
  - **Sovrascrivi**: sostituisce i file con lo stesso nome (`001.jpg`, ...); gli altri file della cartella restano;
  - **Nuova cartella**: crea la stessa cartella con `_2`, `_3`, ... nel nome;
  - **Salta** (predefinito): non salva nulla.

### Cartella scelta a mano

Con la spunta **Scegli la cartella delle immagini** compare una riga in più dove indicare la cartella esatta in cui mettere le immagini (nessuna sottocartella viene creata; se non esiste viene creata). Se è spenta (predefinito) vale il comportamento descritto sopra. Il controllo "cartella già presente" vale anche per la cartella scelta a mano.

## Requisiti

- Python 3.9 o superiore (con Tkinter, incluso nell'installazione standard di Windows/macOS)
- Librerie `requests` e `Pillow`

## Come avviarlo

```bash
# 1. scarica il progetto
git clone https://github.com/<tuo-utente>/salva_img.git
cd salva_img

# 2. installa le dipendenze
pip install -r requirements.txt

# 3. avvia il programma
python scarica_immagini.py
```

Poi nella finestra:

1. scrivi l'indirizzo della pagina;
2. imposta la pausa in ms e scegli la cartella di destinazione con **Sfoglia...**;
3. premi **Cerca immagini** e controlla le anteprime;
   (**Pulisci** accanto al pulsante svuota l'indirizzo e le anteprime, e ferma una ricerca in corso;
   le due spunte accanto servono per "Chiedi se presente" e "Scegli la cartella delle immagini");
4. premi **OK, salva nella cartella**; a salvataggio riuscito il popup offre **OK** (chiude e basta) oppure **OK e pulisci** (chiude e svuota indirizzo e anteprime).

## Limiti

- Funziona sulle pagine pubbliche leggibili con una normale richiesta HTTP; non gestisce login né pagine che caricano le immagini solo dopo azioni dell'utente.
- Analizza una sola pagina per volta (nessuna paginazione).
- Usa il programma solo su contenuti che hai il diritto di scaricare e rispetta i termini del sito.
