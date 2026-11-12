# AI Signal

Un agent de veille IA. Chaque matin, il lit les sources fiables, garde ce qui compte vraiment, vérifie les faits, publie une page web et t'envoie un email récapitulatif.

> 🚧 **En construction.** Ce README s'enrichit à chaque phase.

---

## 1. Installation sur Windows (pas à pas)

Tu n'as besoin de faire cette partie **que si tu veux lancer l'agent sur ton PC**. En production, il tournera tout seul sur GitHub Actions.

### 1.1 Récupérer le projet

Installe [Git pour Windows](https://git-scm.com/download/win) si ce n'est pas déjà fait : garde les options par défaut.

Ouvre ensuite **PowerShell** (touche Windows, tape « PowerShell », Entrée) et place-toi dans le dossier où tu ranges tes projets, par exemple :

```powershell
cd $HOME\Documents
```

```powershell
git clone https://github.com/romain4033/ai-signal.git
```

```powershell
cd ai-signal
```

### 1.2 Créer l'environnement Python

Un *environnement virtuel* est une boîte isolée qui contient les bibliothèques du projet, sans toucher au reste de ton PC.

```powershell
py -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

Si PowerShell refuse avec « l'exécution de scripts est désactivée », lance une seule fois la commande ci-dessous, puis relance l'activation :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Quand l'environnement est actif, `(.venv)` apparaît au début de la ligne. Installe ensuite les dépendances :

```powershell
pip install -e ".[dev]"
```

### 1.3 Ajouter ta clé API

```powershell
Copy-Item .env.example .env
```

```powershell
code .env
```

Dans VS Code, colle ta clé après `ANTHROPIC_API_KEY=` (sans espace ni guillemets) et enregistre. Le fichier `.env` est ignoré par git : ta clé ne partira jamais sur GitHub.

### 1.4 Vérifier que tout marche

```powershell
python -m ai_signal check-setup --ping
```

Toutes les lignes doivent afficher `[OK ]`. L'option `--ping` fait un mini appel à Claude, qui coûte moins d'un centime.

---

## 2. Créer et protéger ta clé API Anthropic

1. Va sur **platform.claude.com** et connecte-toi.
2. **Ajoute du crédit** : menu *Settings → Billing*, puis achète quelques dollars de crédit (5 à 10 $ suffisent largement pour commencer).
3. **Fixe une limite de dépense mensuelle** : dans *Settings → Limits*, mets par exemple **20 $** par mois. C'est ta ceinture de sécurité : même en cas de bug, tu ne pourras jamais dépenser plus que ça.
4. **Crée la clé** : *Settings → API keys → Create key*. Nomme-la `ai-signal`.
5. **Copie-la tout de suite.** Elle commence par `sk-ant-` et ne sera plus jamais affichée. Si tu la perds, supprime-la et crée-en une nouvelle.

⚠️ Ne colle jamais ta clé dans un message, un email ou un fichier suivi par git. Ses seuls emplacements sont ton `.env` local et les *secrets* GitHub (phase 7).

---

## 3. Commandes

| Commande | Rôle |
|---|---|
| `python -m ai_signal check-setup [--ping]` | Vérifie Python, la config et la clé API |
| `python -m ai_signal check-sources` | Teste tous les flux *(phase 2)* |
| `python -m ai_signal collect-only` | Affiche les éléments collectés *(phase 2)* |
| `python -m ai_signal run [--dry-run] [--no-email] [--date AAAA-MM-JJ]` | Exécution complète *(phase 4+)* |
| `pytest` | Lance les tests (aucun appel API, gratuit) |

---

## 4. Réglages

Tout se règle dans **`config/settings.yaml`**. Le fichier est commenté ligne par ligne : fréquence, nombre de sujets, modèles, budget, tarifs.

---

## 5. Organisation du projet

```
config/       réglages (settings.yaml) et sources (sources.yaml)
prompts/      instructions données à Claude, une par étape
src/ai_signal code Python de l'agent
templates/    modèles HTML de la page et de l'email
site/         page web générée (publiée sur GitHub Pages)
data/         historique, éditions JSON, journaux de chaque exécution
tests/        tests automatiques
```
