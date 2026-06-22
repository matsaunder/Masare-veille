#!/usr/bin/env python3
"""
Veille MASARE — Recherche DOSSIERS DISTRESSED (RJ/LJ/Sauvegarde)
Explore l'API BODACC en profondeur pour trouver procédures collectives
"""

import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta
from typing import List, Dict

NAF_TARGETS = {
    "2511Z": "Structures métalliques", "2512Z": "Réservoirs", "2550A": "Forge",
    "2562B": "Usinage", "2651A": "Équipements distribution", "2811Z": "Moteurs",
    "2829B": "Équipements", "3030Z": "Aéronautique", "3254Z": "Munitions",
    "6201Z": "Programmation", "6202A": "Conseil IT", "6209Z": "Activités IT",
    "6311Z": "Traitement données", "7112B": "Ingénierie", "7219Z": "R&D",
}

def search_procedures_collectives(limit: int = 100) -> List[Dict]:
    """
    Recherche les procédures collectives parmi les 100 dernières annonces.
    """
    url = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"

    # Requête basique
    params = {
        "limit": limit,
        "sort": "-dateparution",
    }

    # Construire l'URL correctement
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(full_url, headers={'User-Agent': 'MASARE-Search'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            all_records = data.get("results", [])

            # Filtrer sur procédures collectives
            procedures = []
            for rec in all_records:
                # Chercher les mots-clés de procédures
                familia = rec.get("familleavis_lib", "").lower()
                commercant = rec.get("commercant", "").lower()
                observations = rec.get("observations", "").lower() if rec.get("observations") else ""

                is_procedure = any(keyword in (familia + commercant + observations) for keyword in [
                    "redressement", "rj", "liquidation", "lj", "sauvegarde", "conciliation",
                    "mandat ad hoc", "procédure collective", "jugement", "administrateur",
                    "liquidateur", "cessation de paiements"
                ])

                if is_procedure:
                    procedures.append(rec)

            return procedures

    except Exception as e:
        print(f"❌ Erreur API: {e}")
        return []

def score_dossier(naf: str, familia: str) -> float:
    """Score MASARE 0-10."""
    score = 0.0

    # Actifs
    if naf in ["3030Z", "2811Z", "2829B", "2511Z", "2512Z", "2562B"]:
        score += 3
    elif naf and naf in NAF_TARGETS:
        score += 2
    elif naf and naf.startswith("2"):
        score += 2
    elif naf and naf.startswith("6"):
        score += 1
    else:
        score += 0.5

    # Procédure
    if "redressement" in familia:
        score += 2
    elif "sauvegarde" in familia:
        score += 2
    elif "liquidation" in familia:
        score += 1
    elif "conciliation" in familia:
        score += 1

    return min(score, 10.0)

def format_siren(registre_list: List[str]) -> str:
    """Extrait SIREN de la liste de registres."""
    if not registre_list:
        return "N/A"
    for reg in registre_list:
        clean = reg.replace(" ", "")
        if len(clean) == 9 and clean.isdigit():
            return clean
    return registre_list[0] if registre_list else "N/A"

def main():
    print("\n" + "="*100)
    print("🔍 MASARE — RECHERCHE DOSSIERS DISTRESSED (RJ/LJ/Sauvegarde/Conciliation)")
    print("="*100 + "\n")

    print("📡 Recherche parmi 500 dernières annonces BODACC...")
    procedures = search_procedures_collectives(limit=500)
    print(f"✓ {len(procedures)} procédures collectives trouvées!\n")

    if not procedures:
        print("❌ Aucune procédure collective trouvée.")
        print("💡 Conseil: Vérifier directement sur https://www.bodacc.fr/\n")
        return

    # Convertir en dossiers avec scoring
    dossiers = []
    for rec in procedures:
        naf = rec.get("codenaf", "UNKNOWN")
        familia = rec.get("familleavis_lib", "")
        score = score_dossier(naf, familia.lower())

        dossier = {
            "nom": rec.get("commercant", "N/A"),
            "date": rec.get("dateparution", "N/A"),
            "ville": rec.get("ville", "N/A"),
            "tribunal": rec.get("tribunal", "N/A"),
            "procedure": familia,
            "naf": naf,
            "naf_label": NAF_TARGETS.get(naf, "Autre secteur"),
            "siren": format_siren(rec.get("registre", [])),
            "score": score,
            "url_bodacc": f"https://www.bodacc.fr/{rec.get('id', '')}" if rec.get('id') else "N/A"
        }
        dossiers.append(dossier)

    # Trier par score décroissant
    dossiers = sorted(dossiers, key=lambda d: -d["score"])

    # Affichage
    print("─"*100)
    print(f"📊 TOP {min(30, len(dossiers))} DOSSIERS PAR SCORE\n")

    for i, d in enumerate(dossiers[:30], 1):
        # Code couleur
        if d["score"] >= 8:
            icon = "🔴"
            label = "ALERTE"
        elif d["score"] >= 6:
            icon = "🟠"
            label = "RAPPORT"
        else:
            icon = "🟡"
            label = "VEILLE"

        print(f"{i:2}. {icon} [{label}] Score {d['score']:.1f}/10 — {d['nom']}")
        print(f"    📍 {d['ville']} | 🏛️  {d['tribunal']}")
        print(f"    ⚖️  {d['procedure']} | 📅 {d['date']}")
        print(f"    🏭 {d['naf']} - {d['naf_label']}")
        print(f"    SIREN: {d['siren']}")
        print()

    # Statistiques
    print("\n" + "="*100)
    print("📈 STATISTIQUES")
    print("="*100)
    print(f"Total procédures collectives : {len(dossiers)}")
    print(f"🔴 ALERTES (score ≥ 8) : {len([d for d in dossiers if d['score'] >= 8])}")
    print(f"🟠 RAPPORT (score 6-7) : {len([d for d in dossiers if 6 <= d['score'] < 8])}")
    print(f"🟡 VEILLE (score < 6) : {len([d for d in dossiers if d['score'] < 6])}")

    # Procédures
    print("\n📋 TYPES DE PROCÉDURES:")
    procedure_types = {}
    for d in dossiers:
        ptype = d["procedure"].split("-")[0].strip() if d["procedure"] else "Unknown"
        procedure_types[ptype] = procedure_types.get(ptype, 0) + 1

    for ptype, count in sorted(procedure_types.items(), key=lambda x: -x[1]):
        print(f"   • {ptype}: {count}")

    # Secteurs
    print("\n🎯 TOP SECTEURS (Dossiers NAF cibles):")
    naf_count = {}
    for d in dossiers:
        if d["naf"] in NAF_TARGETS:
            naf_count[d["naf_label"]] = naf_count.get(d["naf_label"], 0) + 1

    if naf_count:
        for sector, count in sorted(naf_count.items(), key=lambda x: -x[1])[:10]:
            print(f"   • {sector}: {count}")
    else:
        print("   (Aucun secteur cible identifié)")

    print("\n" + "="*100)
    print("💡 PROCHAINES ÉTAPES:")
    print("   1. Consulter les dossiers score ≥ 8 sur BODACC")
    print("   2. Valider avec mandataire judiciaire")
    print("   3. Analyser actifs et passif")
    print("   4. Évaluer clear path to recovery MASARE")
    print("="*100 + "\n")

if __name__ == "__main__":
    main()
