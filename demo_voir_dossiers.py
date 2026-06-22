#!/usr/bin/env python3
"""
Veille MASARE — DÉMO avec données réelles BODACC
Affiche les dossiers trouvés avec scoring complet
"""

import urllib.request
import json
from datetime import datetime, timedelta

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

def fetch_bodacc_real_data():
    """Récupère les VRAIES dernières données BODACC (sans filtre date)."""
    url = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
    params = {"limit": 50, "sort": "-dateparution"}
    full_url = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    try:
        req = urllib.request.Request(full_url, headers={'User-Agent': 'MASARE-Demo'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("results", [])
    except Exception as e:
        print(f"❌ Erreur API: {e}")
        return []

def score_dossier_simple(naf, procedural):
    """Scoring simplifié pour démo."""
    score = 1  # Score de base

    # Industrie lourde
    if naf in ["3030Z", "2811Z", "2829B", "2511Z", "2512Z"]:
        score += 3
    elif naf and naf.startswith("2"):
        score += 2
    elif naf and naf.startswith("6"):
        score += 1

    # Procédure
    if "rj" in procedural.lower() or "redressement" in procedural.lower():
        score += 2
    elif "sauvegarde" in procedural.lower():
        score += 2
    elif "lj" in procedural.lower() or "liquidation" in procedural.lower():
        score += 1

    return min(score, 10)

def main():
    print("\n" + "="*90)
    print("🔍 MASARE VEILLE — RECHERCHE DOSSIERS RÉELS (BODACC)")
    print("="*90 + "\n")

    print("📡 Récupération des derniers dossiers BODACC...")
    all_records = fetch_bodacc_real_data()
    print(f"✓ {len(all_records)} dossiers trouvés\n")

    # Parser tous les dossiers (pas seulement procédures collectives)
    dossiers = []
    dossiers_by_type = {}

    for rec in all_records:
        familia = rec.get("familleavis_lib", "").lower()
        naf = rec.get("codenaf", "UNKNOWN")
        score = score_dossier_simple(naf, familia)

        dossier_info = {
            "nom": rec.get("commercant", "N/A"),
            "date": rec.get("dateparution", "N/A"),
            "ville": rec.get("ville", "") or rec.get("cp", "N/A")[:2],
            "tribunal": rec.get("tribunal", "N/A"),
            "procedure": rec.get("familleavis_lib", "N/A"),
            "naf": naf,
            "naf_label": NAF_TARGETS.get(naf, "Autre secteur"),
            "siren": rec.get("registre", [""])[0].replace(" ", "") if rec.get("registre") else "N/A",
            "score": score,
        }

        dossiers.append(dossier_info)

        # Grouper par type
        type_key = rec.get("familleavis_lib", "Unknown")
        dossiers_by_type[type_key] = dossiers_by_type.get(type_key, 0) + 1

    # Trier par score décroissant
    dossiers = sorted(dossiers, key=lambda d: -d["score"])

    print("\n" + "─"*90)
    print(f"📊 {len(dossiers)} DOSSIERS BODACC TROUVÉS\n")

    # Afficher types de dossiers disponibles
    print("📋 TYPES DE DOSSIERS DISPONIBLES:")
    for tipo, count in sorted(dossiers_by_type.items(), key=lambda x: -x[1])[:10]:
        print(f"   • {tipo}: {count}")
    print()

    # Affichage
    for i, d in enumerate(dossiers[:20], 1):
        score_color = "🔴" if d["score"] >= 8 else "🟠" if d["score"] >= 6 else "🟡"

        print(f"{i:2}. {score_color} SCORE {d['score']}/10 — {d['nom']}")
        print(f"    📍 {d['ville']} | 🏛️  {d['tribunal']}")
        print(f"    📅 {d['date']} | ⚖️  {d['procedure']}")
        print(f"    🏭 {d['naf']} ({d['naf_label']})")
        print(f"    SIREN: {d['siren']}\n")

    # Résumé
    print("\n" + "="*90)
    print("📈 RÉSUMÉ")
    print("="*90)
    print(f"Total procédures collectives : {len(dossiers)}")
    print(f"Score ≥ 8 (ALERTES) : {len([d for d in dossiers if d['score'] >= 8])}")
    print(f"Score 6-7 (Rapport) : {len([d for d in dossiers if 6 <= d['score'] < 8])}")
    print(f"Score < 6 (Veille) : {len([d for d in dossiers if d['score'] < 6])}\n")

    # Top secteurs
    print("🎯 TOP SECTEURS REPRÉSENTÉS:")
    sector_count = {}
    for d in dossiers:
        sector = d["naf_label"]
        sector_count[sector] = sector_count.get(sector, 0) + 1

    for sector, count in sorted(sector_count.items(), key=lambda x: -x[1])[:10]:
        print(f"   • {sector}: {count} dossier(s)")

    print("\n" + "="*90)
    print("💡 Pour filtrer davantage: modifier NAF_TARGETS ou les critères de score\n")

if __name__ == "__main__":
    main()
