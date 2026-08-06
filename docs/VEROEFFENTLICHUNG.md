# Veröffentlichung (Facebook & Instagram)

Diese Datei beschreibt, wie ein freigegebener Beitrag technisch auf **Facebook** und
**Instagram** veröffentlicht wird – als **Feed-Beitrag** (Einzelbild oder Karussell) und
optional zusätzlich als **Story** (9:16, verschwindet nach 24 Stunden).

Alle Meta-Aufrufe laufen über die **Graph API** (`https://graph.facebook.com/v26.0`).
Die HTTP-Schicht liegt in **`publish.py`**, die Orchestrierung (welches Bild, welcher Kanal,
Feed und/oder Story) in **`web.py`** (`_veroeffentliche_ziel`).

> **Grundsatz:** Nichts geht ungefragt raus. Veröffentlicht wird erst nach menschlicher
> Freigabe; jede Veröffentlichung wird im Audit-Log protokolliert.

---

## 1. Überblick des Ablaufs

```
Freigegebener Entwurf
        │
        ▼
_veroeffentliche_ziel (web.py)          ← je Ziel: eine Beratungsstelle ODER eine FB-Seite
   ├─ Facebook (Feed)  → publish_facebook / publish_facebook_carousel
   │     └─ danach optional: Facebook-Story (photo_stories)
   └─ Instagram (Feed) → publish_instagram / publish_instagram_carousel
         └─ danach optional: Instagram-Story (media_type=STORIES)
```

Wichtige Punkte:

- **Story ist immer ein Zusatz zum Feed-Post.** Sie wird nur ausgelöst, wenn der reguläre
  Feed-Beitrag erfolgreich war (`if story and ok` / `if story_fb and ok`).
- **Das Story-Ergebnis wird nur ins Audit-Log geschrieben**, nicht als eigener Post in der
  Datenbank verbucht – Stories sind flüchtig (24 Stunden).
- **Facebook** lädt Bilder direkt hoch (Binär-Upload). **Instagram** verarbeitet nur Bilder,
  die über eine **öffentliche URL** erreichbar sind – deshalb werden IG-Bilder vorher per
  SFTP auf einen Webspace hochgeladen (`uploader.py`).

---

## 2. Voraussetzungen (Secrets & Berechtigungen)

| Voraussetzung | Wofür | Herkunft |
|---------------|-------|----------|
| `meta_user_token` | Alle Meta-Aufrufe (FB & IG) | Secret-Store (`secrets.json`/ENV) |
| `meta_app_id`, `meta_app_secret` | *(optional)* Langzeit-Token (60 Tage) | Secret-Store |
| Berechtigung `pages_manage_posts` | Facebook-Feed **und** Facebook-Story | Meta-App/Token |
| Berechtigung `instagram_content_publish` | Instagram-Feed **und** Instagram-Story | Meta-App/Token |
| Verknüpftes **Instagram-Business-Konto** | Alle Instagram-Posts | an der Facebook-Seite |
| `ionos_sftp_*` + `ionos_public_base_url` | Öffentliche Bild-URL für **Instagram** | Secret-Store (`uploader.py`) |

Tokens werden **nie** geloggt oder ausgegeben (`publish.py`).
Das Nutzer-Token kann per `publish.ensure_long_lived()` gegen ein 60-Tage-Langzeit-Token
getauscht werden, sofern `meta_app_id` und `meta_app_secret` gesetzt sind.

---

## 3. Facebook

### 3.1 Feed – Einzelbild
`publish_facebook(page_id, image_path, caption, place=None, alt_text=None)`

- Direkter Binär-Upload: `POST /{page_id}/photos` mit `files={"source": …}` und `message`.
- `place` = optionale Facebook-Orts-ID (Geotag). Schlägt der Post **mit** Ort fehl, wird
  automatisch **ohne** Ort erneut versucht, damit der Beitrag trotzdem erscheint.
- `alt_text` = optionaler Alt-Text für Barrierefreiheit (Feld `alt_text_custom`).

### 3.2 Feed – Karussell (mehrere Bilder)
`publish_facebook_carousel(page_id, image_paths, caption, place=None, alt_texts=None)`

- Jedes Foto wird zunächst **unveröffentlicht** hochgeladen (`published=false`), danach werden
  alle Foto-IDs in **einem** Feed-Beitrag zusammengeführt
  (`POST /{page_id}/feed` mit `attached_media[i]`).
- Scheitert ein Schritt, werden bereits hochgeladene Fotos wieder gelöscht (kein „Waisen-Foto").

### 3.3 Story
`publish_facebook_story(page_id, image_path, alt_text=None)`

- **Keine öffentliche URL nötig** (direkter Binär-Upload).
- Zweistufig: **(a)** Foto unveröffentlicht hochladen (`POST /{page_id}/photos?published=false`)
  → Foto-ID; **(b)** Foto-ID an `POST /{page_id}/photo_stories` übergeben.
- Bei Fehlschlag wird das hochgeladene Foto wieder gelöscht.
- Ideal im Hochformat **9:16** (siehe Abschnitt 5).

### 3.4 Erster Kommentar (Buchungslink)
`comment_facebook(post_id, page_id, message)` – postet nach einem erfolgreichen
Beratungsstellen-Feed-Post automatisch den Termin-Link als **ersten Kommentar** (die
Facebook-Caption verweist auf „Link in den Kommentaren"). Nur bei Stellen mit hinterlegtem
Buchungslink.

---

## 4. Instagram

Instagram veröffentlicht **immer zweistufig** (Container anlegen → veröffentlichen) und braucht
**öffentlich erreichbare Bild-URLs**. Zwischen beiden Schritten wird gewartet, bis Meta den
Container fertig verarbeitet hat (`_wait_ig_container` pollt `status_code=FINISHED`) – sonst
schlägt das Veröffentlichen fehl („Media ID is not available").

### 4.1 Feed – Einzelbild
`publish_instagram(ig_user_id, image_url, caption, location_id=None, alt_text=None)`

- **(a)** `POST /{ig_user_id}/media` (mit `image_url`, `caption`) → Container-ID
- **(b)** warten bis `FINISHED`
- **(c)** `POST /{ig_user_id}/media_publish`
- `location_id` = optionaler Geotag; `alt_text` = Alt-Text (bei Instagram-Feed unterstützt).

### 4.2 Feed – Karussell
`publish_instagram_carousel(ig_user_id, image_urls, caption, location_id=None, alt_texts=None)`

- Je Bild ein **Kind-Container** (`is_carousel_item=true`) → jeweils auf `FINISHED` warten,
  dann ein **Eltern-Container** (`media_type=CAROUSEL`, `children=…`) → `FINISHED` → publish.

### 4.3 Story
`publish_instagram_story(ig_user_id, image_url)`

- **(a)** `POST /{ig_user_id}/media` mit **`media_type=STORIES`** → Story-Container
- **(b)** warten bis `FINISHED`
- **(c)** `POST /{ig_user_id}/media_publish`
- **Kein** `caption`, **kein** `alt_text`: Meta unterstützt das Alt-Text-Feld laut Doku nur für
  Feed-Bilder, ausdrücklich **nicht** für Stories/Reels.

### 4.4 IG-Konto ermitteln
Das zu einer Facebook-Seite gehörende Instagram-Business-Konto wird über
`list_pages()` bestimmt (`GET /me/accounts?fields=…,instagram_business_account{id,username}`)
und über die passende Facebook-Seiten-ID gematcht.

---

## 5. Story-Aufbereitung (9:16) & Frames

Story-Bilder werden aus den vorhandenen (quadratischen, 1080×1080) Beitragsbildern erzeugt:

- **`_status_hochkant`** (`web.py`) komponiert jedes quadratische Bild zentriert auf einen
  HILO-Farbverlauf (Blau → Grün) im Format **9:16 / 1080×1920**.
- **`_publish_story`** (`web.py`) postet die aufbereiteten Bilder **nacheinander als einzelne
  Story-Frames**. Ein Karussell wird so zu einer **mehrteiligen Story** (ein Frame pro Slide).
  - `do_ig=True`: Frame per `uploader.upload` öffentlich machen → `publish_instagram_story`.
  - `do_fb=True`: direkt `publish_facebook_story` (kein Upload nötig).
- Erfolg = mindestens **ein** Frame wurde irgendwo gepostet; Teilfehler werden gesammelt
  gemeldet und protokolliert.

---

## 6. Steuerung im Dashboard (UI)

In der Einplanungs-/Veröffentlichungsseite gibt es zwei Kontrollkästchen:

| Kontrollkästchen | Formularfeld | Standard | Wirkung |
|------------------|--------------|----------|---------|
| „Bei Instagram zusätzlich als Story posten" | `story_ig` | **an** | IG-Story nach IG-Feed-Post |
| „Bei Facebook zusätzlich als Story posten" | `story_fb` | **aus** | FB-Story nach FB-Feed-Post |

Der Kanal selbst (`facebook`, `instagram`, `beide`) und das Bildformat je Kanal
(`einzelbild`/`karussell`) werden separat gewählt. Die Story übernimmt immer alle Slides des
Karussells als Frames – unabhängig vom gewählten Feed-Format.

---

## 7. Fehlerbehandlung & Protokollierung

- **Feed-Posts** landen mit Plattform-Post-ID (oder Fehlermeldung) in der Tabelle `posts`.
- **Stories** werden nur ins **Audit-Log** geschrieben
  (`instagram_story_ok`/`_fehler`, `facebook_story_ok`/`_fehler`), nicht als eigener Post
  verbucht (flüchtig).
- Fehlermeldungen zeigen die **echte** Meta-Fehlermeldung aus dem JSON-Body
  (z.B. „Invalid OAuth access token"), nicht nur den HTTP-Statuscode (`_err`).
- Teil-Uploads (Karussell, Story) werden bei Abbruch wieder aufgeräumt.

---

## 8. Auswertung (Insights)

`post_insights(kanal, plattform_post_id, page_id)` ruft je veröffentlichtem **Feed-Beitrag**
Reichweite und Interaktionen ab:

- **Instagram:** `reach` (Insight) + `like_count` + `comments_count` + `saved`.
- **Facebook:** `post_impressions_unique` (Insight) + Reaktionen + Kommentare + geteilte Beiträge.

Für Stories werden keine Insights abgerufen (flüchtig).

---

## 9. Code-Referenzen

| Funktion | Datei |
|----------|-------|
| Graph-API-Basis, Token-Handling, Langzeit-Token | `publish.py` |
| Facebook Feed (Einzelbild / Karussell) | `publish.py` (`publish_facebook`, `publish_facebook_carousel`) |
| Facebook Story | `publish.py` (`publish_facebook_story`) |
| Instagram Feed (Einzelbild / Karussell) | `publish.py` (`publish_instagram`, `publish_instagram_carousel`) |
| Instagram Story | `publish.py` (`publish_instagram_story`) |
| Container-Warteschleife | `publish.py` (`_wait_ig_container`) |
| Insights | `publish.py` (`post_insights`) |
| Öffentlicher Bild-Upload (SFTP → URL) | `uploader.py` (`upload`, `configured`) |
| Orchestrierung Feed + Story je Ziel | `web.py` (`_veroeffentliche_ziel`) |
| Instagram-Feed-Wrapper (Upload + Konto-Ermittlung) | `web.py` (`_publish_instagram`) |
| Story-Frames posten | `web.py` (`_publish_story`) |
| 9:16-Komposition | `web.py` (`_status_hochkant`) |
