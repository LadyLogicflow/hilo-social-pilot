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


# Tabellen-Parametrisierung (Recruiting-Erweiterung 2026-08): Alle Funktionen bespielen per Default
# die Steuer-Tabellen `pool`/`pool_nutzung` (heutiges Verhalten, BYTE-IDENTISCH). Ueber die optionalen
# Parameter pool_table/nutzung_table koennen dieselben Funktionen die Recruiting-Tabellen
# (`pool_recruiting`/`pool_nutzung_recruiting`) bedienen. Die Tabellennamen sind INTERNE Konstanten
# (kein User-Input) und werden per %-Format in die SQL-Strings gesetzt - kein Injection-Risiko.


def aktive_pool_ids(conn, pool_table="pool"):
    """IDs aller aktiven Topf-Beitraege (aeltester zuerst)."""
    return [r[0] for r in conn.execute(
        "SELECT entwurf_id FROM %s WHERE aktiv=1 ORDER BY freigegeben_am, entwurf_id" % pool_table)]


def ist_im_pool(conn, eid, pool_table="pool"):
    """True, wenn der Entwurf aktiv im Topf liegt."""
    return conn.execute("SELECT 1 FROM %s WHERE entwurf_id=? AND aktiv=1" % pool_table,
                        (eid,)).fetchone() is not None


def verbrauchte_paare(conn, nutzung_table="pool_nutzung"):
    """Menge bereits verbrauchter (entwurf_id, stelle_id, kanal)-Tripel - das 'nie doppelt'-Gedaechtnis."""
    return {(r["entwurf_id"], r["stelle_id"], r["kanal"])
            for r in conn.execute("SELECT entwurf_id, stelle_id, kanal FROM %s" % nutzung_table)}


def offene_beitraege(conn, stelle_id, kanal, pool_ids=None, verbraucht=None,
                     pool_table="pool", nutzung_table="pool_nutzung"):
    """Topf-Beitraege, die diese Stelle auf diesem Kanal NOCH NICHT hatte (= ziehbar).
    pool_ids/verbraucht koennen vorberechnet uebergeben werden (spart Queries bei Schleifen)."""
    if pool_ids is None:
        pool_ids = aktive_pool_ids(conn, pool_table)
    if verbraucht is None:
        verbraucht = verbrauchte_paare(conn, nutzung_table)
    return [eid for eid in pool_ids if (eid, stelle_id, kanal) not in verbraucht]


def restbestand(conn, stelle_ids, kanaele=None, pool_table="pool", nutzung_table="pool_nutzung"):
    """Vorrat je (Stelle, Kanal): wie viele Topf-Beitraege die Stelle auf dem Kanal noch ziehen kann.
    Rueckgabe: dict[(stelle_id, kanal)] -> Anzahl offener Beitraege."""
    kanaele = kanaele or POOL_KANAELE
    pool_ids = aktive_pool_ids(conn, pool_table)
    verbraucht = verbrauchte_paare(conn, nutzung_table)
    out = {}
    for sid in stelle_ids:
        for kanal in kanaele:
            out[(sid, kanal)] = len(offene_beitraege(conn, sid, kanal, pool_ids, verbraucht))
    return out


def knappe_vorraete(conn, stelle_ids, kanaele=None, schwelle=WARNSCHWELLE,
                    pool_table="pool", nutzung_table="pool_nutzung"):
    """Liste (stelle_id, kanal, rest) fuer alle Kombinationen unter der Warnschwelle - fuer den
    Nachschub-Hinweis. Leere Liste = Vorrat ueberall ausreichend."""
    rest = restbestand(conn, stelle_ids, kanaele, pool_table, nutzung_table)
    return sorted([(sid, kanal, n) for (sid, kanal), n in rest.items() if n < schwelle],
                  key=lambda t: t[2])


def markiere_verbraucht(conn, entwurf_id, stelle_id, kanal, nutzung_table="pool_nutzung"):
    """Schreibt ein (entwurf, stelle, kanal)-Tripel ins 'nie doppelt'-Gedaechtnis.
    INSERT OR IGNORE -> idempotent (der UNIQUE-Schluessel verhindert Doppelte)."""
    conn.execute("INSERT OR IGNORE INTO %s(entwurf_id, stelle_id, kanal) VALUES (?,?,?)" % nutzung_table,
                 (entwurf_id, stelle_id, kanal))


def ziehe_tagesauswahl(conn, stelle_ids, kanal, rng, erlaubte_eids=None, tabu=None,
                       pool_table="pool", nutzung_table="pool_nutzung"):
    """Zieht fuer EINEN Kanal je Stelle einen zufaelligen, noch offenen Topf-Beitrag - so, dass an
    EINEM Tag keine zwei Stellen denselben Beitrag bekommen ('fuer jede Stelle ein anderer').

    tabu (optional): Menge von entwurf_ids, die an diesem Tag bereits (auf einem ANDEREN Kanal)
    vergeben wurden und deshalb nicht nochmal gezogen werden duerfen - so erscheint derselbe Beitrag
    pro Tag garantiert nur bei EINER Stelle, auch kanaluebergreifend (Vorgabe catrin 2026-08-23).

    Greedy ohne Zuruecklegen: Stellen mit dem kleinsten Vorrat zuerst bedienen (die haben die
    wenigsten Ausweichmoeglichkeiten). rng ist eine random.Random-Instanz (Aufrufer steuert den Seed
    -> testbar). Rueckgabe: dict[stelle_id] -> entwurf_id (Stellen ohne offenen Beitrag fehlen).

    erlaubte_eids (optional, #127): Menge von entwurf_ids, auf die die Auswahl eingeschraenkt wird
    (z.B. nur 'leichte' Wochenend-Beitraege). None = keine Einschraenkung.

    Markiert NICHTS - der Aufrufer entscheidet, ob/wann er markiere_verbraucht() schreibt (z.B. erst
    nach erfolgreicher Einplanung)."""
    pool_ids = aktive_pool_ids(conn, pool_table)
    verbraucht = verbrauchte_paare(conn, nutzung_table)
    offen = {sid: offene_beitraege(conn, sid, kanal, pool_ids, verbraucht) for sid in stelle_ids}
    if erlaubte_eids is not None:
        erlaubt = set(erlaubte_eids)
        offen = {sid: [eid for eid in lst if eid in erlaubt] for sid, lst in offen.items()}
    auswahl = {}
    schon_vergeben = set(tabu) if tabu else set()
    for sid in sorted(stelle_ids, key=lambda s: len(offen[s])):
        kandidaten = [eid for eid in offen[sid] if eid not in schon_vergeben]
        if not kandidaten:
            continue  # Vorrat fuer diese Stelle erschoepft (oder am Tag alles schon vergeben)
        wahl = rng.choice(kandidaten)
        auswahl[sid] = wahl
        schon_vergeben.add(wahl)
    return auswahl
