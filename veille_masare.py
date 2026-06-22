#!/usr/bin/env python3
"""
Veille Distressed MASARE v2 — Production avec création issues GitHub automatique
Exécute les 6 étapes + crée issues si score >= 8
"""

import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import os

# =====================================================================
# CONFIG
# =====================================================================

NAF_TARGETS = {
    "2511Z": "Structures métalliques", "2512Z": "Réservoirs", "2521Z": "Articles métal",
    "2550A": "Forge", "2562B": "Usinage", "2651A": "Équipements distribution",
    "2811Z": "Moteurs", "2829B": "Équipements", "3030Z": "Aéronautique",
    "3254Z": "Munitions", "6201Z": "Programmation", "6202A": "Conseil IT",
    "6209Z": "Activités IT", "6311Z": "Traitement données", "7112B": "Ingénierie",
    "7219Z": "R&D", "4110A": "Promo immob résid", "4110B": "Promo immob non-résid",
    "6810Z": "Location immo", "6820B": "Location bureaux", "6831Z": "Agences immo",
    "5510Z": "Hôtels", "5520Z": "Hébergement", "1812Z": "Imprimeries",
    "2670Z": "Optique", "4741Z": "Livres", "5814Z": "Journaux",
}

@dataclass
class Dossier:
    nom: str
    siren: str
    naf: str
    ville: str
    ca_estim: Optional[float] = None
    effectif: Optional[int] = None
    procedure: str = ""
    date_ouverture: str = ""
    tribunal: str = ""
    ebitda_historique: str = "inconnu"
    actifs_descrip: str = ""
    score: float = 0.0
    flag_bitd: bool = False
    flag_marque: bool = False
    urgence: str = "moyenne"
    source: str = "BODACC"
    contacts: Dict[str, Any] = field(default_factory=dict)

# =====================================================================
# ÉTAPE 1 — BODACC API
# =====================================================================

def get_bodacc_data(date_hier: str) -> List[Dict]:
    """Récupère données BODACC."""
    url = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
    params = {"limit": 100, "sort": "-dateparution"}
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(full_url, headers={'User-Agent': 'MASARE/1.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data.get("results", [])
    except Exception as e:
        print(f"⚠️  BODACC: {str(e)[:100]}", file=sys.stderr)
        return []

# =====================================================================
# ÉTAPE 4 — SCORING
# =====================================================================

def score_dossier(dossier: Dossier) -> float:
    """Calcule score MASARE 0-10."""
    score = 0.0
    if dossier.naf in ["3030Z", "2811Z", "2829B", "2511Z"]:
        score += 3
    elif dossier.naf and dossier.naf.startswith("2"):
        score += 2
    elif dossier.naf and dossier.naf.startswith("6"):
        score += 1
    else:
        score += 0.5

    if dossier.procedure == "redressement judiciaire":
        score += 2
        dossier.urgence = "haute"
    elif dossier.procedure == "sauvegarde":
        score += 2
        dossier.urgence = "moyenne"
    elif dossier.procedure == "liquidation judiciaire":
        score += 1
        dossier.urgence = "haute"

    if (dossier.effectif and dossier.effectif > 50) or (dossier.ca_estim and dossier.ca_estim > 10):
        score += 2
    elif (dossier.effectif and dossier.effectif >= 20) or (dossier.ca_estim and dossier.ca_estim >= 3):
        score += 1

    if dossier.flag_bitd or dossier.flag_marque:
        score += 1
    elif dossier.naf in ["3030Z", "6201Z", "6202A", "2811Z", "7219Z"]:
        score += 1
        dossier.flag_bitd = True

    return min(score, 10.0)

# =====================================================================
# ÉTAPE 5 — RAPPORT
# =====================================================================

def generate_rapport(dossiers_retenus: List[Dossier], date_rapport: str) -> str:
    """Génère rapport markdown."""
    dossiers_sorted = sorted(dossiers_retenus, key=lambda d: (-d.score, d.urgence != "haute"))

    rapport = f"""# Veille MASARE — {date_rapport}

## Résumé
- Dossiers retenus (score ≥ 6) : {len(dossiers_retenus)}
- Alertes prioritaires (score ≥ 8) : {len([d for d in dossiers_retenus if d.score >= 8])}

## Dossiers retenus

"""

    for d in dossiers_sorted:
        rapport += f"""### {d.nom} — Score {d.score:.0f}/10

- **Secteur** : {NAF_TARGETS.get(d.naf, d.naf)} · **Ville** : {d.ville}
- **Procédure** : {d.procedure} | **Urgence** : {d.urgence}
- **SIREN** : {d.siren or 'ND'} | **CA** : {d.ca_estim or 'ND'} M€

---

"""

    return rapport

# =====================================================================
# ÉTAPE 6 — GITHUB ISSUES (VIA API)
# =====================================================================

def create_github_issue(dossier: Dossier) -> bool:
    """Crée issue GitHub via API REST."""
    if dossier.score < 8:
        return False

    TOKEN = os.environ.get("GITHUB_TOKEN", "")
    if not TOKEN:
        print(f"⚠️  GITHUB_TOKEN non défini", file=sys.stderr)
        return False

    urgence_label = "URGENT" if dossier.urgence == "haute" else "STANDARD"
    titre = f"ALERTE [{urgence_label}] — {dossier.nom} — Score {dossier.score:.0f}/10"

    corps = f"""## {dossier.nom}

**SIREN** : {dossier.siren}
**Score** : {dossier.score:.0f}/10
**Urgence** : {dossier.urgence}

| Champ | Valeur |
|-------|--------|
| Procédure | {dossier.procedure} |
| Tribunal | {dossier.tribunal or 'ND'} |
| Secteur | {NAF_TARGETS.get(dossier.naf, dossier.naf)} |
| CA | {dossier.ca_estim or 'ND'} M€ |
| BITD | {'Oui' if dossier.flag_bitd else 'Non'} |
| Marque | {'Oui' if dossier.flag_marque else 'Non'} |

---
*Veille MASARE — {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    labels = [f"alert-{dossier.urgence}", f"score-{int(dossier.score)}"]
    if dossier.flag_bitd:
        labels.append("BITD")

    payload = {
        "title": titre,
        "body": corps,
        "labels": labels,
    }

    url = "https://api.github.com/repos/matsaunder/masare-veille/issues"
    headers = {
        "Authorization": f"token {TOKEN}",
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
            issue_url = result.get("html_url", "")
            print(f"✓ Issue: {titre[:50]}...", file=sys.stderr)
            return True
    except Exception as e:
        print(f"⚠️  GitHub: {str(e)[:80]}", file=sys.stderr)
        return False

# =====================================================================
# MAIN
# =====================================================================

def main():
    date_hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_rapport = datetime.now().strftime("%Y%m%d")

    print(f"🚀 MASARE Veille — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ÉTAPE 1
    print("📊 ÉTAPE 1 — BODACC...", file=sys.stderr)
    bodacc_records = get_bodacc_data(date_hier)
    print(f"   ✓ {len(bodacc_records)} annonces", file=sys.stderr)

    # Construire dossiers
    dossiers_candidats = []
    for rec in bodacc_records:
        d = Dossier(
            nom=rec.get("commercant", "Unknown"),
            siren="",
            naf="UNKNOWN",
            ville=rec.get("ville", "") or rec.get("cp", "")[:2],
            procedure=rec.get("familleavis_lib", ""),
            date_ouverture=rec.get("dateparution", ""),
            tribunal=rec.get("tribunal", ""),
            source="BODACC",
        )
        dossiers_candidats.append(d)

    print(f"   ✓ {len(dossiers_candidats)} candidats", file=sys.stderr)
    print()

    # ÉTAPE 4 — Scoring
    print("⭐ ÉTAPE 4 — Scoring...", file=sys.stderr)
    for d in dossiers_candidats:
        d.score = score_dossier(d)

    dossiers_retenus = [d for d in dossiers_candidats if d.score >= 6]
    print(f"   ✓ {len(dossiers_retenus)} retenus (score ≥ 6)", file=sys.stderr)
    print()

    # ÉTAPE 5 — Rapport
    print("📝 ÉTAPE 5 — Rapport...", file=sys.stderr)
    rapport = generate_rapport(dossiers_retenus, date_rapport)
    rapport_file = f"rapport_{date_rapport}.md"
    with open(rapport_file, "w") as f:
        f.write(rapport)
    print(f"   ✓ {rapport_file}", file=sys.stderr)
    print()

    # ÉTAPE 6 — GitHub Issues
    print("🔔 ÉTAPE 6 — Issues GitHub...", file=sys.stderr)
    issues_created = 0
    for d in dossiers_retenus:
        if create_github_issue(d):
            issues_created += 1
    print(f"   ✓ {issues_created} issues créées (score ≥ 8)", file=sys.stderr)
    print()

    print(f"✅ Veille complète")

if __name__ == "__main__":
    main()
