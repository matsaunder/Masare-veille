"""
MASARE - Veille Distressed BODACC
Script de surveillance automatique des procédures collectives
Critères affinés juillet 2026

Logique issues GitHub : 1 issue max par SIREN (upsert)
- Si une issue ouverte existe pour ce SIREN → mise à jour du titre + commentaire
- Sinon → création d'une nouvelle issue
"""

import os
import requests
import json
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# GITHUB ISSUES — CONFIG
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
GITHUB_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BODACC_API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
SCORE_MIN = 4
JOURS_RECUL = 2

# ---------------------------------------------------------------------------
# SECTEURS CIBLES (priorité 1 = bonus +2, priorité 2 = bonus +1)
# Secteurs exclus = score plafonné à 3 (ne passent jamais le seuil)
# ---------------------------------------------------------------------------

SECTEURS = {
    # PRIORITÉ 1 — Barrières élevées, marges fortes
    "Défense & Aéronautique (BITD)": {
        "mots_cles": ["aéronaut", "défense", "armement", "naval", "spatia", "bitd", "missi", "munition", "drones", "radar"],
        "priorite": 1,
    },
    "Tech / SaaS B2B Vertical": {
        "mots_cles": ["saas", "logiciel métier", "erp", "éditeur de logiciel", "software", "abonnement logiciel",
                       "logiciel", "informatique", "cybersécur", "cloud", "intelligence artificielle", "ia ", "progiciel"],
        "priorite": 1,
    },
    "Chimie de Spécialités": {
        "mots_cles": ["chimie", "spécialités chimiques", "revêtement", "traitement de surface", "peinture industrielle",
                       "coatings", "adhésif", "polymère", "résine", "pigment"],
        "priorite": 1,
    },
    "Industrie Manufacturière à Barrières Élevées": {
        "mots_cles": ["usinage", "mécaniqu", "manufactur", "métallurg", "fonderie", "forge", "estampage",
                       "tôlerie", "soudure", "chaudronnerie", "équipement industriel", "machine-outil",
                       "pharma", "laboratoir", "biotech", "médical", "medtech", "dispositif médical"],
        "priorite": 1,
    },

    # PRIORITÉ 2 — Actifs tangibles, immobilier hors santé
    "Immobilier & Hôtellerie": {
        "mots_cles": ["immobilier", "foncier", "hôtel", "hôtellerie", "résidence étudiante", "coliving",
                       "data center", "logistique urbaine", "entrepôt", "bureaux", "commerce retail",
                       "centre commercial", "résidence gérée"],
        "priorite": 2,
    },
    "Marques & Retail Premium": {
        "mots_cles": ["marque", "luxe", "maroquinerie", "mode", "licenc", "prêt-à-porter", "cosmétique premium",
                       "bijouterie", "horlogerie", "enseigne"],
        "priorite": 2,
    },
    "Énergie & Environnement": {
        "mots_cles": ["énergie", "solaire", "éolien", "recyclage", "déchets", "environnement", "cleantech",
                       "biomasse", "cogénération"],
        "priorite": 2,
    },

    # SECTEURS EXCLUS — score plafonné (ne passent jamais le seuil de 4)
    "BTP & Construction [EXCLU]": {
        "mots_cles": ["construction", "bâtiment", "travaux publics", "maçonnerie", "gros œuvre", "génie civil"],
        "priorite": -99,  # Exclusion explicite
    },
    "Transport & Logistique Généraliste [EXCLU]": {
        "mots_cles": ["transport routier", "fret", "transitaire", "messagerie", "livraison", "camionnage"],
        "priorite": -99,
    },
    "Commerce & Distribution Généraliste [EXCLU]": {
        "mots_cles": ["commerce", "négoce", "grossiste", "distribution alimentaire", "supermarché", "épicerie"],
        "priorite": -99,
    },
    "Restauration Standard [EXCLU]": {
        "mots_cles": ["restaur", "café", "traiteur", "snack", "brasserie", "pizzeria", "fast-food"],
        "priorite": -99,
    },
    "Immobilier Santé [EXCLU]": {
        "mots_cles": ["ehpad", "maison de retraite", "clinique", "ssr", "soins de suite", "résidence médicalisée"],
        "priorite": -99,
    },
    "Services à la Personne [EXCLU]": {
        "mots_cles": ["aide à domicile", "service à la personne", "garde d'enfant", "ménage à domicile"],
        "priorite": -99,
    },
}

# ---------------------------------------------------------------------------
# BASSINS D'EMPLOI PRIORITAIRES (bonus géographique)
# ---------------------------------------------------------------------------

BASSINS_PRIORITAIRES = [
    # Grandes métropoles
    "paris", "île-de-france", "hauts-de-seine", "seine-saint-denis", "val-de-marne",
    "lyon", "bordeaux", "toulouse", "nantes", "lille", "marseille", "grenoble", "strasbourg",
    # Métropoles régionales
    "rennes", "rouen", "montpellier", "nice", "tours", "metz", "nancy",
    "clermont-ferrand", "angers", "le mans", "caen", "amiens", "besançon", "mulhouse", "pau",
    # Agglomérations à fort tissu économique
    "orléans", "reims", "dijon", "valenciennes", "dunkerque", "brest", "limoges",
    "poitiers", "saint-étienne", "toulon", "avignon", "perpignan", "bayonne", "annecy",
    # Départements industriels clés
    "isère", "rhône", "nord", "bas-rhin", "haut-rhin", "moselle", "gironde",
    "haute-garonne", "loire-atlantique", "bouches-du-rhône", "alpes-maritimes",
]

# ---------------------------------------------------------------------------
# SCORING DES PROCÉDURES
# ---------------------------------------------------------------------------

PROCEDURES = {
    "redressement judiciaire": +3,   # Prioritaire — possibilité de plan de cession
    "liquidation judiciaire": +2,    # Plan de cession direct, prix bas
    "plan de cession": +3,           # Signal le plus direct pour reprise sans apport
    "résolution de plan": +2,        # Sortie de plan raté — bonne décote
    "mandat ad hoc": +2,             # En amont — temps disponible
    "conciliation": +1,              # En amont — négociation créanciers
    "sauvegarde": -2,                # À éviter — actionnaires gardent le contrôle
}

# ---------------------------------------------------------------------------
# FONCTIONS UTILITAIRES
# ---------------------------------------------------------------------------

def normalise(texte: str) -> str:
    """Normalise le texte pour la comparaison (minuscules, sans accents inutiles)."""
    if not texte:
        return ""
    return texte.lower()


def parse_json_field(record: dict, cle: str) -> dict:
    """Parse un champ JSON imbriqué (jugement, listepersonnes, etc.)"""
    raw = record.get(cle, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def extraire_personne(record: dict) -> dict:
    """Extrait les données de la personne/société depuis listepersonnes."""
    lp = parse_json_field(record, "listepersonnes")
    personne = lp.get("personne", lp.get("personnes", None))
    if isinstance(personne, list):
        personne = personne[0] if personne else {}
    return personne if isinstance(personne, dict) else {}


def extraire_denomination(record: dict) -> str:
    # Champ direct 'commercant' dans le nouveau dataset
    nom = record.get("commercant", "")
    if nom:
        return nom
    # Fallback : depuis listepersonnes
    p = extraire_personne(record)
    return (
        p.get("denomination", "")
        or p.get("nomCommercial", "")
        or f"{p.get('nom', '')} {p.get('prenom', '')}".strip()
        or "N/A"
    )


def extraire_siren(record: dict) -> str:
    # Champ 'registre' : liste ["843905241", "843 905 241"]
    registre = record.get("registre", [])
    if registre:
        siren = str(registre[0]).replace(" ", "").strip()
        if len(siren) >= 9:
            return siren[:9]
    # Fallback : depuis listepersonnes
    p = extraire_personne(record)
    num = p.get("numeroImmatriculation", {})
    if isinstance(num, dict):
        return num.get("numeroIdentification", "").replace(" ", "") or "N/A"
    return "N/A"


def extraire_adresse(record: dict) -> str:
    ville = record.get("ville", "")
    cp = record.get("cp", "")
    dept = record.get("departement_nom_officiel", "")
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
    """Extrait administrateurs, mandataires, liquidateurs depuis listepersonnes."""
    contacts = []
    lp = parse_json_field(record, "listepersonnes")
    for cle in ["administrateurJudiciaire", "mandataireJudiciaire", "liquidateur",
                 "representantCreanciers", "mandataireLiquidateur"]:
        val = lp.get(cle, "")
        if val:
            label = cle.replace("Judiciaire", " Judiciaire").replace("Liquidateur", " Liquidateur")
            contacts.append(f"{label} : {val}")
    return contacts


def extraire_procedure(record: dict) -> str:
    """Extrait la nature de la procédure depuis le champ jugement (JSON)."""
    jugement = parse_json_field(record, "jugement")
    if jugement:
        return (
            jugement.get("nature", "")
            or jugement.get("famille", "")
            or jugement.get("type", "")
            or ""
        )
    return record.get("typeavis_lib", "") or record.get("familleavis_lib", "") or ""

# ---------------------------------------------------------------------------
# DÉTECTION SECTEUR ET SCORING
# ---------------------------------------------------------------------------

def detecter_secteur(texte_complet: str):
    """Retourne (nom_secteur, priorite) du secteur détecté, ou (None, 0)."""
    texte = normalise(texte_complet)

    # Vérifier d'abord les secteurs exclus
    for nom, config in SECTEURS.items():
        if config["priorite"] == -99:
            for mot in config["mots_cles"]:
                if mot in texte:
                    return nom, -99

    # Puis les secteurs prioritaires (ordre priorité 1 avant 2)
    for priorite_cible in [1, 2]:
        for nom, config in SECTEURS.items():
            if config["priorite"] == priorite_cible:
                for mot in config["mots_cles"]:
                    if mot in texte:
                        return nom, priorite_cible

    return None, 0


def scorer_dossier(record: dict) -> tuple:
    """
    Calcule le score de pertinence (0-10) d'un dossier.
    Retourne (score, secteur_detecte, procedure_detectee, urgence, geo_match)
    """
    denomination = extraire_denomination(record)
    activite = extraire_activite(record)
    adresse = extraire_adresse(record)
    procedure_raw = extraire_procedure(record)
    tribunal = extraire_tribunal(record)

    texte_complet = f"{denomination} {activite} {procedure_raw} {tribunal}"

    # --- Détection secteur ---
    secteur_detecte, priorite = detecter_secteur(texte_complet)

    # Secteur exclu → score plafonné à 3 (jamais retenu)
    if priorite == -99:
        return 3, secteur_detecte, procedure_raw, "Basse", False

    # --- Score de base ---
    score = 5

    # --- Bonus secteur ---
    if priorite == 1:
        score += 2
    elif priorite == 2:
        score += 1

    # --- Bonus/Malus procédure ---
    proc_lower = normalise(procedure_raw)
    proc_bonus = 0
    for proc, bonus in PROCEDURES.items():
        if proc in proc_lower:
            proc_bonus = bonus
            break
    score += proc_bonus

    # Bonus BITD spécifique
    if any(mot in normalise(texte_complet) for mot in ["bitd", "armement", "défense", "aéronaut", "naval", "dga"]):
        score += 2

    # --- Bonus géographique ---
    texte_geo = normalise(f"{adresse} {tribunal}")
    geo_match = any(bassin in texte_geo for bassin in BASSINS_PRIORITAIRES)
    if geo_match:
        score += 1

    # --- Urgence ---
    if "liquidation" in proc_lower or "cession" in proc_lower:
        urgence = "Haute"
    elif "redressement" in proc_lower or "résolution" in proc_lower:
        urgence = "Moyenne"
    elif "sauvegarde" in proc_lower:
        urgence = "Basse"
    else:
        urgence = "Moyenne"

    # Plafonner le score à 10
    score = min(score, 10)

    return score, secteur_detecte, procedure_raw, urgence, geo_match


# ---------------------------------------------------------------------------
# RÉCUPÉRATION BODACC
# ---------------------------------------------------------------------------

def fetch_bodacc(nb_jours: int = JOURS_RECUL) -> list:
    """Récupère les annonces de procédures collectives (API OpenDataSoft v2.1)."""
    date_debut = (datetime.now() - timedelta(days=nb_jours)).strftime("%Y-%m-%d")

    params = {
        "where": f'familleavis_lib:"Procédures collectives" and dateparution>="{date_debut}"',
        "limit": 100,
        "order_by": "dateparution desc",
    }

    try:
        response = requests.get(BODACC_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de récupérer les données BODACC : {e}")
        return []


# ---------------------------------------------------------------------------
# GÉNÉRATION DU RAPPORT
# ---------------------------------------------------------------------------

def generer_rapport(dossiers_retenus: list, date_rapport: str) -> str:
    """Génère le rapport Markdown à partir des dossiers retenus."""
    lignes = []
    lignes.append(f"# Rapport Veille Distressed MASARE — {date_rapport}")
    lignes.append("")
    lignes.append(f"**{len(dossiers_retenus)} dossier(s) retenu(s)** (score ≥ {SCORE_MIN}, hors secteurs exclus)")
    lignes.append("")
    lignes.append("---")
    lignes.append("")

    if not dossiers_retenus:
        lignes.append("*Aucun dossier retenu aujourd'hui.*")
        return "\n".join(lignes)

    # Grouper par urgence
    groupes = {"Haute": [], "Moyenne": [], "Basse": []}
    for d in dossiers_retenus:
        groupes[d["urgence"]].append(d)

    for niveau in ["Haute", "Moyenne", "Basse"]:
        if not groupes[niveau]:
            continue
        lignes.append(f"## 🔴 Urgence {niveau}" if niveau == "Haute" else
                       f"## 🟠 Urgence {niveau}" if niveau == "Moyenne" else
                       f"## 🟡 Urgence {niveau}")
        lignes.append("")

        for d in groupes[niveau]:
            geo_tag = " 📍" if d["geo_match"] else ""
            lignes.append(f"### {d['denomination']}{geo_tag} — Score {d['score']}/10")
            lignes.append("")
            lignes.append(f"| Champ | Valeur |")
            lignes.append(f"|-------|--------|")
            lignes.append(f"| SIREN | {d['siren']} |")
            lignes.append(f"| Forme juridique | {d['forme_juridique']} |")
            lignes.append(f"| Adresse | {d['adresse']} |")
            lignes.append(f"| Tribunal | {d['tribunal']} |")
            lignes.append(f"| Procédure | {d['procedure']} |")
            lignes.append(f"| Secteur détecté | {d['secteur'] or 'Non classifié'} |")
            lignes.append(f"| Date parution | {d['date_parution']} |")
            lignes.append("")

            if d["contacts"]:
                lignes.append("**Contacts :**")
                for contact in d["contacts"]:
                    lignes.append(f"- {contact}")
                lignes.append("")

            lignes.append("---")
            lignes.append("")

    lignes.append(f"*Rapport généré automatiquement par MASARE-Veille — {datetime.now().strftime('%d/%m/%Y %H:%M')}*")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# GITHUB ISSUES — LOGIQUE UPSERT (1 issue par SIREN max)
# ---------------------------------------------------------------------------

_issues_cache = None  # Cache des issues ouvertes pour éviter les appels répétés

def normalise_nom_issue(titre: str) -> str:
    """Extrait et normalise le nom de société depuis un titre d'issue GitHub."""
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
    """
    Charge toutes les issues ouvertes et les indexe par :
    - SIREN (extrait du corps) — clé primaire
    - Nom normalisé (extrait du titre) — clé de fallback
    Retourne un dict {cle: issue_dict}
    """
    global _issues_cache
    if _issues_cache is not None:
        return _issues_cache

    if not GITHUB_TOKEN:
        _issues_cache = {}
        return _issues_cache

    index = {}
    page = 1
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
            # Index 1 : par SIREN (clé primaire)
            body = issue.get("body", "") or ""
            match_siren = re.search(r"SIREN[^\|]*\|\s*([0-9]{9})", body)
            if match_siren:
                index[match_siren.group(1).strip()] = issue
            # Index 2 : par nom normalisé (fallback pour anciennes issues sans SIREN)
            cle_nom = normalise_nom_issue(issue["title"])
            if cle_nom and cle_nom not in index:
                index[cle_nom] = issue
        page += 1

    _issues_cache = index
    return index


def construire_titre_issue(dossier: dict) -> str:
    urgence_tag = "URGENT" if dossier["urgence"] == "Haute" else "STANDARD"
    secteur_court = (dossier["secteur"] or "Non classifié").split("(")[0].strip()
    # Tronquer secteur si trop long
    if len(secteur_court) > 40:
        secteur_court = secteur_court[:37] + "..."
    return (
        f"ALERTE {urgence_tag} — {dossier['denomination']} — "
        f"Score {dossier['score']}/10 — {secteur_court} — {dossier['urgence']} urgence"
    )


def construire_corps_issue(dossier: dict, date_rapport: str) -> str:
    geo_tag = " 📍 Bassin prioritaire" if dossier["geo_match"] else ""
    contacts_md = "\n".join(f"- {c}" for c in dossier["contacts"]) if dossier["contacts"] else "_Aucun contact extrait_"
    return f"""## {dossier['denomination']}{geo_tag}

| Champ | Valeur |
|-------|--------|
| SIREN | {dossier['siren']} |
| Forme juridique | {dossier['forme_juridique']} |
| Adresse | {dossier['adresse']} |
| Tribunal | {dossier['tribunal']} |
| Procédure | {dossier['procedure']} |
| Secteur détecté | {dossier['secteur'] or 'Non classifié'} |
| Score MASARE | {dossier['score']}/10 |
| Urgence | {dossier['urgence']} |
| Date parution BODACC | {dossier['date_parution']} |
| Dernière mise à jour veille | {date_rapport} |

### Contacts
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


def upsert_issue_github(dossier: dict, date_rapport: str):
    """
    Crée ou met à jour une issue GitHub pour ce dossier.
    Règle : 1 issue max par SIREN.
    """
    if not GITHUB_TOKEN:
        return

    siren = dossier["siren"]
    titre = construire_titre_issue(dossier)
    corps = construire_corps_issue(dossier, date_rapport)
    labels = construire_labels(dossier)

    issues_existantes = charger_issues_ouvertes()

    # Recherche : SIREN en priorité, puis nom normalisé
    cle_match = None
    if siren != "N/A" and siren in issues_existantes:
        cle_match = siren
    else:
        cle_nom = normalise_nom_issue(titre)
        if cle_nom in issues_existantes:
            cle_match = cle_nom

    if cle_match:
        # ── UPDATE : mise à jour du titre, du corps et des labels
        issue = issues_existantes[cle_match]
        issue_number = issue["number"]

        requests.patch(
            f"{GITHUB_BASE}/issues/{issue_number}",
            headers=GITHUB_HEADERS,
            json={"title": titre, "body": corps, "labels": labels},
        )
        # Commentaire de mise à jour
        requests.post(
            f"{GITHUB_BASE}/issues/{issue_number}/comments",
            headers=GITHUB_HEADERS,
            json={"body": f"🔄 **Mise à jour automatique MASARE-Veille — {date_rapport}**\n\nNouvelle occurrence BODACC détectée. Score et informations mis à jour."},
        )
        print(f"  ↺ Issue #{issue_number} mise à jour — {dossier['denomination']} (SIREN {siren})")

    else:
        # ── CREATE : nouvelle issue
        resp = requests.post(
            f"{GITHUB_BASE}/issues",
            headers=GITHUB_HEADERS,
            json={"title": titre, "body": corps, "labels": labels},
        )
        if resp.ok:
            num = resp.json().get("number", "?")
            print(f"  ✓ Issue #{num} créée — {dossier['denomination']} (SIREN {siren})")
            # Mettre à jour le cache (SIREN + nom normalisé)
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

    records = fetch_bodacc()
    print(f"[MASARE-Veille] {len(records)} annonce(s) récupérée(s)")

    dossiers_retenus = []

    for record in records:
        score, secteur, procedure, urgence, geo_match = scorer_dossier(record)

        if score < SCORE_MIN:
            continue

        dossier = {
            "denomination": extraire_denomination(record),
            "siren": extraire_siren(record),
            "forme_juridique": extraire_forme_juridique(record),
            "adresse": extraire_adresse(record),
            "tribunal": extraire_tribunal(record),
            "procedure": procedure,
            "secteur": secteur,
            "date_parution": record.get("dateparution", "") or "N/A",
            "contacts": extraire_contacts(record),
            "score": score,
            "urgence": urgence,
            "geo_match": geo_match,
        }
        dossiers_retenus.append(dossier)

    # Trier par score décroissant
    dossiers_retenus.sort(key=lambda x: x["score"], reverse=True)

    print(f"[MASARE-Veille] {len(dossiers_retenus)} dossier(s) retenu(s) après filtrage")

    # Générer le rapport Markdown
    rapport = generer_rapport(dossiers_retenus, date_rapport)
    nom_fichier = f"rapport_{date_rapport}.md"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"[MASARE-Veille] Rapport généré : {nom_fichier}")

    # Créer / mettre à jour les issues GitHub (1 par SIREN)
    if GITHUB_TOKEN:
        print(f"[MASARE-Veille] Synchronisation GitHub Issues...")
        charger_issues_ouvertes()  # Pré-charger le cache
        for dossier in dossiers_retenus:
            upsert_issue_github(dossier, date_rapport)
        print(f"[MASARE-Veille] Issues synchronisées")
    else:
        print(f"[MASARE-Veille] GITHUB_TOKEN absent — issues ignorées")


if __name__ == "__main__":
    main()
