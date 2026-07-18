"""
MASARE — Déduplication des issues GitHub
Regroupe les issues par nom de société normalisé, garde la mieux scorée, ferme les doublons.
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


def normalise_nom(titre: str) -> str:
    """
    Extrait le nom de société depuis un titre d'issue MASARE.
    Format attendu : "ALERTE XXX — NOM SOCIÉTÉ — Score ..."
    Gère tous types de tirets (—, –, -) et espaces variables.
    """
    # Regex qui capture le 2e segment entre séparateurs (tirets de tout type)
    match = re.search(
        r'ALERTE[^—–\-]*[—–\-]+\s*(.+?)\s*[—–\-]+\s*Score',
        titre,
        re.IGNORECASE | re.UNICODE
    )
    if match:
        nom = match.group(1).strip()
    else:
        # Fallback : split sur tout type de tiret entouré d'espaces
        parties = re.split(r'\s*[—–]\s*|\s+-\s+', titre)
        nom = parties[1].strip() if len(parties) >= 2 else titre

    # Normalise : minuscules, supprime formes juridiques, retire non-alphanumériques
    nom = nom.lower()
    for forme in ["scop sa", "scop", " holding", " groupe", " group",
                   " industries", " industrie", " sas", " sa", " sarl",
                   " srl", " sci", " sca", " eurl", " sasu"]:
        nom = nom.replace(forme, "")
    nom = re.sub(r"[^a-z0-9]", "", nom).strip()
    return nom


def extraire_score(titre: str) -> float:
    match = re.search(r'Score\s+([0-9]+(?:[.,][0-9]+)?)\s*/\s*10', titre, re.IGNORECASE)
    return float(match.group(1).replace(",", ".")) if match else 0.0


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


def commenter_et_fermer(numero: int, principale: int):
    requests.post(
        f"{BASE_URL}/issues/{numero}/comments",
        headers=HEADERS,
        json={"body": f"⚠️ Issue dupliquée — fermée automatiquement. Informations consolidées sur #{principale}"},
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

    # Debug : affiche les noms normalisés
    print("\n[DEBUG] Normalisation des titres :")
    groupes = defaultdict(list)
    for issue in issues:
        cle = normalise_nom(issue["title"])
        print(f"  #{issue['number']:3d} | clé='{cle}' | {issue['title'][:70]}")
        groupes[cle].append(issue)

    doublons = {k: v for k, v in groupes.items() if len(v) > 1}
    print(f"\n[MASARE-Dedup] {len(doublons)} groupe(s) avec doublons\n")

    total_fermes = 0
    for cle, groupe in doublons.items():
        print(f"── Groupe '{cle}' ({len(groupe)} issues)")
        principale = max(groupe, key=lambda i: (extraire_score(i["title"]), i["number"]))
        print(f"   Principale : #{principale['number']} — {principale['title'][:60]}")

        # Consolider les labels
        labels = list({lbl["name"] for i in groupe for lbl in i.get("labels", [])})
        requests.patch(
            f"{BASE_URL}/issues/{principale['number']}",
            headers=HEADERS,
            json={"labels": labels},
        )

        for issue in groupe:
            if issue["number"] != principale["number"]:
                commenter_et_fermer(issue["number"], principale["number"])
                total_fermes += 1

    print(f"\n[MASARE-Dedup] Terminé — {total_fermes} issue(s) fermée(s)")


if __name__ == "__main__":
    main()
