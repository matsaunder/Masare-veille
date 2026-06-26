"""
Veille BODACC — Procédures collectives
Récupère les annonces du jour, score les dossiers, génère rapport_YYYYMMDD.md
"""

import json
import requests
import re
import sys
from datetime import date, timedelta

API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

SCORE_MIN = 4


# ── Helpers ───────────────────────────────────────────────────────────────────

def s(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val if v is not None)
    if isinstance(val, dict):
        for k in ("texte", "value", "libelle", "denomination", "nom"):
            if k in val:
                return s(val[k])
        return " ".join(str(v) for v in val.values() if v is not None)
    return str(val)


def extract_embedded_json(text: str) -> dict:
    """Parse le premier objet JSON trouvé dans une chaîne de texte."""
    start = text.find('{')
    if start == -1:
        return {}
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return {}
    return {}


def debug_record(annonce: dict):
    print("[DEBUG] Structure BODACC premier enregistrement :", file=sys.stderr)
    for key in sorted(annonce.keys()):
        val = annonce[key]
        preview = repr(val)
        if len(preview) > 200:
            preview = preview[:200] + "…"
        print(f"  {key}: {preview}", file=sys.stderr)


# ── Extraction depuis le JSON embedded dans publicationavis ───────────────────

def get_personne(annonce: dict) -> dict:
    """Retourne le dict 'personne' depuis publicationavis JSON ou champs directs."""
    # 1. Cherche dans les champs directs (ancienne structure API)
    for nested_key in ("commercant", "personne", "entreprise", "debiteur"):
        nested = annonce.get(nested_key)
        if isinstance(nested, dict) and nested:
            return nested

    # 2. Parse le JSON embedded dans publicationavis
    texte_brut = annonce.get("publicationavis") or ""
    if isinstance(texte_brut, str) and '{' in texte_brut:
        data = extract_embedded_json(texte_brut)
        if data:
            # Structure {"personne": {...}} ou directement la personne
            return data.get("personne", data)

    return {}


def get_denomination(annonce: dict) -> str:
    # 1. Champ direct API
    for field in ("denomination", "denomination_personne_morale", "raisonsociale"):
        v = s(annonce.get(field)).strip()
        if v:
            return v

    # 2. Depuis l'objet personne (JSON embedded ou champ direct)
    personne = get_personne(annonce)
    if personne:
        d = personne.get("denomination") or personne.get("raisonsociale") or ""
        if d:
            return str(d).strip()
        # Personne physique
        nom = personne.get("nom") or ""
        prenom = personne.get("prenom") or ""
        if nom:
            return f"{prenom} {nom}".strip() if prenom else str(nom).strip()

    # 3. Regex sur tout le texte
    texte = get_full_text(annonce)
    for pat in (
        r'"denomination"\s*:\s*"([^"]{2,80})"',
        r'D[ée]nomination\s*:?\s*([A-ZÀ-Ÿ][^\n,;]{2,60}(?:SAS|SARL|SA|SCI|EURL|SNC|SASU))',
    ):
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return "—"


def get_siren(annonce: dict) -> str:
    # 1. Champ direct
    for field in ("siren", "siret", "numerosiren"):
        v = re.sub(r"\s+", "", s(annonce.get(field, "")))
        if re.match(r"^\d{9,14}$", v):
            return v[:9]

    # 2. Dans registre (liste contenant souvent le SIREN brut)
    registre = annonce.get("registre")
    candidates = registre if isinstance(registre, list) else [s(registre)]
    for item in candidates:
        clean = re.sub(r"\s+", "", str(item))
        if re.match(r"^\d{9}$", clean):
            return clean

    # 3. Dans l'objet personne → numeroImmatriculation → numeroIdentification
    personne = get_personne(annonce)
    if personne:
        immat = personne.get("numeroImmatriculation") or {}
        if isinstance(immat, dict):
            num = re.sub(r"\s+", "", str(immat.get("numeroIdentification") or ""))
            if re.match(r"^\d{9}$", num):
                return num

    # 4. Regex dans le texte
    texte = get_full_text(annonce)
    for pat in (
        r'"numeroIdentification"\s*:\s*"([\d\s]{9,14})"',
        r'SIREN\s*[N°n°]*\s*[:\s]+([\d\s]{9,14})',
        r'RCS[^"]*"([\d\s]{9,14})"',
    ):
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            v = re.sub(r"\s+", "", m.group(1))
            if re.match(r"^\d{9}$", v):
                return v

    return "—"


def get_activite(annonce: dict) -> str:
    for field in ("activite", "activiteprincipale", "libelle_activite"):
        v = s(annonce.get(field)).strip()
        if v and '{' not in v:
            return v

    personne = get_personne(annonce)
    if personne:
        v = str(personne.get("activite") or "").strip()
        if v:
            return v

    # Regex
    texte = get_full_text(annonce)
    m = re.search(r'"activite"\s*:\s*"([^"]{5,150})"', texte)
    return m.group(1).strip() if m else ""


def get_forme_juridique(annonce: dict) -> str:
    personne = get_personne(annonce)
    if personne:
        v = str(personne.get("formeJuridique") or "").strip()
        if v:
            return v
    texte = get_full_text(annonce)
    m = re.search(r'"formeJuridique"\s*:\s*"([^"]{3,80})"', texte)
    return m.group(1).strip() if m else ""


def get_adresse(annonce: dict) -> str:
    personne = get_personne(annonce)
    if personne:
        adr = personne.get("adresseSiegeSoc") or personne.get("adresse") or {}
        if isinstance(adr, dict):
            parts = [
                str(adr.get("numeroVoie") or ""),
                str(adr.get("typeVoie") or ""),
                str(adr.get("nomVoie") or ""),
                str(adr.get("codePostal") or ""),
                str(adr.get("ville") or ""),
            ]
            return " ".join(p for p in parts if p).strip()
        if isinstance(adr, str):
            return adr.strip()
    return ""


def get_ville(annonce: dict) -> str:
    v = s(annonce.get("ville")).strip().title()
    if v:
        return v
    # Depuis tribunal
    trib = s(annonce.get("tribunal")).strip()
    m = re.search(r"\bde\s+([A-ZÀ-Ÿ][a-zà-ÿ\-]+)", trib)
    if m:
        return m.group(1)
    # Depuis personne
    personne = get_personne(annonce)
    if personne:
        immat = personne.get("numeroImmatriculation") or {}
        if isinstance(immat, dict):
            greffe = immat.get("nomGreffeImmat") or ""
            if greffe:
                return str(greffe).strip().title()
    return "—"


def get_tribunal(annonce: dict) -> str:
    for field in ("tribunal", "tribunalname", "juridiction"):
        v = s(annonce.get(field)).strip()
        if v and not re.match(r"^\d+$", v.replace(" ", "")):
            return v
    return ""


def get_full_text(annonce: dict) -> str:
    """Récupère le texte brut le plus complet disponible."""
    for field in ("publicationavis", "contenu", "texte", "avis", "description"):
        v = annonce.get(field)
        if v and len(str(v)) > 5:
            return str(v)
    # Concatène tous les champs string longs
    parts = []
    for val in annonce.values():
        if isinstance(val, str) and len(val) > 20:
            parts.append(val)
    return " ".join(parts)


# ── Secteurs & procédure ──────────────────────────────────────────────────────

SECTEURS = [
    ("Défense & Aéronautique",    ["aéronaut", "défense", "armement", "naval", "spatia", "missile", "militair", "balistiq"]),
    ("Santé & Pharmaceutique",    ["pharmaceut", "médical", "biotech", "biotechnolog", "laboratoir", "clinique", "médecin"]),
    ("Industrie manufacturière",  ["usinage", "mécaniqu", "manufactur", "fonderie", "forge", "métallurg", "plastiqu", "composit", "sous-trait"]),
    ("Tech & Numérique",          ["informatique", "logiciel", "numérique", "télécom", "cybersécur", "cloud", "software", "digital", "édition"]),
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
    haystack = (activite + " " + texte[:800]).lower()
    for secteur, keywords in SECTEURS:
        if any(k in haystack for k in keywords):
            bitd = any(k in haystack for k in BITD_KEYWORDS)
            return secteur, bitd
    return "Autres", False


def detect_procedure(typeavis: str, texte: str) -> "tuple[str, str, int]":
    combined = (texte + " " + typeavis).lower()
    if "liquidation judiciaire" in combined:
        return "Liquidation judiciaire", "Haute", 2
    if "redressement judiciaire" in combined:
        return "Redressement judiciaire", "Haute", 3
    if "sauvegarde" in combined:
        return "Sauvegarde", "Moyenne", 1
    if "rétablissement professionnel" in combined:
        return "Rétablissement professionnel", "Basse", 0
    return typeavis or "Procédure collective", "Basse", 0


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
            key = re.sub(r"^[^A-ZÀ-Ÿ]+", "", val, flags=re.IGNORECASE).lower()
            if key not in seen and len(val) > 5:
                seen.add(key)
                contacts.append(val)
    return " ; ".join(contacts[:4])


# ── Score & mise en forme ─────────────────────────────────────────────────────

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
    forme = get_forme_juridique(annonce)
    adresse = get_adresse(annonce)
    date_par = s(annonce.get("dateparution") or annonce.get("dateParution"))

    synthese = build_synthese(activite, forme, adresse, tribunal, date_par, texte)

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
        "forme": forme,
        "adresse": adresse,
        "tribunal": tribunal,
        "date": date_par,
        "synthese": synthese,
        "contacts": extract_contacts(texte),
    }


def build_synthese(activite, forme, adresse, tribunal, date_par, texte) -> str:
    parts = []
    if activite:
        parts.append(f"Activité : {activite}.")
    if forme:
        parts.append(f"Forme juridique : {forme}.")
    if adresse:
        parts.append(f"Siège : {adresse}.")
    if tribunal:
        parts.append(f"Tribunal : {tribunal}.")
    if date_par:
        parts.append(f"Parution BODACC : {date_par}.")
    # Extrait la partie textuelle AVANT le JSON (souvent descriptive)
    pre_json = texte.split('{')[0].strip() if '{' in texte else texte
    excerpt = re.sub(r"\s+", " ", pre_json).strip()[:300]
    if excerpt and len(excerpt) > 10:
        parts.append(excerpt + ("…" if len(pre_json) > 300 else ""))
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
        return r.json().get("results", [])
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
        if d.get("forme"):
            lines.append(f"- **Forme juridique** : {d['forme']}")
        if d.get("tribunal"):
            lines.append(f"- **Tribunal** : {d['tribunal']}")
        lines.append(f"- **BITD** : {fmt_flag(d['bitd'])}")
        lines.append(f"- **Marque** : {fmt_flag(d['marque'])}")
        if d.get("ebitda"):
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
