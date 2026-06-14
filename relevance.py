# -*- coding: utf-8 -*-
"""Relevanz-Filter fuer die HILO-Zielgruppe (Arbeitnehmer, Rentner, Familie, private Vermieter).
Schliesst Unternehmens-/USt-Themen aus; bevorzugt private Lohnsteuer-/VuV-Themen.
Heuristik per Schluesselwort; die finale Entscheidung trifft der Mensch (Freigabe)."""

# Nicht relevant: Umsatzsteuer, Gewerbe (Stamm "gewerb" -> gewerbe/gewerblich/Gewerbesteuer), Unternehmen
EXCLUDE = [
    "umsatzsteuer", "vorsteuer", "gewerb",
    "k\u00f6rperschaft", "koerperschaft", "kapitalgesellschaft", "gmbh",
    "betriebsausgaben", "bilanz", "organschaft", "buchf\u00fchrung", "buchfuehrung",
    "unternehmer", "selbst\u00e4ndig", "selbstst\u00e4ndig", "selbstaendig", "selbststaendig",
]

# Relevant: private Arbeitnehmer-/Rentner-/Familien-/Vermietungs-Themen
INCLUDE = [
    "arbeitnehmer", "arbeitslohn", "lohnsteuer", "rentner", "rente", "pension",
    "familie", "kind", "kindergeld", "elterngeld", "werbungskosten",
    "au\u00dfergew\u00f6hnliche belastung", "aussergewoehnliche belastung",
    "pflege", "haushaltsnah", "homeoffice", "home-office", "pendler",
    "entfernungspauschale", "unterhalt", "ausbildung", "studium", "behinderung",
    "krankheitskosten", "umzug", "doppelte haushalts", "ehegatten", "verheiratet",
    "scheidung", "minijob", "kurzarbeit", "abfindung", "vorsorge", "riester",
    "spenden", "grundfreibetrag", "steuererkl\u00e4rung", "steuererklaerung",
    "vermietung", "verpachtung", "vermieter", "mieteinnahmen", "immobilie",
    "immobilien", "eigentumswohnung", "grundsteuer",
]

def classify(text):
    t = (text or "").lower()
    if any(k in t for k in EXCLUDE):
        return "verworfen"
    if any(k in t for k in INCLUDE):
        return "ausgewaehlt"
    return "neu"
