"""
Veille BODACC — Procédures collectives
Récupère les annonces du jour, score les dossiers, génère rapport_YYYYMMDD.md
"""

import requests
import re
import sys
from datetime import date, timedelta

API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

SCORE_MIN = 4  # seuil de sélection

# ── Secteurs ────────────────────────────────────────────────────────────────

SECTEURS = [
    ("Défense & Aéronautique",    ["aéronaut", "défense", "armement", "naval", "spatia", "missile", "militair", "balistiq"]),
    ("Santé & Pharmaceutique",    ["pharmaceut", "médical", "biotech", "biotechnolog", "chimie fine", "laboratoir", "clinique"]),
    ("Industrie manufacturière",  ["usinage", "mécaniqu", "manufactur", "fonderie", "forge", "métallurg", "plastiqu", "caoutchouc", "composit"]),
    ("Tech & Numérique",          ["informatique", "logiciel", "numérique", "télécom", "cybersécur", "intelligenc artificielle", "cloud", "software"]),
    ("BTP & Construction",        ["construction", "bâtiment", "travaux publics", "rénovation", "génie civil", "maçonnerie", "charpente"]),
    ("Transport & Logistique",    ["transport", "logistique", "fret", "camion", "transitaire", "messagerie", "entrepôt"]),
    ("Commerce & Distribution",   ["commerce", "distribution", "négoce", "grossiste", "retail", "grande surface"]),
    ("Hôtellerie & Restauration", ["restaur", "hôtel", "tourisme", "café", "brasserie", "traiteur"]),
    ("Immobilier & Hôtellerie",   ["immobilier", "foncier", "promotion immob", "sci"]),
    ("Énergie & Environnement",   ["énergie", "solaire", "éolien", "environnement", "déchets", "recyclage", "eau"]),
    ("Agroalimentaire",           ["agroalimentaire", "alimentaire", "agriculture", "viticole", "boulangerie", "fromagerie"]),
]

BITD_KEYWORDS = ["aéronaut", "défense", "armement", "naval", "spatia", "missile", "militair"]


def detect_secteur(activite: str, texte: str) -> tuple[str, bool]:
    haystack = (activite + " " + texte).lower()
    for secteur, keywords in SECTEURS:
        if any(k in haystack for k in keywords):
            bitd = secteur == "Défense & Aéronautique" or any(k in haystack for k in BITD_KEYWORDS)
            return secteur, bitd
    return "Autres", False


def detect_procedure(typeavis: str) -> tuple[str, str, int]:
    t = typeavis.lower()
    if "redressement" in t:
        return "Redressement judiciaire", "Haute", 3
    if "liquidation" in t and "clôture" not in t and "plan" not in t:
        return "Liquidation judiciaire", "Haute", 2
    if "sauvegarde" in t:
        return "Sauvegarde", "Moyenne", 1
    if "rétablissement" in t:
        return "Rétablissement professionnel", "Basse", 0
    return typeavis, "Basse", 0


def score_dossier(annonce: dict) -> dict:
    activite = annonce.get("activite") or ""
    texte = annonce.get("publicationavis") or ""
    typeavis = annonce.get("typeavis_lib") or ""

    procedure, urgence, proc_bonus = detect_procedure(typeavis)
    secteur, bitd = detect_secteur(activite, texte)

    score = 5 + proc_bonus
    if bitd:
        score += 2
    if secteur in ("Santé & Pharmaceutique", "Tech & Numérique", "Énergie & Environnement"):
        score += 1
    score = min(10, score)

    return {
        "nom": (annonce.get("denomination") or "—").strip(),
        "siren": annonce.get("siren") or "—",
        "ville": (annonce.get("ville") or "—").strip().title(),
        "score": score,
        "secteur": secteur,
        "procedure": procedure,
        "urgence": urgence,
        "bitd": bitd,
        "marque": False,
        "ebitda": None,
        "synthese": build_synthese(annonce),
        "contacts": extract_contacts(texte),
    }


def build_synthese(annonce: dict) -> str:
    activite = (annonce.get("activite") or "").strip()
    typeavis = annonce.get("typeavis_lib") or ""
    registre = (annonce.get("registre") or "").strip()
    date_par = annonce.get("dateparution") or annonce.get("dateParution") or ""

    parts = []
    if activite:
        parts.append(f"Activité : {activite}.")
    if typeavis:
        parts.append(f"Procédure : {typeavis}.")
    if registre:
        parts.append(f"Tribunal : {registre}.")
    if date_par:
        parts.append(f"Parution BODACC : {date_par}.")

    texte = annonce.get("publicationavis") or ""
    # Extrait les 300 premiers caractères utiles du texte
    excerpt = re.sub(r"\s+", " ", texte).strip()[:300]
    if excerpt:
        parts.append(excerpt + ("…" if len(texte) > 300 else ""))

    return " ".join(parts)


def extract_contacts(texte: str) -> str:
    contacts = []
    patterns = [
        r"(administrateur judiciaire\s*:\s*[^\n;,\.]+)",
        r"(mandataire judiciaire\s*:\s*[^\n;,\.]+)",
        r"(liquidateur\s*:\s*[^\n;,\.]+)",
        r"(Me\s+[A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,3})",
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, texte, re.IGNORECASE):
            val = re.sub(r"\s+", " ", m.group(1)).strip(" :.,;")
            if val.lower() not in seen:
                seen.add(val.lower())
                contacts.append(val)
    return " ; ".join(contacts[:4]) if contacts else ""


# ── Fetch BODACC ─────────────────────────────────────────────────────────────

def fetch_annonces(since: str) -> list[dict]:
    params = {
        "where": f'familleavis_lib="Procédures collectives" AND dateparution>="{since}"',
        "limit": 100,
        "order_by": "dateparution DESC",
    }
    try:
        r = requests.get(API, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("results", [])
    except Exception as e:
        print(f"[BODACC] Erreur fetch : {e}", file=sys.stderr)
        return []


# ── Génération markdown ───────────────────────────────────────────────────────

def fmt_flag(val: bool | None) -> str:
    if val is True:
        return "Oui"
    return "Non"


def render_rapport(dossiers: list[dict], rapport_date: str) -> str:
    lines = [
        f"# Rapport Veille MASARE — {rapport_date}\n",
        "## Dossiers Retenus\n",
    ]

    for d in dossiers:
        lines.append("---\n")
        lines.append(f"### {d['nom']}\n")
        lines.append(f"- **SIREN** : {d['siren']}")
        lines.append(f"- **Score** : {d['score']}/10")
        lines.append(f"- **Secteur** : {d['secteur']}")
        lines.append(f"- **Procédure** : {d['procedure']}")
        lines.append(f"- **Urgence** : {d['urgence']}")
        lines.append(f"- **Ville** : {d['ville']}")
        lines.append(f"- **BITD** : {fmt_flag(d['bitd'])}")
        lines.append(f"- **Marque** : {fmt_flag(d['marque'])}")
        if d["ebitda"]:
            lines.append(f"- **EBITDA** : {d['ebitda']}")
        lines.append("")
        if d["synthese"]:
            lines.append(f"**Synthèse** :\n{d['synthese']}\n")
        if d["contacts"]:
            lines.append(f"**Contacts** :\n{d['contacts']}\n")

    lines.append("---\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    # On remonte 2 jours pour couvrir les week-ends / jours fériés
    since = (today - timedelta(days=2)).isoformat()
    rapport_date = today.strftime("%Y%m%d")
    filename = f"rapport_{rapport_date}.md"

    print(f"[BODACC] Récupération depuis {since}…")
    annonces = fetch_annonces(since)
    print(f"[BODACC] {len(annonces)} annonces reçues")

    if not annonces:
        print("[BODACC] Aucune annonce — pas de rapport généré.")
        return

    dossiers = [score_dossier(a) for a in annonces]
    dossiers = [d for d in dossiers if d["score"] >= SCORE_MIN]
    dossiers.sort(key=lambda d: d["score"], reverse=True)

    print(f"[BODACC] {len(dossiers)} dossiers retenus (score >= {SCORE_MIN})")

    if not dossiers:
        print("[BODACC] Aucun dossier qualifié — pas de rapport généré.")
        return

    contenu = render_rapport(dossiers, rapport_date)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(contenu)

    print(f"[BODACC] Rapport écrit : {filename}")


if __name__ == "__main__":
    main()
