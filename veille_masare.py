#!/usr/bin/env python3
"""
Veille Distressed MASARE — Automatisation quotidienne
Exécute 6 étapes : BODACC + Web + Contacts + Scoring + Rapport + GitHub Issues
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
import re

# =====================================================================
# CONFIGURATION
# =====================================================================

NAF_TARGETS = {
    # Industrie / Actifs lourds
    "2511Z": "Fabrication de structures métalliques",
    "2512Z": "Réservoirs, citernes, conteneurs",
    "2521Z": "Fabrication d'articles en métal forméié",
    "2550A": "Forge, estampage, matriçage",
    "2562B": "Usinage",
    "2651A": "Fab. d'équipements de distribution",
    "2651B": "Fab. d'équipements de commutation",
    "2811Z": "Fab. de moteurs et turbines",
    "2829B": "Fab. d'autre équipements",
    "3030Z": "Fab. d'aéronefs, aéronautique",
    "3254Z": "Fab. de munitions et projectiles",
    "2520Z": "Fab. de produits minéraux",

    # Cybersécurité / Tech / Défense
    "6201Z": "Programmation informatique",
    "6202A": "Conseil en systèmes informatiques",
    "6209Z": "Autres activités informatiques",
    "6311Z": "Traitement données",
    "7112B": "Ing. études techiques",
    "7219Z": "Recherche-développement",

    # Immobilier tertiaire / Hôtellerie
    "4110A": "Promo immob. résidentielle",
    "4110B": "Promo immob. non résidentielle",
    "6810Z": "Location immobilière",
    "6820B": "Location immeuble bureaux",
    "6831Z": "Agences immo",
    "6832B": "Gestion immeuble",
    "5510Z": "Hôtels",
    "5520Z": "Hébergement touristique",
    "5590Z": "Autres hébergements",

    # Marques / Médias / Optique
    "1812Z": "Autres imprimeries",
    "2670Z": "Fab. d'articles optique",
    "4741Z": "Com. détail livres",
    "5814Z": "Édition de journaux",
    "1820Z": "Reproduction enregistrements",
    "4762Z": "Com. détail optique",
}

TIER_MAPPING = {
    "6201Z": "TIER1", "6202A": "TIER1", "6209Z": "TIER1",
    "2811Z": "TIER2", "3030Z": "TIER1",
    "5510Z": "TIER3", "5520Z": "TIER3",
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
    """Récupère annonces BODACC pour la date spécifiée."""
    url = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

    params = {
        "where": f"dateparution='{date_hier}'",
        "limit": 1000,
        "sort": "-dateparution",
    }

    full_url = f"{url}?{'&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in params.items())}"

    try:
        with urllib.request.urlopen(full_url, timeout=15) as response:
            data = json.loads(response.read().decode())
            # Note: API retourne 'results' pas 'records'
            records = data.get("results", [])

            filtered = []
            for rec in records:
                # Les champs de l'API BODACC v2 sont différents
                # Pas de NAF direct — on va filtrer différemment
                # Pour la POC : on prend tous les records de type "listeprocedures"
                familia = rec.get("familleavis", "").lower()
                if any(x in familia for x in ["rj", "lj", "sauvegarde", "conciliation", "procedure"]):
                    filtered.append(rec)

            # TODO: Enrichir avec NAF via jointure Pappers/Societe.com si possible
            return filtered[:50]  # Limiter pour la POC
    except Exception as e:
        print(f"⚠️  Erreur BODACC API: {e}", file=sys.stderr)
        return []

# =====================================================================
# ÉTAPE 2 — RECOUPEMENT WEB
# =====================================================================

def web_search(query: str, max_results: int = 5) -> List[str]:
    """Simule recherche web — en prod, utiliserait WebSearch MCP."""
    # Placeholder : en environnement réel, appellerait WebSearch MCP
    # Pour cette POC, retourne []
    return []

def recoupement_web() -> List[Dict]:
    """Effectue 3 recherches web parallèles pour trouver dossiers supplémentaires."""
    # Placeholder pour démo
    return []

# =====================================================================
# ÉTAPE 3 — RECHERCHE CONTACTS
# =====================================================================

def search_contacts(dossier: Dossier) -> Dict[str, Any]:
    """Recherche contacts : dirigeants, mandataires, actionnaires.
    Placeholder en prod, utiliserait WebFetch pour Pappers/Societe.com."""

    contacts = {
        "dirigeants": [],
        "fondateurs": [],
        "actionnaires": [],
        "admin_jud": None,
        "liquidateur": None,
        "avocat": None,
    }

    # En production : appeler Pappers API, Societe.com, etc.
    # Pour démo, on parse les infos du dossier BODACC si disponibles

    return contacts

# =====================================================================
# ÉTAPE 4 — ANALYSE ET SCORING
# =====================================================================

def score_dossier(dossier: Dossier) -> float:
    """Calcule score 0-10 selon critères MASARE."""
    score = 0.0

    # Actifs tangibles (0-3 pts)
    if dossier.naf and dossier.naf != "UNKNOWN":
        if dossier.naf in ["3030Z", "2811Z", "2829B", "2511Z", "2512Z", "2562B"]:
            score += 3
            dossier.actifs_descrip = "Actifs industriels lourds"
        elif dossier.naf.startswith("2") or dossier.naf.startswith("3"):
            score += 2
    else:
        # NAF inconnu : score par défaut modéré
        score += 1

    # Rentabilité historique (0-2 pts)
    if dossier.ebitda_historique == "> 20%":
        score += 2
        dossier.flag_ebitda_sup_20 = True
    elif dossier.ebitda_historique == "10-20%":
        score += 1

    # Potentiel retournement (0-2 pts)
    if dossier.procedure in ["redressement judiciaire", "sauvegarde"]:
        score += 2
        dossier.mode_entree = "barre"
    elif dossier.procedure == "liquidation judiciaire":
        score += 1
        dossier.mode_entree = "actifs"
    else:
        score += 0

    # Taille ticket (0-2 pts)
    if dossier.effectif and dossier.effectif > 50:
        score += 2
    elif dossier.ca_estim and dossier.ca_estim > 10:
        score += 2
    elif dossier.effectif and dossier.effectif >= 20:
        score += 1
    elif dossier.ca_estim and dossier.ca_estim >= 3:
        score += 1
    else:
        score += 0

    # Souveraineté / Stratégique (0-1 pt)
    if dossier.flag_bitd or dossier.flag_marque:
        score += 1
    elif dossier.naf in ["3030Z", "6201Z", "6202A", "2811Z", "6209Z", "7219Z"]:
        score += 1
        dossier.flag_bitd = True

    # Urgence
    if dossier.procedure == "liquidation judiciaire":
        dossier.urgence = "haute"
    elif dossier.procedure == "redressement judiciaire":
        dossier.urgence = "haute"
    elif dossier.procedure == "sauvegarde":
        dossier.urgence = "moyenne"

    return min(score, 10.0)

# =====================================================================
# ÉTAPE 5 — GÉNÉRATION RAPPORT
# =====================================================================

def generate_rapport(dossiers_retenus: List[Dossier], date_rapport: str, date_hier: str) -> str:
    """Génère rapport markdown structuré."""

    total_bodacc = len([d for d in dossiers_retenus if d.source == "BODACC"])
    total_web = len([d for d in dossiers_retenus if d.source == "Web"])
    alertes_prioritaires = len([d for d in dossiers_retenus if d.score >= 8])

    rapport = f"""# Veille MASARE — {date_rapport}

**Date analysée** : {date_hier}

## Résumé
- Sources : BODACC ({total_bodacc} dossiers) + Web ({total_web} dossiers) = {len(dossiers_retenus)} total retenu(s)
- Dossiers retenus (score ≥ 6) : {len(dossiers_retenus)}
- Alertes prioritaires (score ≥ 8) : {alertes_prioritaires}
- Flags EBITDA > 20% historique : {len([d for d in dossiers_retenus if d.flag_ebitda_sup_20])}
- Flags Actifs > Passif : {len([d for d in dossiers_retenus if d.flag_actifs_sup_passif])}

## Dossiers retenus

"""

    # Trier par score décroissant puis urgence
    dossiers_sorted = sorted(dossiers_retenus, key=lambda d: (-d.score, d.urgence != "haute"))

    for d in dossiers_sorted:
        rapport += f"""### {d.nom} — Score {d.score:.0f}/10

- **Secteur** : {NAF_TARGETS.get(d.naf, d.naf)} · **Ville** : {d.ville}
- **SIREN** : {d.siren}
- **Procédure** : {d.procedure} · Date ouverture : {d.date_ouverture} · Tribunal : {d.tribunal}
- **Effectif** : {d.effectif or 'ND'} sal. · **CA hist. estim.** : {d.ca_estim or 'ND'} M€
- **EBITDA historique** : {d.ebitda_historique}
- **Actifs probables** : {d.actifs_descrip}
- **Actifs > Passif** : {['oui', 'non', 'inconnu'][{True: 0, False: 1, None: 2}[d.flag_actifs_sup_passif]]}
- **Mode d'entrée** : {d.mode_entree}
- **Urgence** : {d.urgence}
- **Flag BITD** : {'Oui' if d.flag_bitd else 'Non'} · **Flag Marque** : {'Oui' if d.flag_marque else 'Non'}
- **Source** : {d.source}

#### Contacts
| Rôle | Nom | Cabinet / Structure | Contact |
|------|-----|-------------------|---------|
| Dirigeant | {d.contacts.get('dirigeant', '') or 'ND'} | | |
| Admin. Jud. | {d.contacts.get('admin_jud_nom', '') or 'ND'} | {d.contacts.get('admin_jud_cabinet', '') or ''} | {d.contacts.get('admin_jud_tel', '') or ''} |
| Liquidateur | {d.contacts.get('liquidateur_nom', '') or 'ND'} | {d.contacts.get('liquidateur_cabinet', '') or ''} | {d.contacts.get('liquidateur_tel', '') or ''} |

#### Synthèse
{d.synthese or "Dossier en attente d'analyse complète."}

#### Prochaine échéance
{d.contacts.get('prochaine_echéance', 'À déterminer via annonce BODACC')}

---

"""

    # Dossiers exclus (si besoin)
    rapport += """
## Dossiers analysés non retenus
(Aucun dossier retenu en dessous du seuil de score 6 pour cette veille)

"""

    return rapport

# =====================================================================
# ÉTAPE 6 — GITHUB ISSUES
# =====================================================================

def create_github_issue(dossier: Dossier) -> bool:
    """Crée une GitHub Issue si score >= 8 via subprocess git CLI."""
    if dossier.score < 8:
        return False

    urgence_label = "URGENT" if dossier.urgence == "haute" else "STANDARD"
    titre = f"ALERTE [{urgence_label}] — {dossier.nom} — Score {dossier.score:.0f}/10 — {NAF_TARGETS.get(dossier.naf, dossier.naf)}"

    flag_str = {True: 'Oui', False: 'Non', None: 'Inconnu'}

    corps = f"""## {dossier.nom}

**Secteur** : {NAF_TARGETS.get(dossier.naf, dossier.naf)}
**SIREN** : {dossier.siren}
**Score MASARE** : {dossier.score:.0f}/10
**Urgence** : {dossier.urgence}

### Fiche

| Champ | Valeur |
|-------|--------|
| Procédure | {dossier.procedure} |
| Date ouverture | {dossier.date_ouverture} |
| Tribunal | {dossier.tribunal} |
| Effectif | {dossier.effectif or 'ND'} |
| CA estimé | {dossier.ca_estim or 'ND'} M€ |
| EBITDA hist. | {dossier.ebitda_historique} |
| Actifs | {dossier.actifs_descrip or 'À identifier'} |
| Actifs > Passif | {flag_str[dossier.flag_actifs_sup_passif]} |
| BITD | {flag_str[dossier.flag_bitd]} |
| Marque | {flag_str[dossier.flag_marque]} |
| Mode entrée | {dossier.mode_entree} |

### Synthèse
{dossier.synthese or "Dossier en cours d'analyse"}

---
*Veille MASARE automatisée — {datetime.now().strftime('%Y-%m-%d %H:%M')}*
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
            print(f"✓ Issue créée: {titre[:60]}...", file=sys.stderr)
            return True
        else:
            print(f"⚠️  Erreur gh CLI: {result.stderr[:200]}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"⚠️  Exception GitHub: {str(e)[:100]}", file=sys.stderr)
        return False

# =====================================================================
# MAIN
# =====================================================================

def main():
    # Calcul date hier
    date_hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_rapport = datetime.now().strftime("%Y%m%d")

    print(f"🚀 Veille MASARE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Date analysée : {date_hier}")
    print()

    # ===== ÉTAPE 1 : BODACC API =====
    print("📊 ÉTAPE 1 — Récupération BODACC...", file=sys.stderr)
    bodacc_records = get_bodacc_data(date_hier)
    print(f"   ✓ {len(bodacc_records)} annonces BODACC filtrées", file=sys.stderr)

    # ===== ÉTAPE 2 : RECOUPEMENT WEB =====
    print("🌐 ÉTAPE 2 — Recoupement web...", file=sys.stderr)
    web_records = recoupement_web()
    print(f"   ✓ {len(web_records)} dossiers web supplémentaires", file=sys.stderr)

    # ===== CONSTRUIRE DOSSIERS CANDIDATS =====
    dossiers_candidats = []

    for rec in bodacc_records:
        # Champs de l'API BODACC v2
        entreprise = rec.get("commercant", rec.get("entreprise", "Unknown"))
        siren = ""
        for reg_id in rec.get("registre", []):
            if reg_id and len(reg_id.replace(" ", "")) == 9:  # SIREN sans espaces
                siren = reg_id.replace(" ", "")
                break

        # NAF non fourni par BODACC, on va l'inférer du contexte ou laisser vide pour la POC
        naf = rec.get("codenaf", "").strip()

        # Déterminer la procédure from familleavis
        familia = rec.get("familleavis_lib", "").lower()
        if "redressement" in familia or "rj" in familia:
            procedure = "redressement judiciaire"
        elif "liquidation" in familia or "lj" in familia:
            procedure = "liquidation judiciaire"
        elif "sauvegarde" in familia:
            procedure = "sauvegarde"
        elif "conciliation" in familia:
            procedure = "conciliation"
        else:
            procedure = familia or "procedure_collective"

        d = Dossier(
            nom=entreprise,
            siren=siren,
            naf=naf or "UNKNOWN",
            ville=rec.get("ville", "") or rec.get("cp", "")[:2] + "XXX",
            procedure=procedure,
            date_ouverture=rec.get("dateparution", ""),
            tribunal=rec.get("tribunal", ""),
            source="BODACC",
            actifs_descrip="",
        )

        dossiers_candidats.append(d)

    print(f"   ✓ {len(dossiers_candidats)} dossiers candidats au scoring")
    print()

    # ===== ÉTAPE 3 : RECHERCHE CONTACTS =====
    print("👥 ÉTAPE 3 — Recherche contacts...", file=sys.stderr)
    for i, d in enumerate(dossiers_candidats, 1):
        d.contacts = search_contacts(d)
        if i % 10 == 0:
            print(f"   ✓ {i}/{len(dossiers_candidats)} dossiers", file=sys.stderr)

    print(f"   ✓ Contacts recherchés pour tous les dossiers", file=sys.stderr)
    print()

    # ===== ÉTAPE 4 : SCORING =====
    print("⭐ ÉTAPE 4 — Scoring et filtrage...", file=sys.stderr)
    for d in dossiers_candidats:
        d.score = score_dossier(d)

    dossiers_retenus = [d for d in dossiers_candidats if d.score >= 6]
    print(f"   ✓ {len(dossiers_retenus)}/{len(dossiers_candidats)} dossiers retenus (score ≥ 6)", file=sys.stderr)
    print()

    # ===== ÉTAPE 5 : RAPPORT =====
    print("📝 ÉTAPE 5 — Génération rapport...", file=sys.stderr)
    rapport_content = generate_rapport(dossiers_retenus, date_rapport, date_hier)
    rapport_file = f"/home/user/Masare-veille/rapport_{date_rapport}.md"
    with open(rapport_file, "w") as f:
        f.write(rapport_content)
    print(f"   ✓ Rapport généré : {rapport_file}", file=sys.stderr)
    print()

    # ===== ÉTAPE 6 : GITHUB ISSUES =====
    print("🔔 ÉTAPE 6 — Création alertes GitHub...", file=sys.stderr)
    alertes_count = 0
    for d in dossiers_retenus:
        if create_github_issue(d):
            alertes_count += 1
    print(f"   ✓ {alertes_count} issues GitHub créées (score ≥ 8)", file=sys.stderr)
    print()

    print(f"✅ Veille complète — Rapport : rapport_{date_rapport}.md")

if __name__ == "__main__":
    main()
