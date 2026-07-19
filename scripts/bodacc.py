"""
MASARE - Veille Distressed BODACC
Script de surveillance automatique des procédures collectives
Critères affinés 19 juillet 2026

Sources d'enrichissement :
1. BODACC (annonces-commerciales) — procédure du jour
2. Recherche Entreprises (data.gouv.fr) — catégorie PME/ETI/GE, effectif INSEE, dirigeants RNE, statut
3. Historique BODACC du SIREN — procédures passées (contexte investissement)
4. Pappers API (optionnel, PAPPERS_TOKEN) — CA, résultat net, EBITDA sur 3 exercices
5. Claude API (optionnel, ANTHROPIC_API_KEY) — analyse IA : situation, angle MASARE, actifs, red flags

Filtre taille via catégorie entreprise (INSEE) :
  - GE  (Grande Entreprise)             → CA > 1,5 Md€            → +4 pts (D5)
  - ETI (Entreprise de Taille Interm.)  → CA 50 M€ – 1,5 Md€     → +2 pts (D5)
  - PME (Petite et Moyenne Entreprise)  → CA < 50 M€              → 0 pt   (à vérifier)
  - N/D                                 → indéterminé             → 0 pt

Scoring /20 :
  D1 Secteur          : Priorité 1 → +6 | Priorité 2 → +4 | Exclu/Non classifié → disqualifiant
  D3 Procédure        : Plan cession/Résolution → +4 | RJ/Mandat/Conciliation → +2 | LJ → +1 | Sauvegarde → 0
  D4 Actifs tangibles : secteur avec actifs physiques identifiables → +2
  D5 Taille           : GE → +4 | ETI → +2 | PME/N/D → 0
  D6 Souveraineté     : défense/cyber/BITD/stratégique → +2
  Géo                 : bassin prioritaire → +2
  ── BONUS (après seuil PRE_AI=12) ──
  D2 Rentabilité hist.: résultat net > 0 sur 2-3 ans → +4 | sur 1 an → +2 (source Pappers)
  D7 Marque/Leader    : marque iconique → +4 | leader de niche → +2 (détection IA)
  Score plafonné à 20. Seuil de publication : SCORE_MIN = 16.
"""

import os
import requests
import json
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
PAPPERS_TOKEN   = os.environ.get("PAPPERS_TOKEN", "")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
GITHUB_BASE  = f"https://api.github.com/repos/{GITHUB_REPO}"
BODACC_API   = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
API_GOUV_URL = "https://recherche-entreprises.api.gouv.fr/search"
PAPPERS_URL  = "https://api.pappers.fr/v2/entreprise"

SCORE_MIN        = 12   # Seuil de publication des issues GitHub
PRE_AI_THRESHOLD = 10   # Seuil minimum pour appeler l'IA (D7 bonus marque/leader)
JOURS_RECUL      = int(os.environ.get("JOURS_RECUL", "2"))

# ---------------------------------------------------------------------------
# SECTEURS CIBLES
# ---------------------------------------------------------------------------

SECTEURS = {
    "Défense & Aéronautique (BITD)": {
        "mots_cles": ["aéronaut", "défense", "armement", "naval", "spatia", "bitd",
                      "missi", "munition", "drone", "radar"],
        "priorite": 1,
        "actifs_physiques": True,
        "souverainete": True,
    },
    "Tech / SaaS B2B Vertical": {
        "mots_cles": ["saas", "logiciel métier", "erp", "éditeur de logiciel", "software",
                      "logiciel", "informatique", "cybersécur", "cloud",
                      "intelligence artificielle", "ia ", "progiciel"],
        "priorite": 1,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Chimie de Spécialités": {
        "mots_cles": ["chimie", "spécialités chimiques", "revêtement", "traitement de surface",
                      "peinture industrielle", "coatings", "adhésif", "polymère", "résine", "pigment"],
        "priorite": 1,
        "actifs_physiques": True,
        "souverainete": False,
    },
    "Industrie Manufacturière à Barrières Élevées": {
        "mots_cles": ["usinage", "mécaniqu", "manufactur", "métallurg", "fonderie", "forge",
                      "estampage", "tôlerie", "soudure", "chaudronnerie", "équipement industriel",
                      "machine-outil", "pharma", "laboratoir", "biotech", "médical", "medtech",
                      "dispositif médical"],
        "priorite": 1,
        "actifs_physiques": True,
        "souverainete": False,
    },
    "Immobilier & Hôtellerie": {
        "mots_cles": ["immobilier", "foncier", "hôtel", "hôtellerie", "résidence étudiante",
                      "coliving", "data center", "logistique urbaine", "entrepôt", "bureaux",
                      "commerce retail", "centre commercial", "résidence gérée",
                      "promotion immobilière", "résidentiel", "logement", "lotissement",
                      "copropriété", "aménagement foncier", "construction de maisons",
                      "plateforme logistique", "hub logistique"],
        "priorite": 2,
        "actifs_physiques": True,
        "souverainete": False,
    },
    "Logistique & Entrepôts Immobiliers": {
        # Transport/fret avec actifs physiques significatifs (entrepôts, plateformes)
        # Conditions : présence de mots transport/fret ET mots immobilier/entrepôt
        # Détection fine dans scorer_dossier via logique combinée
        "mots_cles": ["plateforme logistique", "entrepôt logistique", "hub logistique",
                      "messagerie express", "logistique immobilière", "parc logistique",
                      "logistique du froid", "logistique pharmaceutique"],
        "priorite": 2,
        "actifs_physiques": True,
        "souverainete": False,
    },
    "Marques & Retail Premium": {
        "mots_cles": ["marque", "luxe", "maroquinerie", "mode", "licenc", "prêt-à-porter",
                      "cosmétique premium", "bijouterie", "horlogerie", "enseigne"],
        "priorite": 2,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Énergie & Environnement": {
        "mots_cles": ["énergie", "solaire", "éolien", "recyclage", "déchets", "environnement",
                      "cleantech", "biomasse", "cogénération"],
        "priorite": 2,
        "actifs_physiques": True,
        "souverainete": False,
    },
    # EXCLUS
    "BTP & Construction [EXCLU]": {
        "mots_cles": ["construction", "bâtiment", "travaux publics", "maçonnerie",
                      "gros œuvre", "génie civil"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Transport Généraliste [EXCLU]": {
        # Exclu seulement si PAS d'actifs immobiliers/entrepôts identifiables
        # Le transport avec entrepôts est traité par "Logistique & Entrepôts Immobiliers"
        "mots_cles": ["taxi", "vtc", "ambulance", "camionnage", "transport de personnes",
                      "autocar", "autobus", "transport scolaire"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Commerce & Distribution Généraliste [EXCLU]": {
        "mots_cles": ["commerce", "négoce", "grossiste", "distribution alimentaire",
                      "supermarché", "épicerie"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Restauration Standard [EXCLU]": {
        "mots_cles": ["restaur", "café", "traiteur", "snack", "brasserie",
                      "pizzeria", "fast-food"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Immobilier Santé [EXCLU]": {
        "mots_cles": ["ehpad", "maison de retraite", "clinique", "ssr",
                      "soins de suite", "résidence médicalisée"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
    },
    "Services à la Personne [EXCLU]": {
        "mots_cles": ["aide à domicile", "service à la personne",
                      "garde d'enfant", "ménage à domicile"],
        "priorite": -99,
        "actifs_physiques": False,
        "souverainete": False,
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

# D3 — Procédure : points attribués
PROCEDURES = {
    "plan de cession":         4,  # Idéal MASARE : pas d'equity, reprise actifs
    "résolution de plan":      4,  # Idem
    "redressement judiciaire": 2,  # Potentiel plan cession
    "mandat ad hoc":           2,  # Amont, négociation passif possible
    "conciliation":            2,  # Amont, structuration possible
    "liquidation judiciaire":  1,  # Actifs liquidés — possible mais plus dur
    "sauvegarde":              0,  # Surveillance long terme seulement
}

TRANCHE_EFFECTIF = {
    "NN": "Non employeuse", "00": "0 salarié", "01": "1–2 sal.", "02": "3–5 sal.",
    "03": "6–9 sal.", "11": "10–19 sal.", "12": "20–49 sal.", "21": "50–99 sal.",
    "22": "100–199 sal.", "31": "200–249 sal.", "32": "250–499 sal.",
    "41": "500–999 sal.", "42": "1 000–1 999 sal.", "51": "2 000–4 999 sal.",
    "52": "5 000–9 999 sal.", "53": "10 000 sal. et plus",
}

# ---------------------------------------------------------------------------
# UTILITAIRES BODACC
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


def format_montant(val) -> str:
    """Formate un montant en euros vers M€ avec signe."""
    if val is None:
        return "N/D"
    try:
        m = float(val) / 1_000_000
        if m < 0:
            return f"-{abs(m):.1f} M€"
        return f"{m:.1f} M€"
    except (ValueError, TypeError):
        return str(val)


# ---------------------------------------------------------------------------
# SOURCE 1 — API RECHERCHE ENTREPRISES (data.gouv.fr) — gratuit, sans clé
# ---------------------------------------------------------------------------

def enrichir_depuis_api_gouv(siren: str) -> dict:
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

        tranche_code   = e.get("tranche_effectif_salarie", "")
        effectif_label = TRANCHE_EFFECTIF.get(tranche_code, tranche_code or "N/D")
        categorie      = e.get("categorie_entreprise", "N/D")
        statut         = "Active" if e.get("etat_administratif") == "A" else "Cessée/Inconnue"
        annee_eff      = str(e.get("annee_effectif_salarie", ""))
        naf_code       = e.get("activite_principale", "")
        date_creation  = e.get("date_creation", "N/D")

        dirigeants_rne = []
        for d in e.get("dirigeants", [])[:3]:
            nom     = d.get("nom", d.get("denomination", ""))
            prenom  = d.get("prenom", "")
            qualite = d.get("qualite", "")
            libelle = f"{prenom} {nom}".strip()
            if qualite:
                libelle += f" — {qualite}"
            if libelle:
                dirigeants_rne.append(libelle)

        # D5 — Taille
        taille_score = {"GE": 4, "ETI": 2}.get(categorie, 0)
        taille_ok    = categorie in ("ETI", "GE") or categorie == "N/D"

        return {
            "categorie":         categorie,
            "taille_ok":         taille_ok,
            "taille_score":      taille_score,
            "effectif_officiel": effectif_label,
            "annee_effectif":    annee_eff,
            "statut":            statut,
            "naf_code":          naf_code,
            "date_creation":     date_creation,
            "dirigeants_rne":    dirigeants_rne,
        }
    except Exception as ex:
        print(f"  [API Gouv] Exception pour SIREN {siren} : {ex}")
        return {}


# ---------------------------------------------------------------------------
# SOURCE 2 — HISTORIQUE BODACC DU SIREN — gratuit
# ---------------------------------------------------------------------------

def historique_bodacc(siren: str) -> list:
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
            proc   = extraire_procedure(r)
            label  = proc or r.get("typeavis_lib", "") or r.get("familleavis_lib", "") or "Annonce"
            historique.append({"date": date_p, "procedure": label})
        return historique
    except Exception as ex:
        print(f"  [Historique BODACC] Exception pour SIREN {siren} : {ex}")
        return []


# ---------------------------------------------------------------------------
# SOURCE 3 — PAPPERS API (optionnel — activé si PAPPERS_TOKEN défini)
# ---------------------------------------------------------------------------

def enrichir_depuis_pappers(siren: str) -> dict:
    """
    Retourne les données financières Pappers (CA, résultat, EBITDA sur 3 ans).
    Désactivé silencieusement si PAPPERS_TOKEN absent ou invalide.
    """
    if not PAPPERS_TOKEN or siren == "N/A":
        return {}
    try:
        resp = requests.get(
            PAPPERS_URL,
            params={
                "api_token":       PAPPERS_TOKEN,
                "siren":           siren,
                "finances":        "true",
                "representants":   "false",
                "publications":    "false",
                "beneficiaires":   "false",
                "extrait_kbis":    "false",
            },
            timeout=10,
        )
        if resp.status_code == 401:
            print("  [Pappers] Token invalide ou crédits insuffisants — enrichissement financier ignoré")
            return {}
        if not resp.ok:
            print(f"  [Pappers] Erreur {resp.status_code} pour SIREN {siren}")
            return {}

        data     = resp.json()
        finances = data.get("finances", [])
        if not finances:
            return {}

        exercices = []
        for f in finances[:3]:
            annee    = f.get("annee", "")
            ca       = f.get("chiffre_affaires")
            resultat = f.get("resultat")
            ebitda   = f.get("excedent_brut_exploitation")
            exercices.append({
                "annee":    annee,
                "ca":       ca,
                "resultat": resultat,
                "ebitda":   ebitda,
            })

        dernier = exercices[0] if exercices else {}
        return {
            "ca_dernier":       dernier.get("ca"),
            "resultat_dernier": dernier.get("resultat"),
            "ebitda_dernier":   dernier.get("ebitda"),
            "annee_dernier":    dernier.get("annee"),
            "exercices":        exercices,
        }
    except Exception as ex:
        print(f"  [Pappers] Exception pour SIREN {siren} : {ex}")
        return {}


def calculer_bonus_pappers(pappers: dict) -> int:
    """
    D2 — Rentabilité historique (bonus, source Pappers).
    net > 0 sur 2-3 exercices → +4 | sur 1 exercice → +2 | sinon → 0
    """
    if not pappers:
        return 0
    exercices = pappers.get("exercices", [])
    if not exercices:
        return 0
    positifs = 0
    for ex in exercices:
        try:
            if ex.get("resultat") is not None and float(ex["resultat"]) > 0:
                positifs += 1
        except (ValueError, TypeError):
            pass
    if positifs >= 2:
        return 4
    elif positifs == 1:
        return 2
    return 0


# ---------------------------------------------------------------------------
# SOURCE 4 — CLAUDE API (optionnel — activé si ANTHROPIC_API_KEY défini)
# ---------------------------------------------------------------------------

def enrichir_avec_ia(dossier: dict, api_gouv: dict, pappers: dict, historique: list) -> tuple:
    """
    Génère une analyse investissement (situation, angle MASARE, actifs, red flags)
    via Groq (gratuit, 500 req/jour, llama-3.3-70b). Retourne (analyse_str, marque_score).
    marque_score : 4 si marque iconique, 2 si leader de niche, 0 sinon.
    Désactivé silencieusement si GROQ_API_KEY absent → ("", 0).
    """
    if not GROQ_API_KEY:
        return "", 0
    try:
        from groq import Groq

        client_groq = Groq(api_key=GROQ_API_KEY)

        ca_str       = format_montant(pappers.get("ca_dernier")) if pappers else "N/D"
        resultat_str = format_montant(pappers.get("resultat_dernier")) if pappers else "N/D"
        ebitda_str   = format_montant(pappers.get("ebitda_dernier")) if pappers else "N/D"
        annee_fin    = pappers.get("annee_dernier", "") if pappers else ""

        hist_str = ""
        if historique:
            hist_str = "\n".join(
                f"  - {h['date']} : {h['procedure']}" for h in historique[:5]
            )

        dirigeants_str = ", ".join(api_gouv.get("dirigeants_rne", [])) or "N/D"
        effectif_str   = api_gouv.get("effectif_officiel", "N/D")
        categorie_str  = api_gouv.get("categorie", "N/D")

        prompt = f"""Tu es un analyste senior chez MASARE, fonds de private equity distressed (Paris, 58 rue de Monceau).
Stratégie MASARE : retournement sans apport de fonds propres, travail du passif, actifs tangibles prioritaires. Ticket minimum 10M€.
Modes d'entrée : plan de cession à la barre / reprise de titres avec négociation passif / debt-to-equity.
Secteurs cibles : industrie avec actifs lourds, cybersécurité/défense (BITD), immobilier tertiaire/hôtellerie, marques en difficulté.

Analyse ce dossier BODACC et rédige une fiche d'investissement courte en 4 sections.

DONNÉES DISPONIBLES :
- Société : {dossier['denomination']}
- SIREN : {dossier['siren']}
- Forme juridique : {dossier['forme_juridique']}
- Secteur détecté : {dossier['secteur']}
- Procédure : {dossier['procedure']}
- Adresse : {dossier['adresse']} | Tribunal : {dossier['tribunal']}
- Catégorie (INSEE) : {categorie_str} | Effectif : {effectif_str}
- Dirigeants : {dirigeants_str}
- CA ({annee_fin}) : {ca_str} | Résultat net : {resultat_str} | EBITDA : {ebitda_str}
- Historique procédures BODACC :
{hist_str or '  Aucun historique disponible'}

INSTRUCTIONS :
- Ton direct, pas de blabla, pas de conditionnel inutile
- Si les données financières sont N/D, raisonne à partir du secteur et de la catégorie
- Maximum 5 lignes par section

### 🔍 Situation
[Ce qui se passe : nature de la détresse, ancienneté probable, contexte sectoriel. Confirme ou nuance si c'est intéressant.]

### 🎯 Angle MASARE
[Mode d'entrée recommandé parmi les 3 stratégies MASARE. Pourquoi ce dossier correspond ou non à la stratégie. Mention du ticket estimé si possible.]

### 💰 Actifs tangibles probables
[Selon secteur et taille : machines, brevets, marques, immobilier, contrats LT, base clients B2B, licences, etc. Sois concret.]

### ⚠️ Points de vigilance
[2-3 red flags ou éléments à vérifier avant de creuser davantage.]

---
À la toute fin, sur une ligne seule, indique le score marque/leader :
MARQUE_SCORE: X
(X = 4 si marque iconique nationale ou internationale en difficulté — ex : Duralex, Brandt, Lafuma ; X = 2 si leader reconnu d'une niche sectorielle ; X = 0 sinon)"""

        response   = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        texte_brut = response.choices[0].message.content.strip()

        # Extraire MARQUE_SCORE
        marque_score = 0
        m = re.search(r"MARQUE_SCORE:\s*([024])", texte_brut)
        if m:
            marque_score = int(m.group(1))
        # Retirer la ligne MARQUE_SCORE du texte affiché
        analyse_propre = re.sub(r"\n?MARQUE_SCORE:\s*[0-9]+\s*$", "", texte_brut).strip()

        return analyse_propre, marque_score

    except ImportError:
        print("  [Groq] Package groq non installé — analyse IA ignorée")
        return "", 0
    except Exception as ex:
        print(f"  [Groq] Exception : {ex}")
        return "", 0


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

MOTS_TRANSPORT_FRET = [
    "transport routier", "fret", "transitaire", "messagerie", "livraison",
    "camionnage", "affrètement", "groupage", "express"
]
MOTS_ENTREPOT = [
    "entrepôt", "plateforme logistique", "hub logistique", "parc logistique",
    "logistique du froid", "logistique pharmaceutique", "messagerie express",
    "logistique immobilière"
]


def detecter_secteur(texte_complet: str):
    """
    Détection du secteur. Les correspondances positives (priorité 1 & 2)
    l'emportent sur les exclusions, sauf si aucune correspondance positive.

    Cas spécial transport/fret : exclu si pur (pas d'entrepôts), reclassé
    en 'Logistique & Entrepôts Immobiliers' (priorité 2) si actifs physiques.
    """
    texte = normalise(texte_complet)

    # Cas spécial : transport/fret + entrepôt → reclassé immobilier logistique
    has_transport = any(m in texte for m in MOTS_TRANSPORT_FRET)
    has_entrepot  = any(m in texte for m in MOTS_ENTREPOT)
    if has_transport and has_entrepot:
        return "Logistique & Entrepôts Immobiliers", 2

    # Priorité 1 puis 2 — avant les exclusions
    for priorite_cible in [1, 2]:
        for nom, config in SECTEURS.items():
            if config["priorite"] == priorite_cible:
                for mot in config["mots_cles"]:
                    if mot in texte:
                        return nom, priorite_cible

    # Exclusions (seulement si aucune correspondance positive)
    for nom, config in SECTEURS.items():
        if config["priorite"] == -99:
            for mot in config["mots_cles"]:
                if mot in texte:
                    return nom, -99

    # Transport/fret pur sans entrepôt → exclu
    if has_transport and not has_entrepot:
        return "Transport & Fret Généraliste [EXCLU]", -99

    return None, 0


def scorer_dossier(record: dict) -> tuple:
    """
    Calcule le score de base (sans D5 taille, D2 Pappers, D7 IA).
    Retourne (score_base, secteur, procedure, urgence, geo_match).
    score_base = D1 + D3 + D4 + D6 + Géo (max théorique ≈ 14)
    Retourne score_base=0 si dossier disqualifié (exclu ou non classifié).
    """
    if est_personne_physique(record):
        return 0, None, "", "Basse", False

    denomination  = extraire_denomination(record)
    activite      = extraire_activite(record)
    adresse       = extraire_adresse(record)
    procedure_raw = extraire_procedure(record)
    tribunal      = extraire_tribunal(record)

    texte_complet = f"{denomination} {activite} {procedure_raw} {tribunal}"
    secteur_detecte, priorite = detecter_secteur(texte_complet)

    # D1 — disqualifiant si exclu ou non classifié
    if priorite == -99 or priorite == 0:
        return 0, secteur_detecte if priorite == -99 else None, procedure_raw, "Basse", False

    score = 0

    # D1 — Secteur
    if priorite == 1:
        score += 6
    elif priorite == 2:
        score += 4

    # D3 — Procédure
    proc_lower = normalise(procedure_raw)
    for proc, points in PROCEDURES.items():
        if proc in proc_lower:
            score += points
            break

    # D4 — Actifs tangibles physiques identifiables (selon configuration secteur)
    config_secteur = SECTEURS.get(secteur_detecte, {})
    if config_secteur.get("actifs_physiques", False):
        score += 2

    # D6 — Souveraineté / Stratégique
    if config_secteur.get("souverainete", False):
        score += 2
    else:
        # Détection complémentaire sur texte (cyber peut être dans d'autres secteurs)
        mots_souv = ["bitd", "armement", "défense", "aéronaut", "naval", "dga",
                     "cyber", "cybersécur", "souverain"]
        if any(m in normalise(texte_complet) for m in mots_souv):
            score += 2

    # Géo — Bassin prioritaire
    texte_geo = normalise(f"{adresse} {tribunal}")
    geo_match = any(b in texte_geo for b in BASSINS_PRIORITAIRES)
    if geo_match:
        score += 2

    # Urgence
    if "liquidation" in proc_lower or "cession" in proc_lower or "résolution" in proc_lower:
        urgence = "Haute"
    elif "redressement" in proc_lower:
        urgence = "Haute"
    elif "sauvegarde" in proc_lower:
        urgence = "Basse"
    else:
        urgence = "Moyenne"

    return score, secteur_detecte, procedure_raw, urgence, geo_match


# ---------------------------------------------------------------------------
# RÉCUPÉRATION BODACC
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
        f"**{len(dossiers)} dossier(s) retenu(s)** — score ≥ {SCORE_MIN}/20, secteur cible identifié",
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
        lignes += [f"## {emoji_map[niveau]} Urgence {niveau}", ""]
        for d in groupes[niveau]:
            geo_tag = " 📍" if d["geo_match"] else ""
            lignes += [
                f"### {d['denomination']}{geo_tag} — Score {d['score']}/20",
                "",
                "| Champ | Valeur |",
                "|-------|--------|",
                f"| SIREN | {d['siren']} |",
                f"| Adresse | {d['adresse']} |",
                f"| Procédure | {d['procedure']} |",
                f"| Secteur | {d['secteur'] or 'Non classifié'} |",
                f"| Date parution | {d['date_parution']} |",
                "",
                "---",
                "",
            ]

    lignes.append(f"*Généré automatiquement par MASARE-Veille — {datetime.now().strftime('%d/%m/%Y %H:%M')}*")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# GITHUB ISSUES — UPSERT
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
    urgence_tag   = "URGENT" if dossier["urgence"] == "Haute" else "STANDARD"
    secteur_court = (dossier["secteur"] or "Non classifié").split("(")[0].strip()
    if len(secteur_court) > 40:
        secteur_court = secteur_court[:37] + "..."
    return (
        f"ALERTE {urgence_tag} — {dossier['denomination']} — "
        f"Score {dossier['score']}/20 — {secteur_court} — {dossier['urgence']} urgence"
    )


def construire_corps_issue(
    dossier: dict,
    api_gouv: dict,
    historique: list,
    pappers: dict,
    analyse_ia: str,
    date_rapport: str,
) -> str:
    geo_tag = " 📍 Bassin prioritaire" if dossier["geo_match"] else ""

    # Catégorie & taille
    categorie      = api_gouv.get("categorie", "N/D")
    taille_warning = "\n> ⚠️ **PME** — taille à vérifier manuellement (CA cible ≥ 20M€)\n" if categorie == "PME" else ""
    effectif_off   = api_gouv.get("effectif_officiel", "N/D")
    annee_eff      = api_gouv.get("annee_effectif", "")
    effectif_label = f"{effectif_off} ({annee_eff})" if annee_eff else effectif_off
    statut         = api_gouv.get("statut", "N/D")
    naf_code       = api_gouv.get("naf_code", "N/D")
    date_creation  = api_gouv.get("date_creation", "N/D")

    # Dirigeants RNE
    dirigeants_rne = api_gouv.get("dirigeants_rne", [])
    if dirigeants_rne:
        dirigeants_md   = "\n".join(f"- {d}" for d in dirigeants_rne)
        bloc_dirigeants = f"\n### 👤 Dirigeants (Registre National des Entreprises)\n\n{dirigeants_md}\n"
    else:
        bloc_dirigeants = ""

    # Données financières Pappers
    if pappers:
        annee_fin = pappers.get("annee_dernier", "")
        ca_str    = format_montant(pappers.get("ca_dernier"))
        res_str   = format_montant(pappers.get("resultat_dernier"))
        ebi_str   = format_montant(pappers.get("ebitda_dernier"))

        lignes_fin = [
            "",
            f"### 📊 Données financières (source Pappers — exercice {annee_fin})",
            "",
            "| Indicateur | Valeur |",
            "|------------|--------|",
            f"| Chiffre d'affaires | {ca_str} |",
            f"| EBITDA | {ebi_str} |",
            f"| Résultat net | {res_str} |",
        ]

        exercices = pappers.get("exercices", [])
        if len(exercices) > 1:
            lignes_fin += [
                "",
                "**Évolution CA sur 3 ans :**",
                "",
                "| Exercice | CA | Résultat net |",
                "|----------|-----|--------------|",
            ]
            for ex in exercices:
                lignes_fin.append(
                    f"| {ex['annee']} | {format_montant(ex['ca'])} | {format_montant(ex['resultat'])} |"
                )

        bloc_financier = "\n".join(lignes_fin)
    else:
        statut_pappers = (
            "_Données financières non disponibles — activer PAPPERS_TOKEN pour CA/EBITDA/résultat_"
            if not PAPPERS_TOKEN
            else "_Données financières non retournées par Pappers pour ce SIREN_"
        )
        bloc_financier = f"\n### 📊 Données financières\n\n{statut_pappers}\n"

    # Historique BODACC
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

    # Analyse IA
    if analyse_ia:
        bloc_ia = f"\n---\n\n## 🤖 Analyse MASARE\n\n{analyse_ia}\n"
    else:
        bloc_ia = ""

    # Contacts
    contacts_md = (
        "\n".join(f"- {c}" for c in dossier["contacts"])
        if dossier["contacts"]
        else "_Aucun contact extrait du BODACC_"
    )

    return f"""## {dossier['denomination']}{geo_tag}
{taille_warning}
| Champ | Valeur |
|-------|--------|
| SIREN | {dossier['siren']} |
| Forme juridique | {dossier['forme_juridique']} |
| Catégorie entreprise | {categorie} |
| Effectif officiel (INSEE) | {effectif_label} |
| Statut administratif | {statut} |
| NAF | {naf_code} |
| Date création | {date_creation} |
| Adresse | {dossier['adresse']} |
| Tribunal | {dossier['tribunal']} |
| Procédure | {dossier['procedure']} |
| Secteur détecté | {dossier['secteur'] or 'Non classifié'} |
| Score MASARE | {dossier['score']}/20 |
| Urgence | {dossier['urgence']} |
| Date parution BODACC | {dossier['date_parution']} |
| Dernière mise à jour veille | {date_rapport} |
{bloc_dirigeants}
{bloc_financier}
{bloc_historique}
{bloc_ia}
### 📞 Contacts & Mandataires
{contacts_md}

---
_Généré automatiquement par MASARE-Veille_
"""


def construire_labels(dossier: dict, api_gouv: dict) -> list:
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
    if score == 20:
        labels.append("score-20")
    elif score >= 18:
        labels.append("score-18-19")
    elif score >= 16:
        labels.append("score-16-17")

    secteur = (dossier["secteur"] or "").lower()
    if "bitd" in secteur or "défense" in secteur or "aéronaut" in secteur:
        labels.append("BITD")
    if "saas" in secteur or "logiciel" in secteur or "cyber" in secteur:
        labels.append("tech-saas")
    if "immobilier" in secteur or "hôtellerie" in secteur:
        labels.append("immobilier")

    if api_gouv.get("categorie") == "PME":
        labels.append("taille-a-verifier")

    return labels


def upsert_issue_github(
    dossier: dict,
    api_gouv: dict,
    historique: list,
    pappers: dict,
    analyse_ia: str,
    date_rapport: str,
):
    if not GITHUB_TOKEN:
        return

    siren  = dossier["siren"]
    titre  = construire_titre_issue(dossier)
    corps  = construire_corps_issue(dossier, api_gouv, historique, pappers, analyse_ia, date_rapport)
    labels = construire_labels(dossier, api_gouv)

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
            json={"body": f"🔄 **Mise à jour MASARE-Veille — {date_rapport}**\n\nNouvelle occurrence BODACC. Données mises à jour."},
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
    print(f"[MASARE-Veille] Seuil publication : {SCORE_MIN}/20 | Seuil IA : {PRE_AI_THRESHOLD}/20")
    print(f"[MASARE-Veille] Pappers : {'activé' if PAPPERS_TOKEN else 'désactivé (PAPPERS_TOKEN absent)'}")
    print(f"[MASARE-Veille] Groq IA   : {'activée' if GROQ_API_KEY else 'désactivée (GROQ_API_KEY absent)'}")

    records = fetch_bodacc()
    print(f"[MASARE-Veille] {len(records)} annonce(s) BODACC récupérée(s)")

    dossiers_retenus = []
    ecarts_score     = 0

    for record in records:
        # ── Scoring de base (D1, D3, D4, D6, Géo) — sans API externes ──
        score_base, secteur, procedure, urgence, geo_match = scorer_dossier(record)

        if score_base == 0:
            # Dossier disqualifié (PP, exclu, non classifié)
            continue

        siren        = extraire_siren(record)
        denomination = extraire_denomination(record)

        # ── D5 — Taille (data.gouv.fr) ──
        api_gouv     = enrichir_depuis_api_gouv(siren)
        taille_score = api_gouv.get("taille_score", 0)
        score_taille = score_base + taille_score

        # ── Historique & Pappers ──
        historique_rec = historique_bodacc(siren)
        pappers        = enrichir_depuis_pappers(siren)

        # ── D2 — Rentabilité historique (bonus Pappers) ──
        bonus_pappers = calculer_bonus_pappers(pappers)
        score_mid     = score_taille + bonus_pappers

        # ── D7 — Marque/Leader (bonus Claude IA) — seulement si score_mid >= PRE_AI_THRESHOLD ──
        if score_mid >= PRE_AI_THRESHOLD:
            analyse_ia, marque_score = enrichir_avec_ia(dossier_temp := {
                "denomination":    denomination,
                "siren":           siren,
                "forme_juridique": extraire_forme_juridique(record),
                "adresse":         extraire_adresse(record),
                "tribunal":        extraire_tribunal(record),
                "procedure":       procedure,
                "secteur":         secteur,
                "contacts":        [],
            }, api_gouv, pappers, historique_rec)
        else:
            analyse_ia, marque_score = "", 0

        # ── Score final (plafonné à 20) ──
        final_score = min(score_mid + marque_score, 20)

        if final_score < SCORE_MIN:
            ecarts_score += 1
            continue

        # ── Dossier retenu ──
        dossier = {
            "denomination":    denomination,
            "siren":           siren,
            "forme_juridique": extraire_forme_juridique(record),
            "adresse":         extraire_adresse(record),
            "tribunal":        extraire_tribunal(record),
            "procedure":       procedure,
            "secteur":         secteur,
            "date_parution":   record.get("dateparution", "") or "N/A",
            "contacts":        extraire_contacts(record),
            "score":           final_score,
            "urgence":         urgence,
            "geo_match":       geo_match,
        }

        detail_score = (
            f"D1={score_base - (score_base - (6 if secteur and SECTEURS.get(secteur, {}).get('priorite') == 1 else 4 if secteur else 0))} "
            f"taille=+{taille_score} pappers=+{bonus_pappers} IA=+{marque_score}"
        )
        print(f"  → Retenu : {denomination} (SIREN {siren}) — Score {final_score}/20")

        if api_gouv.get("categorie") == "PME":
            print(f"    ⚠️ PME — taille à vérifier")

        dossiers_retenus.append((dossier, api_gouv, historique_rec, pappers, analyse_ia))

    dossiers_retenus.sort(key=lambda x: x[0]["score"], reverse=True)
    print(f"[MASARE-Veille] {len(dossiers_retenus)} dossier(s) retenu(s) — {ecarts_score} écarté(s) score")

    rapport = generer_rapport([d for d, *_ in dossiers_retenus], date_rapport)
    nom_fichier = f"rapport_{date_rapport}.md"
    with open(nom_fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"[MASARE-Veille] Rapport généré : {nom_fichier}")

    if GITHUB_TOKEN:
        print("[MASARE-Veille] Synchronisation GitHub Issues...")
        charger_issues_ouvertes()
        for dossier, api_gouv, historique_rec, pappers, analyse_ia in dossiers_retenus:
            upsert_issue_github(dossier, api_gouv, historique_rec, pappers, analyse_ia, date_rapport)
        print("[MASARE-Veille] Issues synchronisées")
    else:
        print("[MASARE-Veille] GITHUB_TOKEN absent — issues ignorées")


if __name__ == "__main__":
    main()
