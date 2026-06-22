#!/usr/bin/env python3
"""
Veille Distressed MASARE — Version Production
Automatise : BODACC API + Web + Contacts + Scoring + Rapport + GitHub Issues
Exécution quotidienne recommandée : 08:00 CET
"""

import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import subprocess
import os

# =====================================================================
# CONFIG
# =====================================================================

NAF_TARGETS = {
    # Industrie / Actifs lourds
    "2511Z": "Fabrication de structures métalliques",
    "2512Z": "Réservoirs, citernes, conteneurs",
    "2521Z": "Articles en métal forméié",
    "2550A": "Forge, estampage, matriçage",
    "2562B": "Usinage",
    "2651A": "Équipements de distribution",
    "2651B": "Équipements de commutation",
    "2811Z": "Moteurs et turbines",
    "2829B": "Équipements divers",
    "3030Z": "Aéronautique",
    "3254Z": "Munitions et projectiles",
    "2520Z": "Produits minéraux",

    # Cybersécurité / Tech / Défense
    "6201Z": "Programmation informatique",
    "6202A": "Conseil en systèmes informatiques",
    "6209Z": "Activités informatiques",
    "6311Z": "Traitement données",
    "7112B": "Ingénierie études techniques",
    "7219Z": "Recherche-développement",

    # Immobilier tertiaire
    "4110A": "Promo immob. résidentielle",
    "4110B": "Promo immob. non résidentielle",
    "6810Z": "Location immobilière",
    "6820B": "Location immeuble bureaux",
    "6831Z": "Agences immobilières",
    "6832B": "Gestion immeuble",
    "5510Z": "Hôtels",
    "5520Z": "Hébergement touristique",
    "5590Z": "Autres hébergements",

    # Marques / Médias
    "1812Z": "Autres imprimeries",
    "2670Z": "Articles optique",
    "4741Z": "Commerce livres",
    "5814Z": "Édition journaux",
    "1820Z": "Reproduction enregistrements",
    "4762Z": "Commerce optique",
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
    passif_montant: Optional[float] = None
    score: float = 0.0
    flag_bitd: bool = False
    flag_marque: bool = False
    flag_actifs_sup_passif: Optional[bool] = None
    flag_ebitda_sup_20: Optional[bool] = None
    mode_entree: str = "barre"
    urgence: str = "moyenne"
    source: str = "BODACC"
    contacts: Dict[str, Any] = field(default_factory=dict)
    synthese: str = ""

# =====================================================================
# ÉTAPE 1 — BODACC API
# =====================================================================

def get_bodacc_data(date_hier: str) -> List[Dict]:
    """Récupère données BODACC, filtre NAF cibles."""
    url = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

    params = {"limit": 100, "sort": "-dateparution"}
    full_url = f"{url}?{'&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())}"

    try:
        req = urllib.request.Request(
            full_url,
            headers={'User-Agent': 'Claude-Code-MASARE/1.0'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            results = data.get("results", [])

            # Filtre : on cherche des procédures collectives
            filtered = []
            for rec in results:
                familia = rec.get("familleavis_lib", "").lower()
                if any(x in familia for x in ["rj", "lj", "sauvegarde", "procedure"]):
                    filtered.append(rec)

            return filtered[:20]
    except Exception as e:
        print(f"⚠️  BODACC: {str(e)[:100]}", file=sys.stderr)
        return []

# =====================================================================
# ÉTAPE 2 — RECOUPEMENT WEB (placeholder)
# =====================================================================

def recoupement_web() -> List[Dict]:
    """Placeholder : recherches web parallèles."""
    return []

# =====================================================================
# ÉTAPE 3 — RECHERCHE CONTACTS (placeholder)
# =====================================================================

def search_contacts(dossier: Dossier) -> Dict[str, Any]:
    """Placeholder : recherche Pappers/Societe.com/Infogreffe."""
    return {}

# =====================================================================
# ÉTAPE 4 — SCORING
# =====================================================================

def score_dossier(dossier: Dossier) -> float:
    """Calcule score MASARE 0-10."""
    score = 0.0

    # Actifs (0-3)
    if dossier.naf and dossier.naf in NAF_TARGETS:
        if dossier.naf in ["3030Z", "2811Z", "2829B", "2511Z", "2512Z"]:
            score += 3
        elif dossier.naf.startswith("2") or dossier.naf.startswith("3"):
            score += 2
        elif dossier.naf.startswith("6") or dossier.naf.startswith("7"):
            score += 1
    else:
        score += 1

    # EBITDA (0-2)
    if dossier.ebitda_historique == "> 20%":
        score += 2
        dossier.flag_ebitda_sup_20 = True
    elif dossier.ebitda_historique == "10-20%":
        score += 1

    # Procédure (0-2)
    if dossier.procedure == "redressement judiciaire":
        score += 2
        dossier.urgence = "haute"
    elif dossier.procedure == "sauvegarde":
        score += 2
        dossier.urgence = "moyenne"
    elif dossier.procedure == "liquidation judiciaire":
        score += 1
        dossier.urgence = "haute"

    # Taille (0-2)
    if (dossier.effectif and dossier.effectif > 50) or (dossier.ca_estim and dossier.ca_estim > 10):
        score += 2
    elif (dossier.effectif and dossier.effectif >= 20) or (dossier.ca_estim and dossier.ca_estim >= 3):
        score += 1

    # Stratégic (0-1)
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
- Flags EBITDA > 20% : {len([d for d in dossiers_retenus if d.flag_ebitda_sup_20])}
- Flags Actifs > Passif : {len([d for d in dossiers_retenus if d.flag_actifs_sup_passif])}

## Dossiers retenus

"""

    for d in dossiers_sorted:
        rapport += f"""### {d.nom} — Score {d.score:.0f}/10

- **Secteur** : {NAF_TARGETS.get(d.naf, d.naf)} · **Ville** : {d.ville}
- **SIREN** : {d.siren or 'ND'}
- **Procédure** : {d.procedure} · Date : {d.date_ouverture}
- **Tribunal** : {d.tribunal or 'ND'}
- **Effectif** : {d.effectif or 'ND'} · **CA estim.** : {d.ca_estim or 'ND'} M€
- **EBITDA** : {d.ebitda_historique}
- **Actifs** : {d.actifs_descrip or 'À identifier'}
- **BITD** : {'Oui' if d.flag_bitd else 'Non'} · **Marque** : {'Oui' if d.flag_marque else 'Non'}
- **Mode entrée** : {d.mode_entree} · **Urgence** : {d.urgence}

---

"""

    return rapport

# =====================================================================
# ÉTAPE 6 — GITHUB ISSUES
# =====================================================================

def create_github_issue(dossier: Dossier) -> bool:
    """Crée issue GitHub si score >= 8."""
    if dossier.score < 8:
        return False

    urgence_label = "URGENT" if dossier.urgence == "haute" else "STANDARD"
    titre = f"ALERTE [{urgence_label}] — {dossier.nom} — Score {dossier.score:.0f}/10 — {NAF_TARGETS.get(dossier.naf, dossier.naf)}"

    corps = f"""## {dossier.nom}

**SIREN** : {dossier.siren or 'ND'}
**Score MASARE** : {dossier.score:.0f}/10
**Urgence** : {dossier.urgence}

| Champ | Valeur |
|-------|--------|
| Procédure | {dossier.procedure} |
| Tribunal | {dossier.tribunal or 'ND'} |
| Effectif | {dossier.effectif or 'ND'} |
| CA | {dossier.ca_estim or 'ND'} M€ |
| EBITDA | {dossier.ebitda_historique} |
| BITD | {'Oui' if dossier.flag_bitd else 'Non'} |
| Marque | {'Oui' if dossier.flag_marque else 'Non'} |

---
*Veille MASARE — {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    try:
        result = subprocess.run(
            ["gh", "issue", "create",
             "--title", titre,
             "--body", corps,
             "--label", f"alert-{dossier.urgence}",
             "--repo", "matsaunder/masare-veille"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"✓ Issue créée: {titre[:50]}...", file=sys.stderr)
            return True
        else:
            print(f"⚠️  gh CLI: {result.stderr[:100]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"⚠️  {str(e)[:80]}", file=sys.stderr)
        return False

# =====================================================================
# MAIN
# =====================================================================

def main():
    date_hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_rapport = datetime.now().strftime("%Y%m%d")

    print(f"🚀 MASARE Veille — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Analysant : {date_hier}")
    print()

    # ===== ÉTAPE 1 =====
    print("📊 ÉTAPE 1 — BODACC API...", file=sys.stderr)
    bodacc_records = get_bodacc_data(date_hier)
    print(f"   ✓ {len(bodacc_records)} annonces", file=sys.stderr)

    # ===== ÉTAPE 2 =====
    print("🌐 ÉTAPE 2 — Recoupement web...", file=sys.stderr)
    web_records = recoupement_web()
    print(f"   ✓ {len(web_records)} dossiers web", file=sys.stderr)

    # ===== Construire candidats =====
    dossiers_candidats = []
    for rec in bodacc_records:
        d = Dossier(
            nom=rec.get("commercant", "Unknown"),
            siren="",
            naf="UNKNOWN",
            ville=rec.get("ville", "") or rec.get("cp", "")[:2],
            procedure=rec.get("familleavis_lib", "procedure"),
            date_ouverture=rec.get("dateparution", ""),
            tribunal=rec.get("tribunal", ""),
            source="BODACC",
        )
        dossiers_candidats.append(d)

    print(f"   ✓ {len(dossiers_candidats)} candidats", file=sys.stderr)
    print()

    # ===== ÉTAPE 3 =====
    print("👥 ÉTAPE 3 — Contacts...", file=sys.stderr)
    for d in dossiers_candidats:
        d.contacts = search_contacts(d)
    print(f"   ✓ Contacts recherchés", file=sys.stderr)
    print()

    # ===== ÉTAPE 4 =====
    print("⭐ ÉTAPE 4 — Scoring...", file=sys.stderr)
    for d in dossiers_candidats:
        d.score = score_dossier(d)

    dossiers_retenus = [d for d in dossiers_candidats if d.score >= 6]
    print(f"   ✓ {len(dossiers_retenus)}/{len(dossiers_candidats)} retenus", file=sys.stderr)
    print()

    # ===== ÉTAPE 5 =====
    print("📝 ÉTAPE 5 — Rapport...", file=sys.stderr)
    rapport = generate_rapport(dossiers_retenus, date_rapport)
    rapport_file = f"rapport_{date_rapport}.md"
    with open(rapport_file, "w") as f:
        f.write(rapport)
    print(f"   ✓ {rapport_file}", file=sys.stderr)
    print()

    # ===== ÉTAPE 6 =====
    print("🔔 ÉTAPE 6 — Alertes GitHub...", file=sys.stderr)
    alertes = sum(1 for d in dossiers_retenus if create_github_issue(d))
    print(f"   ✓ {alertes} issues (score ≥ 8)", file=sys.stderr)
    print()

    print(f"✅ Veille complète — Rapport : {rapport_file}")

if __name__ == "__main__":
    main()
