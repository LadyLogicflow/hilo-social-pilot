# -*- coding: utf-8 -*-
"""Zufalls-Pool ("Topf") fuer die HISOME-Hybrid-Strategie (Catrin 2026-06-23).

Idee: Zeitlose Beitraege werden EINMAL fuer alle Beratungsstellen freigegeben und landen
im Topf. Aus dem Topf wird taeglich je Stelle und Kanal ein Beitrag ZUFAELLIG gezogen -
fuer jede Stelle ein anderer. "Nie doppelt" (Variante 1): jeder Beitrag erscheint je Stelle
GENAU EINMAL pro Kanal (zeitversetzt ueber mehrere Kanaele erlaubt, nie zweimal auf demselben
Kanal). Das Gedaechtnis dafuer ist die Tabelle pool_nutzung (UNIQUE entwurf+stelle+kanal).

Datumsgebundene Inhalte (Anlass-Tage, Fristen-Countdown) laufen NICHT ueber den Topf, sondern
weiter manuell ueber die Einplanung-Seite. Dieses Modul ist bewusst Flask-frei und nur ueber
eine offene SQLite-Verbindung angesprochen -> einzeln testbar.
"""

# Kanaele, die der Topf bespielt. facebook/instagram laufen ueber den bestehenden Scheduler;
# whatsapp_* werden in einer spaeteren Ausbaustufe an den WhatsApp-Dienst angebunden.
POOL_KANAELE = ["facebook", "instagram", "whatsapp_status", "whatsapp_kanal"]

KANAL_LABEL = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "whatsapp_status": "WhatsApp-Status",
    "whatsapp_kanal": "WhatsApp-Kanal",
}

# Schwelle, ab der vor knappem Vorrat gewarnt wird (Catrin: < 14 Beitraege je Stelle).
WARNSCHWELLE = 14


def aktive_pool_ids(conn):
    """IDs aller aktiven Topf-Beitraege (aeltester zuerst)."""
    return [r[0] for r in conn.execute(
        "SELECT entwurf_id FROM pool WHERE aktiv=1 ORDER BY freigegeben_am, entwurf_id")]


def ist_im_pool(conn, eid):
    """True, wenn der Entwurf aktiv im Topf liegt."""
    return conn.execute("SELECT 1 FROM pool WHERE entwurf_id=? AND aktiv=1", (eid,)).fetchone() is not None


def verbrauchte_paare(conn):
    """Menge bereits verbrauchter (entwurf_id, stelle_id, kanal)-Tripel - das 'nie doppelt'-Gedaechtnis."""
    return {(r["entwurf_id"], r["stelle_id"], r["kanal"])
            for r in conn.execute("SELECT entwurf_id, stelle_id, kanal FROM pool_nutzung")}


def offene_beitraege(conn, stelle_id, kanal, pool_ids=None, verbraucht=None):
    """Topf-Beitraege, die diese Stelle auf diesem Kanal NOCH NICHT hatte (= ziehbar).
    pool_ids/verbraucht koennen vorberechnet uebergeben werden (spart Queries bei Schleifen)."""
    if pool_ids is None:
        pool_ids = aktive_pool_ids(conn)
    if verbraucht is None:
        verbraucht = verbrauchte_paare(conn)
    return [eid for eid in pool_ids if (eid, stelle_id, kanal) not in verbraucht]


def restbestand(conn, stelle_ids, kanaele=None):
    """Vorrat je (Stelle, Kanal): wie viele Topf-Beitraege die Stelle auf dem Kanal noch ziehen kann.
    Rueckgabe: dict[(stelle_id, kanal)] -> Anzahl offener Beitraege."""
    kanaele = kanaele or POOL_KANAELE
    pool_ids = aktive_pool_ids(conn)
    verbraucht = verbrauchte_paare(conn)
    out = {}
    for sid in stelle_ids:
        for kanal in kanaele:
            out[(sid, kanal)] = len(offene_beitraege(conn, sid, kanal, pool_ids, verbraucht))
    return out


def knappe_vorraete(conn, stelle_ids, kanaele=None, schwelle=WARNSCHWELLE):
    """Liste (stelle_id, kanal, rest) fuer alle Kombinationen unter der Warnschwelle - fuer den
    Nachschub-Hinweis. Leere Liste = Vorrat ueberall ausreichend."""
    rest = restbestand(conn, stelle_ids, kanaele)
    return sorted([(sid, kanal, n) for (sid, kanal), n in rest.items() if n < schwelle],
                  key=lambda t: t[2])


def markiere_verbraucht(conn, entwurf_id, stelle_id, kanal):
    """Schreibt ein (entwurf, stelle, kanal)-Tripel ins 'nie doppelt'-Gedaechtnis.
    INSERT OR IGNORE -> idempotent (der UNIQUE-Schluessel verhindert Doppelte)."""
    conn.execute("INSERT OR IGNORE INTO pool_nutzung(entwurf_id, stelle_id, kanal) VALUES (?,?,?)",
                 (entwurf_id, stelle_id, kanal))


def ziehe_tagesauswahl(conn, stelle_ids, kanal, rng):
    """Zieht fuer EINEN Kanal je Stelle einen zufaelligen, noch offenen Topf-Beitrag - so, dass an
    EINEM Tag keine zwei Stellen denselben Beitrag bekommen ('fuer jede Stelle ein anderer').

    Greedy ohne Zuruecklegen: Stellen mit dem kleinsten Vorrat zuerst bedienen (die haben die
    wenigsten Ausweichmoeglichkeiten). rng ist eine random.Random-Instanz (Aufrufer steuert den Seed
    -> testbar). Rueckgabe: dict[stelle_id] -> entwurf_id (Stellen ohne offenen Beitrag fehlen).

    Markiert NICHTS - der Aufrufer entscheidet, ob/wann er markiere_verbraucht() schreibt (z.B. erst
    nach erfolgreicher Einplanung)."""
    pool_ids = aktive_pool_ids(conn)
    verbraucht = verbrauchte_paare(conn)
    offen = {sid: offene_beitraege(conn, sid, kanal, pool_ids, verbraucht) for sid in stelle_ids}
    auswahl = {}
    schon_vergeben = set()
    for sid in sorted(stelle_ids, key=lambda s: len(offen[s])):
        kandidaten = [eid for eid in offen[sid] if eid not in schon_vergeben]
        if not kandidaten:
            continue  # Vorrat fuer diese Stelle erschoepft (oder am Tag alles schon vergeben)
        wahl = rng.choice(kandidaten)
        auswahl[sid] = wahl
        schon_vergeben.add(wahl)
    return auswahl
