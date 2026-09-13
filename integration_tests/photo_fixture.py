"""Photo compatibility inputs and non-allocation defaults for isolated tests."""

from copy import deepcopy

from scripts.foto_core import load_config


MODULE_KEY = "foto_papierabzuege"
STATE_PATH = "state/foto-papierabzuege.json"
INDEX_PATH = "indexes/fotos.json"
PASSWORD = "LokalerFotoTest123!"


def server_defaults(module, user, payload):
    config = load_config()
    return {
        "schema_version": 1, "modul": module.id,
        "redaktion.stufe": "ehrenamtlich",
        "bearbeitung.status": config["defaults"]["bearbeitung_status"],
        "publikation.status": config["defaults"]["publikation_status"],
        "technik.quelle": "webapp",
    }


def sample_payload(partition="A"):
    return {
        "signatur": {"format": partition},
        "erschliessung": {
            "titel": "INTEGRATIONSTEST generische Foto-Persistenz",
            "beschriftung": "INTEGRATIONSTEST - kein echter Archivnachweis",
            "beschreibung": "Kontrollierter Vergleich von generischer und bisheriger Foto-Persistenz.",
            "dargestellte_personen": [{"name": "Testperson Eins", "hinweis": "links"}, {"name": "Testperson Zwei", "hinweis": "rechts"}],
            "herkunft": "Technischer Integrationstest auf integration-test",
            "sammler": None, "fotograf": "Testfotograf",
            "rechteinhaber": "Technischer Testwert",
            "orte": ["Seitenstetten", "Stiftshof (Testangabe)"],
            "schlagworte": ["Integrationstest"], "altsignaturen": ["TEST-GENERIC"],
            "interne_bemerkung": "Nur Integrationstest; nicht in main uebernehmen.",
        },
        "korrespondenzstueck": True,
        "datierung": {"jahr": 1966, "monat": 5, "tag": 12, "anmerkung": "Fiktives Testdatum"},
    }


def legacy_payload(payload):
    return {
        "format": payload["signatur"]["format"],
        **{key: deepcopy(payload[key]) for key in ("erschliessung", "korrespondenzstueck", "datierung")},
    }
