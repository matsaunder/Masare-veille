#!/usr/bin/env python3
"""
Système de déduplication MASARE — Évite les doublons d'issues
Détecte par SIREN et met à jour plutôt que de créer doublon
"""

import json
import urllib.request
import os
from datetime import datetime

DOSSIERS_DB = "dossiers_traites.json"
OWNER = "matsaunder"
REPO = "masare-veille"

def load_dossiers_db():
    """Charge la base de données des dossiers traités."""
    if os.path.exists(DOSSIERS_DB):
        with open(DOSSIERS_DB, "r") as f:
            return json.load(f)
    return {}

def save_dossiers_db(db):
    """Sauvegarde la base de données des dossiers traités."""
    with open(DOSSIERS_DB, "w") as f:
        json.dump(db, f, indent=2)

def find_issue_by_siren(siren: str, token: str) -> dict:
    """Cherche une issue GitHub existante par SIREN."""
    if not siren or siren == "ND":
        return None

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues?state=open&per_page=100"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MASARE",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            issues = json.loads(response.read().decode())

            # Chercher issue avec ce SIREN dans le body
            for issue in issues:
                if siren in issue.get("body", ""):
                    return issue

            return None
    except Exception as e:
        print(f"⚠️  Erreur recherche issue: {str(e)[:80]}")
        return None

def update_github_issue(issue_number: int, titre: str, corps: str, labels: list, token: str) -> bool:
    """Met à jour une issue GitHub existante."""
    if not token:
        print("⚠️  GITHUB_TOKEN non défini")
        return False

    payload = {
        "title": titre,
        "body": corps,
        "labels": labels,
    }

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{issue_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MASARE",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="PATCH"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            print(f"✓ Issue #{issue_number} mise à jour: {titre[:50]}...")
            return True
    except Exception as e:
        print(f"⚠️  Erreur mise à jour: {str(e)[:80]}")
        return False

def create_github_issue(titre: str, corps: str, labels: list, token: str) -> dict:
    """Crée une nouvelle issue GitHub."""
    if not token:
        print("⚠️  GITHUB_TOKEN non défini")
        return None

    payload = {
        "title": titre,
        "body": corps,
        "labels": labels,
    }

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MASARE",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            print(f"✓ Nouvelle issue créée #{result.get('number')}: {titre[:50]}...")
            return result
    except Exception as e:
        print(f"⚠️  Erreur création: {str(e)[:80]}")
        return None

def manage_github_issue(dossier, token: str, action="create_or_update") -> bool:
    """
    Gère une issue GitHub (crée ou met à jour selon déduplication).
    Retourne True si création/mise à jour réussie.
    """
    if dossier.score < 8:
        return False

    # Paramètres issue
    urgence_label = "URGENT" if dossier.urgence == "haute" else "STANDARD"
    titre = f"ALERTE [{urgence_label}] — {dossier.nom} — Score {dossier.score:.0f}/10"

    NAF_TARGETS = {
        "3030Z": "Aéronautique", "2811Z": "Moteurs", "6201Z": "Programmation",
        "6202A": "Conseil IT", "2511Z": "Structures métalliques",
    }

    corps = f"""## {dossier.nom}

**SIREN** : {dossier.siren}
**Score MASARE** : {dossier.score:.0f}/10
**Urgence** : {dossier.urgence}
**Dernière mise à jour** : {datetime.now().strftime('%Y-%m-%d %H:%M')}

### Informations

| Champ | Valeur |
|-------|--------|
| Procédure | {dossier.procedure} |
| Tribunal | {dossier.tribunal or 'ND'} |
| Secteur | {NAF_TARGETS.get(dossier.naf, dossier.naf)} |
| CA | {dossier.ca_estim or 'ND'} M€ |
| Effectif | {dossier.effectif or 'ND'} |
| EBITDA | {dossier.ebitda_historique} |
| Actifs | {dossier.actifs_descrip or 'À identifier'} |
| BITD | {'Oui' if dossier.flag_bitd else 'Non'} |
| Marque | {'Oui' if dossier.flag_marque else 'Non'} |

### Synthèse
{dossier.synthese or 'Dossier en cours d\'analyse'}

---
*Veille MASARE automatisée — Harmonisée*
"""

    labels = [f"alert-{dossier.urgence}", f"score-{int(dossier.score)}"]
    if dossier.flag_bitd:
        labels.append("BITD")
    if dossier.flag_marque:
        labels.append("marque")

    # ===== DÉDUPLICATION =====
    existing_issue = find_issue_by_siren(dossier.siren, token)

    if existing_issue:
        # Mise à jour issue existante
        print(f"🔄 Doublon détecté (SIREN {dossier.siren})")
        return update_github_issue(
            existing_issue["number"],
            titre,
            corps,
            labels,
            token
        )
    else:
        # Créer nouvelle issue
        result = create_github_issue(titre, corps, labels, token)
        return result is not None

# =====================================================================
# TEST / DÉMO
# =====================================================================

if __name__ == "__main__":
    # Exemple dossier
    class DossierTest:
        nom = "AEROTECH COMPOSITES"
        siren = "412897563"
        naf = "3030Z"
        score = 9
        urgence = "haute"
        procedure = "Redressement judiciaire"
        tribunal = "Toulouse"
        ca_estim = 38
        effectif = None
        ebitda_historique = "-28%"
        actifs_descrip = "Outil industriel moderne"
        synthese = "Équipementier Airbus/Dassault"
        flag_bitd = True
        flag_marque = False

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        result = manage_github_issue(DossierTest(), token)
        print(f"\n{'✅ Succès' if result else '❌ Erreur'}")
    else:
        print("⚠️  GITHUB_TOKEN non défini")
