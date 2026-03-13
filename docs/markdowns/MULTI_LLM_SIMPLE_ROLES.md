# Roles du mode multi-LLM simple

Date: 2026-03-10
Workspace: `D:\backtest_core_v2`

## Resume

Le mode multi-LLM simple du Builder autonome repose sur 4 roles LLM specialises:

1. `idea_llm`
2. `builder_llm`
3. `critic_llm`
4. `risk_llm`
Pipeline reel:

`idea_llm -> builder_llm -> critic_llm + risk_llm -> routeur deterministe local`

## Validation runtime observee le 2026-03-10

Commande executee:

```powershell
python -m cli multi-llm --profile 24GB_balanced --json validate
```

Hote valide:

- `http://127.0.0.1:11434`
- `missing_roles = []`

Resolution observee:

| Role | Modele resolu | Etat |
|------|---------------|------|
| `idea_llm` | `qwen2.5:32b` | disponible et visible sur l'hote |
| `builder_llm` | `qwen3-coder:30b` | disponible et visible sur l'hote |
| `critic_llm` | `deepseek-r1-distill:14b` | disponible et visible sur l'hote |
| `risk_llm` | `martain7r/finance-llama-8b:q4_k_m` | disponible et visible sur l'hote |
Important:

- "visible sur l'hote" signifie que le modele est expose par l'instance Ollama active.
- Cela ne veut pas dire que les 4 modeles restent charges en VRAM en permanence en meme temps.

## Role par role

### `idea_llm`

Fonction:

- Genere un objectif de strategie testable.
- Structure le cadrage initial avec objectif, rationale, contraintes et famille de strategie.

Ne fait pas:

- pas de code
- pas de backtest
- pas de decision finale de boucle

Entrees:

- univers symboles/timeframes
- indicateurs disponibles
- historique recent

Sortie:

- JSON avec `objective`, `rationale`, `constraints`, `strategy_family`

## `builder_llm`

Fonction:

- C'est le modele principal du Strategy Builder.
- Il ecrit ou ajuste le code, les parametres et la logique de strategie via le Builder existant.

Ne fait pas:

- il ne tranche pas seul l'acceptation finale de la boucle autonome

Entree:

- objectif final produit par `idea_llm` ou fallback

Sortie:

- session Builder complete avec iterations, code genere, backtests et resume

## `critic_llm`

Fonction:

- Critique le resultat du Builder.
- Cherche overfitting, manque de robustesse, faiblesse des signaux et angles morts methodologiques.

Entree:

- resume deterministic de la session Builder
- objectif initial

Sortie:

- JSON avec `verdict`, `critique`, `next_focus`

## `risk_llm`

Fonction:

- Evalue surtout le risque de trading.
- Se concentre sur drawdown, fragilite, nombre de trades, expectancy instable et mitigations.

Entree:

- meme resume deterministic que `critic_llm`

Sortie:

- JSON avec `risk_level`, `key_risks`, `mitigations`

## Decision de boucle

Fonction:

- Ce n'est plus un LLM actif en mode simple.
- Le moteur local lit les metriques de session, la critique et l'analyse risque.
- Puis il choisit l'action suivante:
  - `accept`
  - `iterate`
  - `recover`

Ne fait pas:

- il ne charge pas un cinquieme modele
- il ne choisit pas le token/timeframe
- il ne remplace pas `builder_llm`
- il ne route pas les GPU/endpoints du mode multi-GPU

Pourquoi ce role existe:

- separer la generation de strategie de la decision de poursuivre ou non la boucle
- eviter de charger un LLM supplementaire sur le meme endpoint en mode simple

## Ou modifier les attributions

Dans l'UI:

`Strategy Builder -> mode autonome -> Mode multi-LLM -> Inventaire et roles multi-LLM`

Chaque role actif peut maintenant recevoir un override explicite:

- laisser vide = le profil decide
- choisir un modele = override runtime pour ce role

## Fichiers de reference

- `core/llm_multi/config/default_profiles.json`
- `core/llm_multi/registry.py`
- `core/llm_multi/session_manager.py`
- `core/llm_multi/prompt_templates.py`
- `ui/exec_tabs.py`
- `ui/builder_view.py`

## Conclusion rapide

- `idea_llm` imagine
- `builder_llm` construit
- `critic_llm` critique
- `risk_llm` securise
- la suite de boucle est tranchee localement

Le role le plus "meta" n'est donc plus un LLM en mode simple: la decision `accept/iterate/recover` est prise localement apres evaluation.
