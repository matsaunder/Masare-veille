#!/usr/bin/env python3
"""
Nettoyage des doublons GitHub — Fusionne issues dupliquées
Détecte par SIREN et fusionne les plus anciennes dans la plus récente
"""

import json
import urllib.request
import os
from collections import defaultdict

OWNER = "matsaunder"
REPO = "masare-veille"

def get_all_issues(token: str, state="all"):
    """Récupère toutes les issues GitHub."""
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues?state={state}&per_page=100"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MASARE-Cleanup",
    }

    issues = []
    page = 1

    while True:
        try:
            req = urllib.request.Request(
                f"{url}&page={page}",
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                batch = json.loads(response.read().decode())
                if not batch:
                    break
                issues.extend(batch)
                page += 1
        except Exception as e:
            print(f"⚠️  Erreur fetch issues: {e}")
            break

    return issues

def extract_siren(issue_body: str) -> str:
    """Extrait SIREN du body de l'issue."""
    if not issue_body:
        return None

    lines = issue_body.split("\n")
    for line in lines:
        if "SIREN" in line and ":" in line:
            # Format: "**SIREN** : 412 897 563"
            parts = line.split(":")
            if len(parts) > 1:
                siren = parts[1].strip().replace(" ", "")
                if siren.isdigit() and len(siren) == 9:
                    return siren

    return None

def close_issue(issue_num: int, reason: str, token: str) -> bool:
    """Ferme une issue GitHub."""
    payload = {
        "state": "closed",
        "state_reason": "not_planned",
    }

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{issue_num}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MASARE-Cleanup",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="PATCH"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"✓ Issue #{issue_num} fermée — {reason}")
            return True
    except Exception as e:
        print(f"⚠️  Erreur fermeture: {e}")
        return False

def main():
    TOKEN = os.environ.get("GITHUB_TOKEN", "")
    if not TOKEN:
        print("❌ GITHUB_TOKEN non défini")
        return

    print("📋 Nettoyage doublons GitHub MASARE")
    print("="*60)
    print()

    print("🔍 Récupération des issues...")
    issues = get_all_issues(TOKEN, state="all")
    print(f"✓ {len(issues)} issues trouvées\n")

    # Grouper par SIREN
    by_siren = defaultdict(list)
    no_siren = []

    for issue in issues:
        if issue.get("pull_request"):  # Ignorer les PRs
            continue

        siren = extract_siren(issue.get("body", ""))
        if siren:
            by_siren[siren].append(issue)
        else:
            no_siren.append(issue)

    print(f"📊 Analyse:")
    print(f"   • Issues avec SIREN : {sum(len(v) for v in by_siren.values())}")
    print(f"   • Issues sans SIREN : {len(no_siren)}")
    print()

    # Détecter doublons
    duplicates = {k: v for k, v in by_siren.items() if len(v) > 1}

    if not duplicates:
        print("✅ Aucun doublon détecté !")
        return

    print(f"🔴 {len(duplicates)} groupe(s) de doublons détecté(s)")
    print()

    # Afficher et fusionner
    for siren, issues_group in sorted(duplicates.items()):
        print(f"Entreprise SIREN {siren} — {len(issues_group)} issues :")

        # Trier par date (plus ancien d'abord)
        issues_sorted = sorted(issues_group, key=lambda x: x["created_at"])

        # Garder la plus récente, fermer les autres
        master_issue = issues_sorted[-1]
        duplicates_to_close = issues_sorted[:-1]

        for issue in duplicates_to_close:
            print(f"   └─ Fermer #{issue['number']} (créée {issue['created_at'][:10]})")

        print(f"   ✓ Garder #{master_issue['number']} (plus récente — {master_issue['created_at'][:10]})")
        print()

        # Auto-close duplicates (no interactive prompt)
        for issue in duplicates_to_close:
            close_issue(
                issue["number"],
                f"Doublon fusionné avec issue #{master_issue['number']}",
                TOKEN
            )
        print()

    print("="*60)
    print("✅ Nettoyage terminé")

if __name__ == "__main__":
    main()
