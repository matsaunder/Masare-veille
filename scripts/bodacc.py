"""
Veille BODACC — Procédures collectives
Récupère les annonces du jour, score les dossiers, génère rapport_YYYYMMDD.md
"""

import requests
import re
import sys
from datetime import date, timedelta

API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

SCORE_MIN = 4


# ── Helpers ──────────────────────────────────────────────────────────────────

def s(val) -> str:
    """Aplatit n'importe quel champ BODACC en chaîne propre."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val if v is not None)
    if isinstance(val, dict):
        # Essaie les clés texte courantes
        for k in ("texte", "value", "libelle", "denomination", "nom"):
            if k in val:
                return s(val[k])
        return " ".join(str(v) for v in val.values() if v is not None)
    return str(val)


def debug_record(annonce: dict):
    """Affiche tous les champs du premier enregistrement (logs GitHub Actions)."""
    print("[DEBUG] Structure du premier enregistrement BODACC :", file=sys.stderr)
    for key in sorted(annonce.keys()):
        val = annonce[key]
        preview = repr(val)
        if len(preview) > 120:
            preview = preview[:120] + "…"
        print(f"  {key}: {preview}", file=sys.stderr)


# ── Extraction robuste ────────────────────────────────────────────────────────

def get_denomination(annonce: dict) -> str:
    # Champs directs possibles selon version API BODACC
    for field in ("denomination", "denomination_personne_morale", "nom_personne", "raisonsociale"):
        v = s(annonce.get(field)).strip()
        if v:
            return v
    # Cherche dans les objets imbriqués courants
    for nested_key in ("commercant", "personne", "entreprise", "debiteur"):
        nested = annonce.get(nested_key)
        if isinstance(nested, dict):
            for sub in ("denomination", "raisonsociale", "nom"):
                v = s(nested.get(sub, "")).strip()
                if v:
                    return v
    # Extraction depuis le texte de l'annonce
    texte = get_full_text(annonce)
    for pat in (
        r"(?:D[ée]nomination(?:\s+sociale)?\s*:?\s*)([A-ZÀ-Ÿ][^\n,;]{2,60}(?:SAS|SARL|SA|SCI|EURL|SNC|SCP|SCM|SASU))",
        r"(?:Soci[eé]t[eé][^\n:]*:\s*)([A-ZÀ-Ÿ][^\n,;]{2,60}(?:SAS|SARL|SA|SCI|EURL|SNC|SCP|SCM|SASU))",
        r"(?:la soci[eé]t[eé]\s+)([A-ZÀ-Ÿ][A-ZÀ-Ÿ\s\-\.&]{2,50}(?:SAS|SARL|SA|SCI|EURL|SNC|SCP))",
    ):
        m = re.search(pat, texte)
        if m:
            return m.group(1).strip()
    return "—"


def get_siren(annonce: dict) -> str:
    # Champ direct
    for field in ("siren", "siret", "numero_siren", "numerosiren"):
        v = re.sub(r"\s+", "", s(annonce.get(field, "")))
        if re.match(r"^\d{9,14}$", v):
            return v[:9]  # garde 9 chiffres SIREN
    # Dans registre (souvent une liste contenant le SIREN)
    registre = annonce.get("registre")
    candidates = registre if isinstance(registre, list) else [s(registre)]
    for item in candidates:
        clean = re.sub(r"\s+", "", str(item))
        if re.match(r"^\d{9}$", clean):
            return clean
    # Extraction textuelle
    texte = get_full_text(annonce)
    for pat in (
        r"SIREN\s*[N°n°]*\s*[:\s]+(\d[\d\s]{6,10}\d)",
        r"(?:n[°o]\s+)?RCS[^:]*[:\s]+(\d[\d\s]{6,10}\d)",
        r"SIRET\s*[:\s]+(\d[\d\s]{11,16}\d)",
    ):
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", "", m.group(1))[:9]
    return "—"


def get_full_text(annonce: dict) -> str:
    """Tente tous les champs texte connus pour récupérer l'annonce complète."""
    for field in ("publicationavis", "contenu", "texte", "avis", "corps", "description",
                  "publicationavis_facette"):
        v = annonce.get(field)
        if v and len(str(v)) > 5:
            return s(v)
    # Si tous les champs sont courts, concatène tout ce qui est string long
    parts = []
    for val in annonce.values():
        if isinstance(val, str) and len(val) > 20:
            parts.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and len(item) > 20:
                    parts.append(item)
    return " ".join(parts)


def get_activite(annonce: dict) -> str:
    for field in ("activite", "activiteprincipale", "libelle_activite", "naf_lib"):
        v = s(annonce.get(field)).strip()
        if v:
            return v
    # Dans objet imbriqué
    for nested_key in ("commercant", "entreprise"):
        nested = annonce.get(nested_key)
        if isinstance(nested, dict):
            for sub in ("activite", "activiteprincipale", "libelle"):
                v = s(nested.get(sub, "")).strip()
                if v:
                    return v
    return ""


def get_ville(annonce: dict) -> str:
    v = s(annonce.get("ville")).strip().title()
    if v:
        return v
    v = s(annonce.get("tribunal")).strip()
    # "TJ de Lyon" → "Lyon"
    m = re.search(r"\bde\s+([A-ZÀ-Ÿ][a-zà-ÿ\-]+)", v)
    return m.group(1) if m else v or "—"


def get_tribunal(annonce: dict) -> str:
    for field in ("tribunal", "tribunalname", "juridiction"):
        v = s(annonce.get(field)).strip()
        if v and not re.match(r"^\d+$", v.replace(" ", "")):
            return v
    return ""


# ── Secteurs & procédure ──────────────────────────────────────────────────────

SECTEURS = [
    ("Défense & Aéronautique",    ["aéronaut", "défense", "armement", "naval", "spatia", "missile", "militair", "balistiq"]),
    ("Santé & Pharmaceutique",    ["pharmaceut", "médical", "biotech", "biotechnolog", "laboratoir", "clinique", "médecin"]),
    ("Industrie manufacturière",  ["usinage", "mécaniqu", "manufactur", "fonderie", "forge", "métallurg", "plastiqu", "composit", "sous-trait"]),
    ("Tech & Numérique",          ["informatique", "logiciel", "numérique", "télécom", "cybersécur", "cloud", "software", "digital"]),
    ("BTP & Construction",        ["construction", "bâtiment", "travaux publics", "rénovation", "génie civil", "maçonnerie", "charpente", "plomberie", "électricité"]),
    ("Transport & Logistique",    ["transport", "logistique", "fret", "camion", "transitaire", "messagerie", "entrepôt", "déménagement"]),
    ("Commerce & Distribution",   ["commerce", "distribution", "négoce", "grossiste", "retail", "grande surface", "vente"]),
    ("Hôtellerie & Restauration", ["restaur", "hôtel", "tourisme", "café", "brasserie", "traiteur", "snack", "pizz"]),
    ("Immobilier",                ["immobilier", "foncier", "promotion immob", "agence immob"]),
    ("Énergie & Environnement",   ["énergie", "solaire", "éolien", "environnement", "déchets", "recyclage"]),
    ("Agroalimentaire",           ["agroalimentaire", "alimentaire", "agriculture", "viticole", "boulangerie", "fromagerie", "viande"]),
]

BITD_KEYWORDS = ["aéronaut", "défense", "armement", "naval", "spatia", "missile", "militair"]


def detect_secteur(activite: str, texte: str) -> "tuple[str, bool]":
    haystack = (activite + " " + texte[:500]).lower()
    for secteur, keywords in SECTEURS:
        if any(k in haystack for k in keywords):
            bitd = any(k in haystack for k in BITD_KEYWORDS)
            return secteur, bitd
    return "Autres", False


def detect_procedure(typeavis: str, texte: str) -> "tuple[str, str, int]":
    # Cherche d'abord dans le texte complet (plus fiable que typeavis_lib)
    combined = (texte + " " + typeavis).lower()

    # Ordre important : liquidation avant redressement pour éviter faux positifs
    if "liquidation judiciaire" in combined and "plan" not in combined[:100]:
        return "Liquidation judiciaire", "Haute", 2
    if "redressement judiciaire" in combined:
        return "Redressement judiciaire", "Haute", 3
    if "sauvegarde" in combined:
        return "Sauvegarde", "Moyenne", 1
    if "rétablissement professionnel" in combined:
        return "Rétablissement professionnel", "Basse", 0
    if "procédure collective" in combined or "faillite" in combined:
        return "Procédure collective", "Basse", 0
    # Fallback sur le type BODACC
    return typeavis or "Procédure collective", "Basse", 0


# ── Score & contacts ──────────────────────────────────────────────────────────

def extract_contacts(texte: str) -> str:
    contacts = []
    patterns = [
        r"(administrateur(?:s)?\s+judiciaire(?:s)?\s*:?\s*(?:Me\.?\s*)?[A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,3})",
        r"(mandataire(?:s)?\s+judiciaire(?:s)?\s*:?\s*(?:Me\.?\s*)?[A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,3})",
        r"(liquidateur(?:s)?\s*:?\s*(?:Me\.?\s*)?[A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,3})",
        r"(Me\.?\s+[A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,2})",
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, texte, re.IGNORECASE):
            val = re.sub(r"\s+", " ", m.group(1)).strip(" :.,;")
            key = re.sub(r"^[^A-ZÀ-Ÿ]+", "", val).lower()
            if key not in seen and len(val) > 5:
                seen.add(key)
                contacts.append(val)
    return " ; ".join(contacts[:4])


def score_dossier(annonce: dict) -> dict:
    texte = get_full_text(annonce)
    activite = get_activite(annonce)
    typeavis = s(annonce.get("typeavis_lib"))

    procedure, urgence, proc_bonus = detect_procedure(typeavis, texte)
    secteur, bitd = detect_secteur(activite, texte)

    score = 5 + proc_bonus
    if bitd:
        score += 2
    if secteur in ("Santé & Pharmaceutique", "Tech & Numérique", "Énergie & Environnement"):
        score += 1
    score = min(10, score)

    nom = get_denomination(annonce)
    siren = get_siren(annonce)
    ville = get_ville(annonce)
    tribunal = get_tribunal(annonce)

    # Synthèse courte depuis le texte
    synthese = build_synthese(annonce, activite, typeavis, tribunal, texte)

    return {
        "nom": nom,
        "siren": siren,
        "ville": ville,
        "score": score,
        "secteur": secteur,
        "procedure": procedure,
        "urgence": urgence,
        "bitd": bitd,
        "marque": False,
        "ebitda": None,
        "synthese": synthese,
        "contacts": extract_contacts(texte),
    }


def build_synthese(annonce, activite, typeavis, tribunal, texte) -> str:
    date_par = s(annonce.get("dateparution") or annonce.get("dateParution"))
    parts = []
    if activite:
        parts.append(f"Activité : {activite}.")
    if tribunal:
        parts.append(f"Tribunal : {tribunal}.")
    if date_par:
        parts.append(f"Parution BODACC : {date_par}.")
    excerpt = re.sub(r"\s+", " ", texte).strip()[:400]
    if excerpt:
        parts.append(excerpt + ("…" if len(texte) > 400 else ""))
    return " ".join(parts)


# ── Fetch ─────────────────────────────────────────────────────────────────────

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

def fmt_flag(val) -> str:
    return "Oui" if val else "Non"


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
    since = (today - timedelta(days=2)).isoformat()
    rapport_date = today.strftime("%Y%m%d")
    filename = f"rapport_{rapport_date}.md"

    print(f"[BODACC] Récupération depuis {since}…")
    annonces = fetch_annonces(since)
    print(f"[BODACC] {len(annonces)} annonces reçues")

    if not annonces:
        print("[BODACC] Aucune annonce — pas de rapport généré.")
        return

    # Debug : affiche la structure du premier enregistrement
    debug_record(annonces[0])

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
