"""
MASARE — Déduplication des issues GitHub
Script one-shot : consolide les issues dupliquées par société (même SIREN ou même nom normalisé)
Garde l'issue la plus récente / la mieux scorée, ferme les autres avec un commentaire de redirection.

Usage :
    GITHUB_TOKEN=xxx python scripts/deduplicate_issues.py

Variables d'environnement :
    GITHUB_TOKEN  : token GitHub avec accès repo (issues read/write)
    GITHUB_REPO   : ex. "matsaunder/Masare-veille" (défaut ci-dessous)
"""

import os
import re
import requests
from collections import defaultdict

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

REPO = os.environ.get("GITHUB_REPO", "matsaunder/Masare-veille")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
BASE_URL = f"https://api.github.com/repos/{REPO}"

# ---------------------------------------------------------------------------
# UTILITAIRES
# ---------------------------------------------------------------------------

def normalise_nom(titre: str) -> str:
    """Extrait et normalise le nom de société depuis le titre d'une issue."""
    # Titre format : "ALERTE URGENT — NOM SOCIÉTÉ — Score X/10 — ..."
    parties = titre.split("—")
    if len(parties) >= 2:
        nom = parties[1].strip()
    else:
        nom = titre
    # Normalise : minuscules, sans accents courants, sans forme juridique
    nom = nom.lower()
    for forme in ["scop sa", "scop", " sas", " sa ", " sas ", " sarl", " srl", " sca", " sci",
                   " holding", " groupe", " group", " industries", " industrie"]:
        nom = nom.replace(forme, "")
    # Retire espaces multiples et ponctuation
    nom = re.sub(r"[^a-z0-9]", "", nom)
    return nom.strip()


def extraire_score(titre: str) -> float:
    """Extrait le score numérique depuis le titre d'une issue."""
    match = re.search(r"Score\s+([0-9]+(?:[.,][0-9]+)?)/10", titre, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", "."))
    return 0.0


def get_all_open_issues() -> list:
    """Récupère toutes les issues ouvertes du repo (paginées)."""
    issues = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/issues",
            headers=HEADERS,
            params={"state": "open", "per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        # Exclure les pull requests (l'API les inclut)
        issues.extend([i for i in batch if "pull_request" not in i])
        page += 1
    return issues


def commenter_et_fermer(issue_number: int, issue_principale: int):
    """Ajoute un commentaire de redirection et ferme l'issue dupliquée."""
    # Commentaire
    requests.post(
        f"{BASE_URL}/issues/{issue_number}/comments",
        headers=HEADERS,
        json={"body": f"⚠️ **Issue dupliquée — fermée automatiquement par MASARE-Veille.**\n\nInformations consolidées sur l'issue principale : #{issue_principale}"},
    )
    # Fermeture
    requests.patch(
        f"{BASE_URL}/issues/{issue_number}",
        headers=HEADERS,
        json={"state": "closed", "state_reason": "not_planned"},
    )
    print(f"  ✓ Issue #{issue_number} fermée → redirigée vers #{issue_principale}")


def consolider_labels(issues: list) -> list:
    """Fusionne tous les labels uniques de toutes les issues dupliquées."""
    labels_set = set()
    for issue in issues:
        for label in issue.get("labels", []):
            labels_set.add(label["name"])
    return list(labels_set)


def mettre_a_jour_issue_principale(issue: dict, tous_labels: list):
    """Met à jour l'issue principale avec les labels consolidés."""
    requests.patch(
        f"{BASE_URL}/issues/{issue['number']}",
        headers=HEADERS,
        json={"labels": tous_labels},
    )


# ---------------------------------------------------------------------------
# LOGIQUE PRINCIPALE
# ---------------------------------------------------------------------------

def main():
    if not TOKEN:
        print("[ERREUR] Variable GITHUB_TOKEN non définie.")
        return

    print(f"[MASARE-Dedup] Chargement des issues ouvertes sur {REPO}...")
    issues = get_all_open_issues()
    print(f"[MASARE-Dedup] {len(issues)} issue(s) ouverte(s) trouvée(s)")

    # Grouper par nom normalisé
    groupes = defaultdict(list)
    for issue in issues:
        cle = normalise_nom(issue["title"])
        groupes[cle].append(issue)

    doublons_trouves = {k: v for k, v in groupes.items() if len(v) > 1}
    print(f"[MASARE-Dedup] {len(doublons_trouves)} groupe(s) avec doublons détecté(s)")

    if not doublons_trouves:
        print("[MASARE-Dedup] Aucun doublon à traiter. Pipeline propre.")
        return

    total_fermes = 0

    for cle, groupe in doublons_trouves.items():
        print(f"\n── Groupe '{cle}' : {len(groupe)} issues")
        for i in groupe:
            print(f"   #{i['number']} — score {extraire_score(i['title'])} — {i['title'][:80]}")

        # Sélectionner l'issue principale : score le plus élevé, puis la plus récente
        principale = max(groupe, key=lambda i: (extraire_score(i["title"]), i["number"]))
        print(f"   → Issue principale retenue : #{principale['number']}")

        # Consolider les labels
        tous_labels = consolider_labels(groupe)
        mettre_a_jour_issue_principale(principale, tous_labels)
        print(f"   → Labels consolidés : {tous_labels}")

        # Fermer les doublons
        for issue in groupe:
            if issue["number"] != principale["number"]:
                commenter_et_fermer(issue["number"], principale["number"])
                total_fermes += 1

    print(f"\n[MASARE-Dedup] Terminé — {total_fermes} issue(s) dupliquée(s) fermée(s)")


if __name__ == "__main__":
    main()
