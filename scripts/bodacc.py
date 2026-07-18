"""
MASARE - Veille Distressed BODACC
Script de surveillance automatique des procédures collectives
Critères affinés juillet 2026
"""

import requests
import json
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BODACC_API = "https://bodacc-datadila.opendatasoft.com/api/records/1.0/search/"
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


def extraire_champ(record: dict, *chemins) -> str:
    """Tente d'extraire un champ selon plusieurs chemins possibles."""
    fields = record.get("fields", {})
    for chemin in chemins:
        parties = chemin.split(".")
        valeur = fields
        for partie in parties:
            if isinstance(valeur, dict):
                valeur = valeur.get(partie, "")
            else:
                valeur = ""
                break
        if valeur:
            return str(valeur)
    return ""


def extraire_json_imbrique(record: dict, cle: str) -> dict:
    """Parse le JSON imbriqué dans publicationavis si présent."""
    fields = record.get("fields", {})
    raw = fields.get("publicationavis", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def extraire_denomination(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "denomination", "nomCommercial", "raisonSociale")
        or avis.get("denomination", "")
        or avis.get("nomCommercial", "")
        or "N/A"
    )


def extraire_siren(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "numeroidentifiant", "siren")
        or avis.get("numeroIdentifiant", "")
        or avis.get("siren", "")
        or "N/A"
    )


def extraire_adresse(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    ville = (
        extraire_champ(record, "ville", "commune")
        or avis.get("adresse", {}).get("ville", "")
        or avis.get("ville", "")
        or ""
    )
    dept = (
        extraire_champ(record, "departement", "codePostal")
        or avis.get("adresse", {}).get("codePostal", "")
        or ""
    )
    return f"{ville} ({dept})" if ville and dept else ville or dept or "N/A"


def extraire_tribunal(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "tribunal")
        or avis.get("tribunal", "")
        or "N/A"
    )


def extraire_forme_juridique(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "formejuridique")
        or avis.get("formeJuridique", "")
        or "N/A"
    )


def extraire_activite(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "activite", "codeNaf", "libelleCodeNaf")
        or avis.get("activite", "")
        or avis.get("codeNaf", "")
        or ""
    )


def extraire_contacts(record: dict) -> list:
    """Extrait administrateurs, mandataires, liquidateurs."""
    contacts = []
    avis = extraire_json_imbrique(record, "publicationavis")

    for cle in ["administrateurJudiciaire", "mandataireJudiciaire", "liquidateur", "representantCreanciers"]:
        val = avis.get(cle, "")
        if val:
            contacts.append(f"{cle.replace('J', ' J').replace('C', ' C').strip()} : {val}")

    raw_contacts = extraire_champ(record, "listepersonnes")
    if raw_contacts and not contacts:
        contacts.append(raw_contacts[:200])

    return contacts


def extraire_procedure(record: dict) -> str:
    avis = extraire_json_imbrique(record, "publicationavis")
    return (
        extraire_champ(record, "familleavis_lib", "typeavis_lib", "jugement")
        or avis.get("typeAvis", "")
        or avis.get("jugement", "")
        or ""
    )

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
    """Récupère les annonces de procédures collectives sur les derniers jours."""
    date_debut = (datetime.now() - timedelta(days=nb_jours)).strftime("%Y-%m-%d")

    params = {
        "dataset": "bodacc-a",
        "q": f"familleavis_lib:\"Procédures collectives\" AND dateparution>={date_debut}",
        "rows": 100,
        "sort": "dateparution",
        "order": "desc",
    }

    try:
        response = requests.get(BODACC_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("records", [])
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
            "date_parution": extraire_champ(record, "dateparution") or "N/A",
            "contacts": extraire_contacts(record),
            "score": score,
            "urgence": urgence,
            "geo_match": geo_match,
        }
        dossiers_retenus.append(dossier)

    # Trier par score décroissant
    dossiers_retenus.sort(key=lambda x: x["score"], reverse=True)

    print(f"[MASARE-Veille] {len(dossiers_retenus)} dossier(s) retenu(s) après filtrage")

    rapport = generer_rapport(dossiers_retenus, date_rapport)

    nom_fichier = f"rapport_{date_rapport}.md"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(rapport)

    print(f"[MASARE-Veille] Rapport généré : {nom_fichier}")


if __name__ == "__main__":
    main()
