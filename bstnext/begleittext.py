# -*- coding: utf-8 -*-
"""BSt Next: KI-Entwurf des Begleittextes passend zum Spruch (catrin 12.11.2026).

Die KI schreibt nur den Fliesstext (Aufhaenger, Nutzen, Schlusszeile). Link und Hashtags werden
deterministisch angehaengt. Produktaussagen stammen ausschliesslich aus der oeffentlichen
Produktuebersicht (Stand 07.10.2026) und der Produkt-FAQ: keine Preise, keine Verfuegbarkeit,
kein SmartNext (von catrin am 18.09.2026 ausgeblendet), kein CheckNext (noch nicht buchbar).

Das Ergebnis wird geprueft (keine Ziffern, Links, Hashtags, Superlative, Du-Ansprache) und bei
Verstoss einmal neu angefragt. Der Text landet nur im Formularfeld; gespeichert wird erst beim
Anlegen/Bearbeiten des Beitrags."""
import logging
import re

from . import brand

log = logging.getLogger("hilo.bstnext")

LINK_ZEILE = "Mehr über BSt Next: http://www.bst-next.de"

# Nur belegte Aussagen. Aenderungen nur anhand der oeffentlichen Produktuebersicht / Produkt-FAQ.
PRODUKTE = (
    ("SortNext", "Belegsortierung für Beratungsstellen: SortNext analysiert und sortiert die Belege der "
                 "Mitglieder. Die Ausgabe erfolgt als PDF- und Excel-Datei, unabhängig von der eingesetzten "
                 "Steuersoftware. Optional erstellt SortNext mit dem ELSTER-Protokoll des Vorjahres einen "
                 "Vorjahresvergleich mit einer Liste fehlender Belege und einem Mitglieder-Anschreiben."),
    ("BookNext", "Buchungsseite für Beratungsstellen: Mitglieder buchen darüber Termine bei ihrer "
                 "Beratungsstelle und können Mitgliedsausweis und Vollmacht vorab digital unterschreiben."),
    ("CallNext", "Digitale Telefonassistenz (KI-System): Anrufende erfahren zu Gesprächsbeginn, dass sie mit "
                 "einem KI-System sprechen."),
    ("ShareNext", "Social-Media-Automatisierung für Beratungsstellen (Facebook, Instagram, WhatsApp)."),
    ("HelpNext", "Support rund um die eingesetzte Software, Administration, Fehler und Anwendungsfragen der "
                 "Beratungsstelle."),
    ("CoachNext", "Individuelles Coaching für Beratungsstellen, die gezielt an eigenen Themen arbeiten."),
)

SCHLUSSZEILEN = (
    "Wir fangen mit Ihren Belegen an.",
    "Wir fangen mit Ihren Prozessen an.",
    "Wir fangen mit Ihren Terminen an.",
    "Wir fangen mit Ihren Mitgliedern an.",
)

SYSTEM = ("Du schreibst Begleittexte für Social-Media-Beiträge der BSt Next GmbH i.G. (digitale Werkzeuge "
          "ausschließlich für Lohnsteuerhilfevereine und deren Beratungsstellen). Schreibe sachlich und "
          "konkret, ohne Werbehype, auf Deutsch mit echten Umlauten.")

# Verbotenes (case-insensitive). Ziffern, Links und Hashtags werden separat geprueft.
_VERBOTEN = re.compile(
    r"vollautomatisch|revolution|game-?changer|garantier|schneller|zuverlässiger|ab sofort|jetzt verfügbar"
    r"|smartnext|checknext|\bpreis|\beuro\b|€|\bdu\b|\bdein|\bdir\b|\bdich\b|steuerberat", re.IGNORECASE)
_MARKDOWN = re.compile(r"[*_`]|^\s*[-•]\s", re.MULTILINE)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


class BegleittextFehler(Exception):
    """Der Textvorschlag ist nicht moeglich oder nicht brauchbar; str(e) ist die Meldung fuer catrin."""


def baue_prompt(spruch_zeilen, hinweis="", vermeiden=()):
    produkte = "\n".join("- %s: %s" % (n, s) for n, s in PRODUKTE)
    schluss = "\n".join("- " + s for s in SCHLUSSZEILEN)
    text = (
        "Auf einem Bild steht dieser Spruch (jede Zeile ein Bildzeilenabschnitt):\n%s\n\n"
        "Schreibe dazu den Begleittext für Facebook und Instagram.\n\n"
        "Aufbau, genau drei Absätze:\n"
        "1. Aufhänger: eine konkrete Alltagssituation einer Beratungsstelle, ein Wortspiel oder eine "
        "nachdenklich machende Frage zur Aussage des Spruchs, 1 bis 2 Sätze. Gute Aufhänger sind zum "
        "Beispiel: „Ihre Mitglieder bringen Belegestapel - und Sie müssen alle bewerten und bearbeiten.“, "
        "„Der Beleg fällt nicht weit vom Stapel.“, „Eine Datei macht noch keine Digitalisierung.“\n"
        "2. Übergang und Nutzen: beginne mit „Mit <Produkt> ändert sich das.“ oder „Mit <Produkt> wird es "
        "besser.“ (mit dem passenden Produkt) und erkläre den Nutzen in 2 bis 3 Sätzen. Nenne nur Produkte, "
        "die zum Spruch passen (eines oder mehrere), und stütze den Nutzen auf diese Aussagen. "
        "Werbliche Nutzenformulierungen ohne konkrete Zusicherung sind erlaubt (zum Beispiel Zeit und "
        "Fehlerquellen sparen, Übersicht statt Chaos):\n%s\n"
        "3. Schlusszeile: genau eine der folgenden, wörtlich, passend zum Thema:\n%s\n\n"
        "Regeln:\n"
        "- Kurz und prägnant: insgesamt höchstens fünf Sätze vor der Schlusszeile. Sachlich-motivierend, "
        "nicht generisch.\n"
        "- Stil: konkrete Details statt Abstraktion (zum Beispiel „Belegestapel“ statt „viel zu tun“). "
        "Erst der Schmerzpunkt, dann die Wende mit dem Übergangssatz. Den Nutzen aus Sicht der Beratungsstelle "
        "schildern statt Funktionen aufzuzählen, gestützt auf die oben genannten Aussagen. Persönlich, aber "
        "professionell, nicht süßlich. Wenn passend, ein konkreter Vergleich (zum Beispiel „Papier im falschen "
        "Format“). Kurze und lange Sätze abwechseln.\n"
        "- Ansprache „Sie“, Zielgruppe Beratungsstellen und ihre Mitglieder. Schreibe „Beratungsstelle“, "
        "nie „Stelle“ allein.\n"
        "- Keine Ziffern und keine Zahlen- oder Zeitangaben (auch nicht „Stunden“, „Minuten“, „Tage“), keine "
        "Preise, keine Aussagen zur Verfügbarkeit oder zum Starttermin.\n"
        "- Keine Zusicherung konkreter Eigenschaften, keine Garantien, keine Superlative (zum Beispiel "
        "vollautomatisch, schneller, zuverlässiger, garantiert, revolutionär). Keine Steuerberatung.\n"
        "- Keine Hashtags, keine Links, kein Markdown, keine Aufzählungen, keine Emojis.\n"
        "- Antworte nur mit dem Text, ohne Überschrift und ohne Einleitung."
        % ("\n".join(spruch_zeilen), produkte, schluss))
    if vermeiden:
        text += ("\n\nDiese Anfänge wurden in früheren Beiträgen schon verwendet. Schreibe deutlich anders "
                 "(anderer Aufhänger, anderer Satzbau, andere Bilder):\n" + "\n".join("- " + v for v in vermeiden))
    if hinweis:
        text += "\n\nDein letzter Entwurf wurde abgelehnt: %s Bitte schreibe ihn neu und halte die Regeln ein." % hinweis
    return text


def pruefe(text):
    """Gibt den Ablehnungsgrund zurueck oder None, wenn der Text brauchbar ist."""
    if not text or len(text) < 80:
        return "Der Text ist zu kurz."
    if re.search(r"\d", text):
        return "Der Text enthält Ziffern."
    if re.search(r"https?://|www\.|@", text) or "#" in text:
        return "Der Text enthält Links oder Hashtags."
    if _MARKDOWN.search(text) or _EMOJI.search(text):
        return "Der Text enthält Markdown oder Emojis."
    m = _VERBOTEN.search(text)
    if m:
        return "Der Text enthält unerlaubte Wörter (%s)." % m.group(0)
    if not any(s in text for s in SCHLUSSZEILEN):
        return "Die Schlusszeile fehlt oder weicht von den erlaubten ab."
    return None


def _client():
    from secrets_store import get_secret
    key = get_secret("anthropic_api_key")
    if not key:
        raise BegleittextFehler("Der Textvorschlag ist gerade nicht möglich (kein KI-Zugang hinterlegt).")
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=45)


def _modell():
    import textgen
    return textgen._model()


def erzeuge(spruch_zeilen, client=None, versuche=2, vermeiden=()):
    """Liefert den fertigen Begleittext (Fliesstext + Link-Zeile + Hashtags). Wirft BegleittextFehler.
    'client' ist mockbar (Objekt mit messages.create(...))."""
    zeilen = [z.strip() for z in spruch_zeilen if z and z.strip()]
    if not zeilen:
        raise BegleittextFehler("Bitte zuerst den Spruch (weiße Zeilen) eintragen.")
    if client is None:
        client = _client()
    hinweis = ""
    for _ in range(max(1, versuche)):
        try:
            msg = client.messages.create(model=_modell(), max_tokens=700, system=SYSTEM,
                                         messages=[{"role": "user", "content": baue_prompt(zeilen, hinweis, vermeiden)}])
            roh = "".join(getattr(b, "text", "") for b in msg.content).strip()
        except BegleittextFehler:
            raise
        except Exception as ex:
            log.warning("BSt-Next-Textvorschlag fehlgeschlagen: %s", ex)
            raise BegleittextFehler("Der Textvorschlag ist gerade nicht möglich. Bitte später noch einmal versuchen.")
        text = re.sub(r"\n{3,}", "\n\n", roh).strip()
        grund = pruefe(text)
        if not grund:
            return "%s\n\n%s\n%s" % (text, LINK_ZEILE, brand.HASHTAGS)
        log.info("BSt-Next-Textvorschlag abgelehnt: %s", grund)
        hinweis = grund
    raise BegleittextFehler("Die KI hat keinen brauchbaren Text geliefert. Bitte noch einmal auf „Text vorschlagen“ klicken.")
