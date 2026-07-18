"""
MASARE - Veille Distressed BODACC
Script de surveillance automatique des procédures collectives
Critères affinés 18 juillet 2026

Sources d'enrichissement :
1. BODACC (annonces-commerciales) — procédure du jour
2. Pappers API — financials 3 ans (CA, EBE, résultat), dirigeants, capital
3. Recherche Entreprises (data.gouv.fr) — catégorie PME/ETI/GE, effectif officiel, statut
4. Historique BODACC du SIREN — procédures passées (contexte investissement)

Logique issues GitHub : 1 issue max par SIREN (upsert)
"""

import os
import requests
import json
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
PAPPERS_TOKEN = os.environ.get("PAPPERS_TOKEN", "")

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
GITHUB_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"

BODACC_API        = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
PAPPERS_API       = "https://api.pappers.fr/v2/entreprise"
API_GOUV_URL      = "https://recherche-entreprises.api.gouv.fr/search"

SCORE_MIN    = 8
CA_MIN_EUR   = 20_000_000
JOURS_RECUL  = 2

# ---------------------------------------------------------------------------
# SECTEURS CIBLES
# ---------------------------------------------------------------------------

SECTEURS = {
    "Défense & Aéronautique (BITD)": {
        "mots_cles": ["aéronaut", "défense", "armement", "naval", "spatia", "bitd",
                      "missi", "munition", "drone", "radar"],
        "priorite": 1,
    },
    "Tech / SaaS B2B Vertical": {
        "mots_cles": ["saas", "logiciel métier", "erp", "éditeur de logiciel", "software",
                      "logiciel", "informatique", "cybersécur", "cloud",
                      "intelligence artificielle", "ia ", "progiciel"],
        "priorite": 1,
    },
    "Chimie de Spécialités": {
        "mots_cles": ["chimie", "spécialités chimiques", "revêtement", "traitement de surface",
                      "peinture industrielle", "coatings", "adhésif", "polymère", "résine", "pigment"],
        "priorite": 1,
    },
    "Industrie Manufacturière à Barrières Élevées": {
        "mots_cles": ["usinage", "mécaniqu", "manufactur", "métallurg", "fonderie", "forge",
                      "estampage", "tôlerie", "soudure", "chaudronnerie", "équipement industriel",
                      "machine-outil", "pharma", "laboratoir", "biotech", "médical", "medtech",
                      "dispositif médical"],
        "priorite": 1,
    },
    "Immobilier & Hôtellerie": {
        "mots_cles": ["immobilier", "foncier", "hôtel", "hôtellerie", "résidence étudiante",
                      "coliving", "data center", "logistique urbaine", "entrepôt", "bureaux",
                      "commerce retail", "centre commercial", "résidence gérée"],
        "priorite": 2,
    },
    "Marques & Retail Premium": {
        "mots_cles": ["marque", "luxe", "maroquinerie", "mode", "licenc", "prêt-à-porter",
                      "cosmétique premium", "bijouterie", "horlogerie", "enseigne"],
        "priorite": 2,
    },
    "Énergie & Environnement": {
        "mots_cles": ["énergie", "solaire", "éolien", "recyclage", "déchets", "environnement",
                      "cleantech", "biomasse", "cogénération"],
        "priorite": 2,
    },
    # EXCLUS
    "BTP & Construction [EXCLU]": {
        "mots_cles": ["construction", "bâtiment", "travaux publics", "maçonnerie",
                      "gros œuvre", "génie civil"],
        "priorite": -99,
    },
    "Transport & Logistique Généraliste [EXCLU]": {
        "mots_cles": ["transport routier", "fret", "transitaire", "messagerie",
                      "livraison", "camionnage", "taxi", "vtc", "ambulance"],
        "priorite": -99,
    },
    "Commerce & Distribution Généraliste [EXCLU]": {
        "mots_cles": ["commerce", "négoce", "grossiste", "distribution alimentaire",
                      "supermarché", "épicerie"],
        "priorite": -99,
    },
    "Restauration Standard [EXCLU]": {
        "mots_cles": ["restaur", "café", "traiteur", "snack", "brasserie",
                      "pizzeria", "fast-food"],
        "priorite": -99,
    },
    "Immobilier Santé [EXCLU]": {
        "mots_cles": ["ehpad", "maison de retraite", "clinique", "ssr",
                      "soins de suite", "résidence médicalisée"],
        "priorite": -99,
    },
    "Services à la Personne [EXCLU]": {
        "mots_cles": ["aide à domicile", "service à la personne",
                      "garde d'enfant", "ménage à domicile"],
        "priorite": -99,
    },
}

BASSINS_PRIORITAIRES = [
    "paris", "île-de-france", "hauts-de-seine", "seine-saint-denis", "val-de-marne",
    "lyon", "bordeaux", "toulouse", "nantes", "lille", "marseille", "grenoble", "strasbourg",
    "rennes", "rouen", "montpellier", "nice", "tours", "metz", "nancy",
    "clermont-ferrand", "angers", "le mans", "caen", "amiens", "besançon", "mulhouse", "pau",
    "orléans", "reims", "dijon", "valenciennes", "dunkerque", "brest", "limoges",
    "poitiers", "saint-étienne", "toulon", "avignon", "perpignan", "bayonne", "annecy",
    "isère", "rhône", "nord", "bas-rhin", "haut-rhin", "moselle", "gironde",
    "haute-garonne", "loire-atlantique", "bouches-du-rhône", "alpes-maritimes",
]

PROCEDURES = {
    "redressement judiciaire": +3,
    "liquidation judiciaire":  +2,
    "plan de cession":         +3,
    "résolution de plan":      +2,
    "mandat ad hoc":           +2,
    "conciliation":            +1,
    "sauvegarde":              -2,
}

# ---------------------------------------------------------------------------
# UTILITAIRES
# ---------------------------------------------------------------------------

def normalise(texte: str) -> str:
    return texte.lower() if texte else ""


def parse_json_field(record: dict, cle: str) -> dict:
    raw = record.get(cle, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def extraire_personne(record: dict) -> dict:
    lp = parse_json_field(record, "listepersonnes")
    personne = lp.get("personne", lp.get("personnes", None))
    if isinstance(personne, list):
        personne = personne[0] if personne else {}
    return personne if isinstance(personne, dict) else {}


def extraire_denomination(record: dict) -> str:
    nom = record.get("commercant", "")
    if nom:
        return nom
    p = extraire_personne(record)
    return (
        p.get("denomination", "")
        or p.get("nomCommercial", "")
        or f"{p.get('nom', '')} {p.get('prenom', '')}".strip()
        or "N/A"
    )


def extraire_siren(record: dict) -> str:
    registre = record.get("registre", [])
    if registre:
        siren = str(registre[0]).replace(" ", "").strip()
        if len(siren) >= 9:
            return siren[:9]
    p = extraire_personne(record)
    num = p.get("numeroImmatriculation", {})
    if isinstance(num, dict):
        return num.get("numeroIdentification", "").replace(" ", "") or "N/A"
    return "N/A"


def extraire_adresse(record: dict) -> str:
    ville = record.get("ville", "")
    cp    = record.get("cp", "")
    dept  = record.get("departement_nom_officiel", "")
    if ville and cp:
        return f"{ville} ({cp}) — {dept}"
    return ville or dept or "N/A"


def extraire_tribunal(record: dict) -> str:
    return record.get("tribunal", "") or "N/A"


def extraire_forme_juridique(record: dict) -> str:
    p = extraire_personne(record)
    return p.get("formeJuridique", "") or p.get("typePersonne", "") or "N/A"


def extraire_activite(record: dict) -> str:
    p = extraire_personne(record)
    return p.get("activite", "") or ""


def extraire_contacts(record: dict) -> list:
    contacts = []
    lp = parse_json_field(record, "listepersonnes")
    labels_map = {
        "administrateurJudiciaire": "Administrateur judiciaire",
        "mandataireJudiciaire":     "Mandataire judiciaire",
        "liquidateur":              "Liquidateur",
        "representantCreanciers":   "Représentant des créanciers",
        "mandataireLiquidateur":    "Mandataire liquidateur",
    }
    for cle, label in labels_map.items():
        val = lp.get(cle, "")
        if val:
            contacts.append(f"{label} : {val}")
    return contacts


def extraire_procedure(record: dict) -> str:
    jugement = parse_json_field(record, "jugement")
    if jugement:
        return (
            jugement.get("nature", "")
            or jugement.get("famille", "")
            or jugement.get("type", "")
            or ""
        )
    return record.get("typeavis_lib", "") or record.get("familleavis_lib", "") or ""


def est_personne_physique(record: dict) -> bool:
    p = extraire_personne(record)
    if p.get("typePersonne", "").lower() == "pp":
        return True
    if p.get("prenom") and not p.get("denomination") and not p.get("nomCommercial"):
        return True
    return False


def fmt_eur(valeur) -> str:
    if valeur is None:
        return "N/D"
    try:
        v = int(valeur)
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f} M€"
        elif abs(v) >= 1_000:
            return f"{v / 1_000:.0f} k€"
        return f"{v} €"
    except (ValueError, TypeError):
        return str(valeur)


# ---------------------------------------------------------------------------
# SOURCE 1 — PAPPERS : données financières + filtre taille/rentabilité
# ---------------------------------------------------------------------------

def enrichir_depuis_pappers(siren: str) -> dict:
    """
    Enrichit depuis Pappers.
    Filtre : CA ≥ 20M€  OU  résultat net positif sur au moins 1 des 3 derniers exercices.
    Retourne dict avec ca_filtre_ok + toutes les données financières.
    """
    if not PAPPERS_TOKEN or siren == "N/A":
        return {"ca_filtre_ok": True, "source": "pappers_absent"}

    try:
        resp = requests.get(
            PAPPERS_API,
            params={
                "api_token": PAPPERS_TOKEN,
                "siren": siren,
                "extrait_kbis": "false",
                "dirigeants": "true",
                "beneficiaires_effectifs": "false",
                "finances": "true",
            },
            timeout=10,
        )
        if not resp.ok:
            print(f"  [Pappers] Erreur {resp.status_code} pour SIREN {siren}")
            return {"ca_filtre_ok": True, "source": "pappers_erreur"}

        data = resp.json()

        # --- Filtre taille + rentabilité historique ---
        ca_recent = data.get("chiffre_affaires")
        comptes_raw = data.get("comptes_sociaux_saisis", [])
        if not isinstance(comptes_raw, list):
            comptes_raw = []
        comptes_tri = sorted(comptes_raw, key=lambda x: x.get("annee", 0), reverse=True)[:3]

        ca_ok = False
        if ca_recent is not None:
            try:
                ca_ok = float(ca_recent) >= CA_MIN_EUR
            except (ValueError, TypeError):
                pass

        rentable_ok = any(
            (c.get("resultat_net") or c.get("resultat") or 0) > 0
            for c in comptes_tri
        )

        ca_filtre_ok = ca_ok or rentable_ok

        if not ca_filtre_ok:
            raison = f"CA {fmt_eur(ca_recent)} < 20 M€ et aucun exercice bénéficiaire sur 3 ans"
            print(f"  [Pappers] SIREN {siren} écarté — {raison}")
            return {"ca_filtre_ok": False, "ca_recent": ca_recent, "raison": raison}

        # --- Dirigeant principal ---
        dirigeants = data.get("dirigeants", [])
        dirigeant = ""
        if dirigeants:
            d = dirigeants[0]
            prenom  = d.get("prenom", "")
            nom     = d.get("nom", d.get("denomination", ""))
            qualite = d.get("qualite", "")
            dirigeant = f"{prenom} {nom}".strip()
            if qualite:
                dirigeant += f" ({qualite})"

        return {
            "ca_filtre_ok": True,
            "ca_recent":    ca_recent,
            "effectif":     data.get("effectif", "N/D"),
            "capital":      data.get("capital"),
            "naf":          f"{data.get('code_naf', '')} — {data.get('libelle_code_naf', '')}".strip(" —") or "N/D",
            "date_creation": data.get("date_creation", "N/D"),
            "dirigeant":    dirigeant or "N/D",
            "comptes":      comptes_tri,
            "source":       "pappers_ok",
        }

    except Exception as e:
        print(f"  [Pappers] Exception pour SIREN {siren} : {e}")
        return {"ca_filtre_ok": True, "source": "pappers_exception"}


# ---------------------------------------------------------------------------
# SOURCE 2 — API RECHERCHE ENTREPRISES (data.gouv.fr) : catégorie + statut
# ---------------------------------------------------------------------------

TRANCHE_EFFECTIF = {
    "NN": "Non employeuse",
    "00": "0 salarié",
    "01": "1 à 2 salariés",
    "02": "3 à 5 salariés",
    "03": "6 à 9 salariés",
    "11": "10 à 19 salariés",
    "12": "20 à 49 salariés",
    "21": "50 à 99 salariés",
    "22": "100 à 199 salariés",
    "31": "200 à 249 salariés",
    "32": "250 à 499 salariés",
    "41": "500 à 999 salariés",
    "42": "1 000 à 1 999 salariés",
    "51": "2 000 à 4 999 salariés",
    "52": "5 000 à 9 999 salariés",
    "53": "10 000 salariés et plus",
}


def enrichir_depuis_api_gouv(siren: str) -> dict:
    """
    Appelle l'API Recherche Entreprises (data.gouv.fr) — gratuit, sans clé API.
    Retourne : categorie (PME/ETI/GE), effectif officiel, statut, dirigeants officiels.
    """
    if siren == "N/A":
        return {}

    try:
        resp = requests.get(
            API_GOUV_URL,
            params={"q": siren, "per_page": 1},
            timeout=8,
        )
        if not resp.ok:
            return {}

        results = resp.json().get("results", [])
        if not results:
            return {}

        e = results[0]
        tranche_code = e.get("tranche_effectif_salarie", "")
        effectif_label = TRANCHE_EFFECTIF.get(tranche_code, tranche_code or "N/D")
        categorie = e.get("categorie_entreprise", "N/D")  # PME / ETI / GE
        statut = "Active" if e.get("etat_administratif") == "A" else "Cessée/Inconnue"

        # Dirigeants officiels (RNE)
        dirigeants_rne = []
        for d in e.get("dirigeants", [])[:3]:
            nom    = d.get("nom", d.get("denomination", ""))
            prenom = d.get("prenom", "")
            qualite = d.get("qualite", "")
            libelle = f"{prenom} {nom}".strip()
            if qualite:
                libelle += f" — {qualite}"
            if libelle:
                dirigeants_rne.append(libelle)

        return {
            "categorie":       categorie,
            "effectif_officiel": effectif_label,
            "statut":          statut,
            "dirigeants_rne":  dirigeants_rne,
            "annee_effectif":  str(e.get("annee_effectif_salarie", "")),
        }

    except Exception as e:
        print(f"  [API Gouv] Exception pour SIREN {siren} : {e}")
        return {}


# ---------------------------------------------------------------------------
# SOURCE 3 — HISTORIQUE BODACC DU SIREN : procédures passées
# ---------------------------------------------------------------------------

def historique_bodacc(siren: str) -> list:
    """
    Récupère les 8 dernières annonces BODACC pour ce SIREN.
    Retourne une liste de dict {date, procedure} pour l'affichage dans l'issue.
    """
    if siren == "N/A":
        return []

    try:
        resp = requests.get(
            BODACC_API,
            params={
                "where": f'registre like "%{siren}%"',
                "order_by": "dateparution desc",
                "limit": 8,
            },
            timeout=10,
        )
        if not resp.ok:
            return []

        results = resp.json().get("results", [])
        historique = []
        for r in results:
            date_p = r.get("dateparution", "N/D")
            proc = extraire_procedure(r)
            famille = r.get("familleavis_lib", "")
            type_avis = r.get("typeavis_lib", "")
            label = proc or type_avis or famille or "Annonce"
            historique.append({"date": date_p, "procedure": label})

        return historique

    except Exception as e:
        print(f"  [Historique BODACC] Exception pour SIREN {siren} : {e}")
        return []


# ---------------------------------------------------------------------------
# DÉTECTION SECTEUR ET SCORING
# ---------------------------------------------------------------------------

def detecter_secteur(texte_complet: str):
    texte = normalise(texte_complet)
    for nom, config in SECTEURS.items():
        if config["priorite"] == -99:
            for mot in config["mots_cles"]:
                if mot in texte:
                    return nom, -99
    for priorite_cible in [1, 2]:
        for nom, config in SECTEURS.items():
            if config["priorite"] == priorite_cible:
                for mot in config["mots_cles"]:
                    if mot in texte:
                        return nom, priorite_cible
    return None, 0


def est_personne_physique(record: dict) -> bool:
    p = extraire_personne(record)
    if p.get("typePersonne", "").lower() == "pp":
        return True
    if p.get("prenom") and not p.get("denomination") and not p.get("nomCommercial"):
        return True
    return False


def scorer_dossier(record: dict) -> tuple:
    if est_personne_physique(record):
        return 0, None, "", "Basse", False

    denomination  = extraire_denomination(record)
    activite      = extraire_activite(record)
    adresse       = extraire_adresse(record)
    procedure_raw = extraire_procedure(record)
    tribunal      = extraire_tribunal(record)

    texte_complet = f"{denomination} {activite} {procedure_raw} {tribunal}"
    secteur_detecte, priorite = detecter_secteur(texte_complet)

    if priorite in (-99, 0):
        return 0, secteur_detecte if priorite == -99 else None, procedure_raw, "Basse", False

    score = 0
    if priorite == 1:
        score += 6
    elif priorite == 2:
        score += 4

    if any(m in normalise(texte_complet) for m in ["bitd", "armement", "défense", "aéronaut", "naval", "dga"]):
        score += 2

    proc_lower = normalise(procedure_raw)
    for proc, bonus in PROCEDURES.items():
        if proc in proc_lower:
            score += bonus
            break

    texte_geo = normalise(f"{adresse} {tribunal}")
    geo_match = any(b in texte_geo for b in BASSINS_PRIORITAIRES)
    if geo_match:
        score += 1

    if "liquidation" in proc_lower or "cession" in proc_lower or "résolution" in proc_lower:
        urgence = "Haute"
    elif "redressement" in proc_lower:
        urgence = "Haute"
    elif "sauvegarde" in proc_lower:
        urgence = "Basse"
    else:
        urgence = "Moyenne"

    return min(score, 10), secteur_detecte, procedure_raw, urgence, geo_match


# ---------------------------------------------------------------------------
# RÉCUPÉRATION BODACC (jour J)
# ---------------------------------------------------------------------------

def fetch_bodacc(nb_jours: int = JOURS_RECUL) -> list:
    date_debut = (datetime.now() - timedelta(days=nb_jours)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            BODACC_API,
            params={
                "where": f'familleavis_lib:"Procédures collectives" and dateparution>="{date_debut}"',
                "limit": 100,
                "order_by": "dateparution desc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de récupérer les données BODACC : {e}")
        return []


# ---------------------------------------------------------------------------
# GÉNÉRATION RAPPORT MARKDOWN
# ---------------------------------------------------------------------------

def generer_rapport(dossiers: list, date_rapport: str) -> str:
    lignes = [
        f"# Rapport Veille Distressed MASARE — {date_rapport}",
        "",
        f"**{len(dossiers)} dossier(s) retenu(s)** — score ≥ {SCORE_MIN}, CA ≥ 20 M€ ou rentabilité historique",
        "",
        "---",
        "",
    ]
    if not dossiers:
        lignes.append("*Aucun dossier retenu aujourd'hui.*")
        return "\n".join(lignes)

    groupes = {"Haute": [], "Moyenne": [], "Basse": []}
    for d in dossiers:
        groupes[d["urgence"]].append(d)

    emoji_map = {"Haute": "🔴", "Moyenne": "🟠", "Basse": "🟡"}
    for niveau in ["Haute", "Moyenne", "Basse"]:
        if not groupes[niveau]:
            continue
        lignes.append(f"## {emoji_map[niveau]} Urgence {niveau}")
        lignes.append("")
        for d in groupes[niveau]:
            geo_tag = " 📍" if d["geo_match"] else ""
            lignes.append(f"### {d['denomination']}{geo_tag} — Score {d['score']}/10")
            lignes.append("")
            lignes.append("| Champ | Valeur |")
            lignes.append("|-------|--------|")
            lignes.append(f"| SIREN | {d['siren']} |")
            lignes.append(f"| Adresse | {d['adresse']} |")
            lignes.append(f"| Procédure | {d['procedure']} |")
            lignes.append(f"| Secteur | {d['secteur'] or 'Non classifié'} |")
            lignes.append(f"| Date parution | {d['date_parution']} |")
            lignes.append("")
            if d["contacts"]:
                lignes.append("**Contacts :**")
                for c in d["contacts"]:
                    lignes.append(f"- {c}")
                lignes.append("")
            lignes.append("---")
            lignes.append("")

    lignes.append(f"*Généré automatiquement par MASARE-Veille — {datetime.now().strftime('%d/%m/%Y %H:%M')}*")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# GITHUB ISSUES — UPSERT (1 issue par SIREN max)
# ---------------------------------------------------------------------------

_issues_cache = None


def normalise_nom_issue(titre: str) -> str:
    match = re.search(
        r'ALERTE[^—–\-]*[—–\-]+\s*(.+?)\s*[—–\-]+\s*Score',
        titre, re.IGNORECASE | re.UNICODE
    )
    nom = match.group(1).strip() if match else titre
    nom = nom.lower()
    for forme in ["scop sa", "scop", " holding", " groupe", " group",
                  " industries", " industrie", " sas", " sa", " sarl",
                  " srl", " sci", " sca", " eurl", " sasu"]:
        nom = nom.replace(forme, "")
    return re.sub(r"[^a-z0-9]", "", nom).strip()


def charger_issues_ouvertes() -> dict:
    global _issues_cache
    if _issues_cache is not None:
        return _issues_cache
    if not GITHUB_TOKEN:
        _issues_cache = {}
        return _issues_cache

    index, page = {}, 1
    while True:
        resp = requests.get(
            f"{GITHUB_BASE}/issues",
            headers=GITHUB_HEADERS,
            params={"state": "open", "per_page": 100, "page": page},
        )
        if not resp.ok:
            break
        batch = resp.json()
        if not batch:
            break
        for issue in batch:
            if "pull_request" in issue:
                continue
            body = issue.get("body", "") or ""
            m = re.search(r"SIREN[^\|]*\|\s*([0-9]{9})", body)
            if m:
                index[m.group(1).strip()] = issue
            cle_nom = normalise_nom_issue(issue["title"])
            if cle_nom and cle_nom not in index:
                index[cle_nom] = issue
        page += 1

    _issues_cache = index
    return index


def construire_titre_issue(dossier: dict) -> str:
    urgence_tag = "URGENT" if dossier["urgence"] == "Haute" else "STANDARD"
    secteur_court = (dossier["secteur"] or "Non classifié").split("(")[0].strip()
    if len(secteur_court) > 40:
        secteur_court = secteur_court[:37] + "..."
    return (
        f"ALERTE {urgence_tag} — {dossier['denomination']} — "
        f"Score {dossier['score']}/10 — {secteur_court} — {dossier['urgence']} urgence"
    )


def construire_corps_issue(dossier: dict, pappers: dict, api_gouv: dict, historique: list, date_rapport: str) -> str:
    geo_tag = " 📍 Bassin prioritaire" if dossier["geo_match"] else ""

    # --- Bloc identité ---
    categorie      = api_gouv.get("categorie", "N/D")
    effectif_off   = api_gouv.get("effectif_officiel", "N/D")
    annee_eff      = api_gouv.get("annee_effectif", "")
    statut_adm     = api_gouv.get("statut", "N/D")
    dirigeants_rne = api_gouv.get("dirigeants_rne", [])

    # --- Bloc financier Pappers ---
    if pappers.get("source") == "pappers_ok":
        dirigeant  = pappers.get("dirigeant", "N/D")
        effectif_p = pappers.get("effectif", "N/D")
        capital    = fmt_eur(pappers.get("capital"))
        naf        = pappers.get("naf", "N/D")
        date_crea  = pappers.get("date_creation", "N/D")

        comptes = pappers.get("comptes", [])
        if comptes:
            lignes_fin = [
                "",
                "### 📊 Données Financières (Pappers)",
                "",
                "| Exercice | CA | Résultat net | EBE (EBITDA) |",
                "|----------|----|--------------|--------------|",
            ]
            for c in comptes:
                annee = c.get("annee", "N/D")
                ca_c  = fmt_eur(c.get("chiffre_affaires"))
                res   = fmt_eur(c.get("resultat_net") or c.get("resultat"))
                ebe   = fmt_eur(c.get("excedent_brut_exploitation"))
                lignes_fin.append(f"| {annee} | {ca_c} | {res} | {ebe} |")
            bloc_finances = "\n".join(lignes_fin)
        else:
            bloc_finances = f"\n### 📊 Données Financières\n\n| CA récent | {fmt_eur(pappers.get('ca_recent'))} |\n|-----------|------------|"

        infos_pappers = f"""| Dirigeant (Pappers) | {dirigeant} |
| Effectif (Pappers) | {effectif_p} |
| Capital social | {capital} |
| NAF | {naf} |
| Date création | {date_crea} |"""
    else:
        infos_pappers = "| Données financières | PAPPERS_TOKEN absent — non disponible |"
        bloc_finances = ""

    # --- Bloc catégorie & effectif officiel (data.gouv) ---
    if annee_eff:
        effectif_off_label = f"{effectif_off} ({annee_eff})"
    else:
        effectif_off_label = effectif_off

    infos_gouv = f"""| Catégorie entreprise | {categorie} |
| Effectif officiel (INSEE) | {effectif_off_label} |
| Statut administratif | {statut_adm} |"""

    # --- Bloc dirigeants RNE ---
    if dirigeants_rne:
        dirigeants_md = "\n".join(f"- {d}" for d in dirigeants_rne)
        bloc_dirigeants = f"\n### 👤 Dirigeants (Registre National des Entreprises)\n\n{dirigeants_md}\n"
    else:
        bloc_dirigeants = ""

    # --- Bloc historique BODACC ---
    if historique:
        lignes_hist = [
            "",
            "### 📋 Historique BODACC",
            "",
            "| Date | Procédure / Annonce |",
            "|------|---------------------|",
        ]
        for h in historique:
            lignes_hist.append(f"| {h['date']} | {h['procedure']} |")
        bloc_historique = "\n".join(lignes_hist)
    else:
        bloc_historique = ""

    # --- Contacts ---
    contacts_md = (
        "\n".join(f"- {c}" for c in dossier["contacts"])
        if dossier["contacts"]
        else "_Aucun contact extrait du BODACC_"
    )

    return f"""## {dossier['denomination']}{geo_tag}

| Champ | Valeur |
|-------|--------|
| SIREN | {dossier['siren']} |
| Forme juridique | {dossier['forme_juridique']} |
{infos_pappers}
{infos_gouv}
| Adresse | {dossier['adresse']} |
| Tribunal | {dossier['tribunal']} |
| Procédure | {dossier['procedure']} |
| Secteur détecté | {dossier['secteur'] or 'Non classifié'} |
| Score MASARE | {dossier['score']}/10 |
| Urgence | {dossier['urgence']} |
| Date parution BODACC | {dossier['date_parution']} |
| Dernière mise à jour veille | {date_rapport} |
{bloc_finances}
{bloc_dirigeants}
{bloc_historique}

### 📞 Contacts & Mandataires
{contacts_md}

---
_Généré automatiquement par MASARE-Veille_
"""


def construire_labels(dossier: dict) -> list:
    labels = []
    if dossier["urgence"] == "Haute":
        labels.append("alerte-urgent")
    elif dossier["urgence"] == "Moyenne":
        labels.append("alert-prioritaire")

    proc_lower = (dossier["procedure"] or "").lower()
    if "liquidation" in proc_lower:
        labels.append("liquidation")
    elif "redressement" in proc_lower:
        labels.append("redressement-judiciaire")
    elif "cession" in proc_lower:
        labels.append("plan-de-cession")
    elif "conciliation" in proc_lower or "mandat" in proc_lower:
        labels.append("amont")

    score = dossier["score"]
    if score >= 9:
        labels.append("score-9")
    elif score >= 8:
        labels.append("score-8")

    secteur = (dossier["secteur"] or "").lower()
    if "bitd" in secteur or "défense" in secteur or "aéronaut" in secteur:
        labels.append("BITD")
    if "saas" in secteur or "logiciel" in secteur or "cyber" in secteur:
        labels.append("tech-saas")
    if "immobilier" in secteur or "hôtellerie" in secteur:
        labels.append("immobilier")

    return labels


def upsert_issue_github(dossier: dict, pappers: dict, api_gouv: dict, historique: list, date_rapport: str):
    if not GITHUB_TOKEN:
        return

    siren  = dossier["siren"]
    titre  = construire_titre_issue(dossier)
    corps  = construire_corps_issue(dossier, pappers, api_gouv, historique, date_rapport)
    labels = construire_labels(dossier)

    issues_existantes = charger_issues_ouvertes()

    cle_match = None
    if siren != "N/A" and siren in issues_existantes:
        cle_match = siren
    else:
        cle_nom = normalise_nom_issue(titre)
        if cle_nom in issues_existantes:
            cle_match = cle_nom

    if cle_match:
        issue_number = issues_existantes[cle_match]["number"]
        requests.patch(
            f"{GITHUB_BASE}/issues/{issue_number}",
            headers=GITHUB_HEADERS,
            json={"title": titre, "body": corps, "labels": labels},
        )
        requests.post(
            f"{GITHUB_BASE}/issues/{issue_number}/comments",
            headers=GITHUB_HEADERS,
            json={"body": f"🔄 **Mise à jour MASARE-Veille — {date_rapport}**\n\nNouvelle occurrence BODACC. Score et données mis à jour."},
        )
        print(f"  ↺ Issue #{issue_number} mise à jour — {dossier['denomination']} (SIREN {siren})")
    else:
        resp = requests.post(
            f"{GITHUB_BASE}/issues",
            headers=GITHUB_HEADERS,
            json={"title": titre, "body": corps, "labels": labels},
        )
        if resp.ok:
            num = resp.json().get("number", "?")
            print(f"  ✓ Issue #{num} créée — {dossier['denomination']} (SIREN {siren})")
            nouvelle = resp.json()
            if siren != "N/A":
                issues_existantes[siren] = nouvelle
            cle_nom = normalise_nom_issue(titre)
            if cle_nom:
                issues_existantes[cle_nom] = nouvelle
        else:
            print(f"  ✗ Erreur création issue pour {dossier['denomination']} : {resp.status_code}")


# ---------------------------------------------------------------------------
# POINT D'ENTRÉE
# ---------------------------------------------------------------------------

def main():
    date_rapport = datetime.now().strftime("%Y%m%d")
    print(f"[MASARE-Veille] Démarrage — {date_rapport}")
    if not PAPPERS_TOKEN:
        print("[MASARE-Veille] ⚠️  PAPPERS_TOKEN absent — filtre taille et financials désactivés")

    records = fetch_bodacc()
    print(f"[MASARE-Veille] {len(records)} annonce(s) BODACC récupérée(s)")

    dossiers_retenus = []
    ecarts_score, ecarts_taille = 0, 0

    for record in records:
        score, secteur, procedure, urgence, geo_match = scorer_dossier(record)

        if score < SCORE_MIN:
            ecarts_score += 1
            continue

        siren       = extraire_siren(record)
        denomination = extraire_denomination(record)

        # Enrichissement 1 — Pappers (avec filtre taille + rentabilité)
        pappers = enrichir_depuis_pappers(siren)
        if not pappers.get("ca_filtre_ok", True):
            ecarts_taille += 1
            continue

        # Enrichissement 2 — API Gouv (gratuit, sans clé)
        api_gouv = enrichir_depuis_api_gouv(siren)

        # Enrichissement 3 — Historique BODACC du SIREN
        historique = historique_bodacc(siren)

        dossier = {
            "denomination":   denomination,
            "siren":          siren,
            "forme_juridique": extraire_forme_juridique(record),
            "adresse":        extraire_adresse(record),
            "tribunal":       extraire_tribunal(record),
            "procedure":      procedure,
            "secteur":        secteur,
            "date_parution":  record.get("dateparution", "") or "N/A",
            "contacts":       extraire_contacts(record),
            "score":          score,
            "urgence":        urgence,
            "geo_match":      geo_match,
        }
        dossiers_retenus.append((dossier, pappers, api_gouv, historique))

    dossiers_retenus.sort(key=lambda x: x[0]["score"], reverse=True)
    print(
        f"[MASARE-Veille] {len(dossiers_retenus)} dossier(s) retenu(s) "
        f"— {ecarts_score} écarté(s) score — {ecarts_taille} écarté(s) taille"
    )

    # Rapport Markdown
    rapport = generer_rapport([d for d, *_ in dossiers_retenus], date_rapport)
    nom_fichier = f"rapport_{date_rapport}.md"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"[MASARE-Veille] Rapport généré : {nom_fichier}")

    # Issues GitHub
    if GITHUB_TOKEN:
        print("[MASARE-Veille] Synchronisation GitHub Issues...")
        charger_issues_ouvertes()
        for dossier, pappers, api_gouv, historique in dossiers_retenus:
            upsert_issue_github(dossier, pappers, api_gouv, historique, date_rapport)
        print("[MASARE-Veille] Issues synchronisées")
    else:
        print("[MASARE-Veille] GITHUB_TOKEN absent — issues ignorées")


if __name__ == "__main__":
    main()
