"""
MASARE — Déduplication et nettoyage des issues GitHub
Étapes :
  1. Fermer les issues auto-générées score < SCORE_MIN
  2. Fermer les issues auto-générées "Non classifié" (résidus ancien scoring)
  3. Dédupliquer les issues restantes par nom normalisé
"""

import os
import re
import requests
from collections import defaultdict

REPO = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
BASE_URL = f"https://api.github.com/repos/{REPO}"

SCORE_MIN = 8  # Doit correspondre au seuil dans bodacc.py
MARQUEUR_AUTO = "Généré automatiquement par MASARE-Veille"


def normalise_nom(titre: str) -> str:
    match = re.search(
        r'ALERTE[^—–\-]*[—–\-]+\s*(.+?)\s*[—–\-]+\s*Score',
        titre,
        re.IGNORECASE | re.UNICODE
    )
    if match:
        nom = match.group(1).strip()
    else:
        parties = re.split(r'\s*[—–]\s*|\s+-\s+', titre)
        nom = parties[1].strip() if len(parties) >= 2 else titre

    nom = nom.lower()
    for forme in ["scop sa", "scop", " holding", " groupe", " group",
                  " industries", " industrie", " sas", " sa", " sarl",
                  " srl", " sci", " sca", " eurl", " sasu"]:
        nom = nom.replace(forme, "")
    return re.sub(r"[^a-z0-9]", "", nom).strip()


def extraire_score(titre: str) -> float:
    match = re.search(r'Score\s+([0-9]+(?:[.,][0-9]+)?)\s*/\s*10', titre, re.IGNORECASE)
    return float(match.group(1).replace(",", ".")) if match else 0.0


def est_auto_generee(issue: dict) -> bool:
    """Retourne True si l'issue a été créée automatiquement par MASARE-Veille."""
    body = issue.get("body", "") or ""
    return MARQUEUR_AUTO in body


def est_non_classifiee(titre: str) -> bool:
    return "non classif" in titre.lower()


def get_all_open_issues() -> list:
    issues, page = [], 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/issues",
            headers=HEADERS,
            params={"state": "open", "per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = [i for i in resp.json() if "pull_request" not in i]
        if not batch:
            break
        issues.extend(batch)
        page += 1
    return issues


def fermer_issue(numero: int, raison: str):
    requests.post(
        f"{BASE_URL}/issues/{numero}/comments",
        headers=HEADERS,
        json={"body": f"⚠️ Issue fermée automatiquement — {raison}"},
    )
    resp = requests.patch(
        f"{BASE_URL}/issues/{numero}",
        headers=HEADERS,
        json={"state": "closed", "state_reason": "not_planned"},
    )
    statut = "✓ fermée" if resp.ok else f"✗ erreur {resp.status_code}"
    print(f"    Issue #{numero} → {statut}")


def main():
    if not TOKEN:
        print("[ERREUR] GITHUB_TOKEN non défini.")
        return

    print(f"[MASARE-Dedup] Chargement des issues sur {REPO}...")
    issues = get_all_open_issues()
    print(f"[MASARE-Dedup] {len(issues)} issue(s) ouverte(s)")

    total_fermes = 0

    # ── ÉTAPE 1 : Fermer les issues auto-générées sous le seuil de score ───────
    print(f"\n── Étape 1 : Fermeture des issues auto-générées score < {SCORE_MIN}")
    issues_valides = []
    for issue in issues:
        if not est_auto_generee(issue):
            issues_valides.append(issue)
            continue
        score = extraire_score(issue["title"])
        if score > 0 and score < SCORE_MIN:
            print(f"  Score {score}/10 — #{issue['number']} {issue['title'][:60]}")
            fermer_issue(issue["number"], f"score {score}/10 sous le seuil {SCORE_MIN}/10")
            total_fermes += 1
        else:
            issues_valides.append(issue)

    print(f"  → {total_fermes} issue(s) fermée(s) pour score insuffisant")

    # ── ÉTAPE 2 : Fermer les issues auto-générées "Non classifié" ───────────────
    print(f"\n── Étape 2 : Fermeture des issues auto-générées 'Non classifié'")
    n_non_classif = 0
    issues_apres_etape2 = []
    for issue in issues_valides:
        if est_auto_generee(issue) and est_non_classifiee(issue["title"]):
            print(f"  Non classifié — #{issue['number']} {issue['title'][:60]}")
            fermer_issue(issue["number"], "secteur non classifié — résidu ancien scoring")
            total_fermes += 1
            n_non_classif += 1
        else:
            issues_apres_etape2.append(issue)

    print(f"  → {n_non_classif} issue(s) 'Non classifié' fermée(s)")

    # ── ÉTAPE 3 : Dédupliquer les issues restantes ────────────────────────────
    print(f"\n── Étape 3 : Déduplication ({len(issues_apres_etape2)} issues restantes)")
    groupes = defaultdict(list)
    for issue in issues_apres_etape2:
        cle = normalise_nom(issue["title"])
        groupes[cle].append(issue)

    doublons = {k: v for k, v in groupes.items() if len(v) > 1}
    print(f"  {len(doublons)} groupe(s) avec doublons")

    for cle, groupe in doublons.items():
        print(f"\n  Groupe '{cle}' ({len(groupe)} issues)")
        principale = max(groupe, key=lambda i: (extraire_score(i["title"]), i["number"]))
        print(f"  Principale : #{principale['number']} — {principale['title'][:60]}")

        labels = list({lbl["name"] for i in groupe for lbl in i.get("labels", [])})
        requests.patch(f"{BASE_URL}/issues/{principale['number']}", headers=HEADERS, json={"labels": labels})

        for issue in groupe:
            if issue["number"] != principale["number"]:
                fermer_issue(issue["number"], f"doublon de #{principale['number']}")
                total_fermes += 1

    print(f"\n[MASARE-Dedup] Terminé — {total_fermes} issue(s) fermée(s) au total")


if __name__ == "__main__":
    main()
