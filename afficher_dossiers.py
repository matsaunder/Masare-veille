#!/usr/bin/env python3
"""
Affiche les dossiers du rapport MASARE existant
"""

import re
from datetime import datetime

def parse_rapport():
    """Parse le rapport markdown et extrait les dossiers."""

    try:
        with open("rapport_20260619.md", "r") as f:
            content = f.read()
    except:
        print("❌ Rapport rapport_20260619.md non trouvé")
        return []

    # Parser les sections de dossiers
    dossiers = []
    sections = re.split(r'^### ', content, flags=re.MULTILINE)[1:]  # Skip le header

    for section in sections[:10]:  # Limiter à 10
        lines = section.split('\n')
        title = lines[0].strip()

        # Extraire score: peut être "9/10" ou "9 /10" ou "Score : 9/10"
        score_match = re.search(r'\*\*Score\*\*\s*:\s*([\d]+/[\d]+)', section)
        score = score_match.group(1) if score_match else "N/A"

        # Extraire autres infos
        siren_match = re.search(r'\*\*SIREN\*\*\s*:\s*([0-9\s]+)', section)
        siren = siren_match.group(1).replace(" ", "") if siren_match else "N/A"

        secteur_match = re.search(r'\*\*Secteur\*\*\s*:\s*([^\n]+)', section)
        secteur = secteur_match.group(1).strip() if secteur_match else "N/A"

        procedure_match = re.search(r'\*\*Procédure\*\*\s*:\s*([^\n]+)', section)
        procedure = procedure_match.group(1).strip() if procedure_match else "N/A"

        ca_match = re.search(r'CA\s+\d+\s+M€', section)
        ca = "ND"
        if ca_match:
            ca_full_match = re.search(r'CA.*?(\d+)\s+M€', section)
            ca = ca_full_match.group(1) if ca_full_match else "ND"

        urgence_match = re.search(r'\*\*Urgence\*\*\s*:\s*(Haute|Moyenne|Basse)', section)
        urgence = urgence_match.group(1) if urgence_match else "ND"

        dossiers.append({
            "nom": title,
            "score": score,
            "siren": siren,
            "secteur": secteur,
            "procedure": procedure,
            "ca": ca,
            "urgence": urgence,
        })

    return dossiers

def main():
    print("\n" + "="*90)
    print("📊 DOSSIERS MASARE RETENUS — Rapport du 19 juin 2026")
    print("="*90 + "\n")

    dossiers = parse_rapport()

    if not dossiers:
        print("❌ Impossible de parser le rapport.")
        return

    print(f"✓ {len(dossiers)} dossiers trouvés\n")

    for i, d in enumerate(dossiers, 1):
        # Déterminer urgence et couleur
        try:
            score_num = int(d["score"].split("/")[0]) if "/" in d["score"] else 0
        except:
            score_num = 0

        if score_num >= 8:
            icon = "🔴"
            label = "ALERTE"
        elif score_num >= 6:
            icon = "🟠"
            label = "RAPPORT"
        else:
            icon = "🟡"
            label = "VEILLE"

        print(f"{i}. {icon} [{label}] {d['nom']}")
        print(f"   Score: {d['score']} | Urgence: {d['urgence']}")
        print(f"   Secteur: {d['secteur']} | Procédure: {d['procedure']}")
        print(f"   CA historique: {d['ca']}M€ | SIREN: {d['siren']}")
        print()

    # Stats
    print("\n" + "="*90)
    print("📈 STATISTIQUES")
    print("="*90)

    scores = []
    for d in dossiers:
        try:
            if "/" in d["score"]:
                scores.append(int(d["score"].split("/")[0]))
            else:
                scores.append(0)
        except:
            scores.append(0)

    alertes = len([s for s in scores if s >= 8])
    rapports = len([s for s in scores if 6 <= s < 8])

    print(f"🔴 ALERTES (score ≥ 8) : {alertes}")
    print(f"🟠 RAPPORTS (score 6-7) : {rapports}")
    print(f"🟡 VEILLE (score < 6) : {len(dossiers) - alertes - rapports}")

    # Top secteurs
    print(f"\n🎯 TOP SECTEURS:")
    sectors = {}
    for d in dossiers:
        s = d["secteur"]
        sectors[s] = sectors.get(s, 0) + 1

    for sector, count in sorted(sectors.items(), key=lambda x: -x[1]):
        print(f"   • {sector}: {count}")

    print("\n" + "="*90 + "\n")

if __name__ == "__main__":
    main()
