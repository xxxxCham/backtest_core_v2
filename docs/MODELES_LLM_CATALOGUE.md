# Catalogue des modèles LLM — Backtest Core v2

> Généré le 28/03/2026  
> Score **Builder** = aptitude estimée pour l'usage en mode Strategy Builder (raisonnement, génération de stratégie, feedback structuré, suivi d'itérations).  
> Échelle : de 0 % (inutilisable) à 100 % (idéal).  
> ☁️ = modèle cloud-only (consomme des crédits Ollama) · 💻 = modèle téléchargeable en local

---

## ☁️ Modèles Cloud-Only (19)

> Ces modèles ne sont **pas téléchargeables**. Chaque appel consomme des crédits Ollama.  
> Utiliser en priorité pour les tâches critiques ou les audits finaux.

| Modèle | Paramètres | Catégorie | Score Builder | Commentaire |
|--------|-----------|-----------|:-------------:|-------------|
| `deepseek-v3.2` | 671 B | Raisonnement | **98 %** | Flagship absolu DeepSeek 2025 — thinking hybride ON/OFF, structured output parfait, 1er choix pour sessions Critic & Validator |
| `kimi-k2-thinking` | N/A | Raisonnement | **95 %** | Meilleur raisonnement open-source Moonshot, thinking profond, idéal pour hypothèses complexes et diagnostics |
| `gpt-oss:120b` | 120 B | Raisonnement | **94 %** | Poids ouverts OpenAI, raisonnement + agentique, très fiable pour toutes les phases Builder |
| `qwen3-coder:480b` | 480 B | Code | **93 %** | Meilleur modèle code agentique Alibaba, génération de stratégie à haut niveau, slow mais très précis |
| `devstral-2:123b` | 123 B | Code | **91 %** | Meilleur agent code toutes tailles (Mistral), contexte 256 k, excellent pour la relecture et correction de code stratégie |
| `glm-5` | 744 B | Raisonnement | **90 %** | GLM-5 744 B MoE (40 B actifs) — raisonnement long + systèmes complexes (Z.ai), très lourd côté crédit |
| `cogito-2.1:671b` | 671 B | Raisonnement | **92 %** | Instruction tuning deep raisonnement, licence MIT, très bien sur les analyses critiques multi-étapes |
| `deepseek-v3.1` | 671 B | Raisonnement | **96 %** | Quasi-équivalent à v3.2, thinking hybride, légèrement moins rapide — excellent fallback v3.2 |
| `qwen3.5:122b` | 122 B | Général | **89 %** | Vision + tools + thinking, haut de gamme, bonne polyvalence pour Analyst + Strategist |
| `kimi-k2` | N/A | Code | **88 %** | Agent code benchmarks SOTA open-source (Moonshot), bon pour génération et debug stratégie |
| `qwen3-coder:480b` | 480 B | Code | — | *(déjà listé)* |
| `qwen3-next:80b` | 80 B | Raisonnement | **86 %** | Thinking haute efficacité, 1ère génération Qwen3-Next, bon équilibre coût/qualité cloud |
| `kimi-k2.5` | N/A | Multimodal | **85 %** | Vision + thinking + instant, utile pour lecture de graphiques ou tableaux dans un futur Builder multimodal |
| `nemotron-3-super:120b` | 120 B | Général | **84 %** | NVIDIA MoE 12 B actifs, multi-agent et tools, très efficace à l'inférence cloud, bon pour orchestration |
| `mistral-large-3` | N/A | Général | **82 %** | Flagship enterprise Mistral, vision + tools, très fiable pour tâches structurées et JSON strict |
| `minimax-m2.7` | N/A | Code | **80 %** | Code + workflows agentiques, productivité, bon complément pour phases d'exécution du Builder |
| `minimax-m2.5` | N/A | Général | **76 %** | Productivité et code SOTA, moins entraîné au raisonnement pur, acceptable pour Analyst/Validator |
| `glm-4.7` | N/A | Code | **78 %** | Coding avancé + raisonnement thinking (Z.ai), bon sur génération code mais moins connu que DeepSeek |
| `glm-4.6` | N/A | Agentique | **72 %** | Agentique + code (Z.ai), version précédente, correct pour tests rapides à faible coût crédit |

---

## 💻 Modèles Locaux (45)

> Ces modèles sont **téléchargeables sur votre machine**.  
> Ceux marqués `⚠️ >50 B` requièrent une **approbation manuelle** dans le Builder (RAM/VRAM importante).

### Modèles lourds (≥ 30 B paramètres)

| Modèle | Paramètres | Catégorie | Score Builder | Commentaire |
|--------|-----------|-----------|:-------------:|-------------|
| `deepseek-r1:671b` ⚠️ | 671 B | Raisonnement | **90 %** | Flagship local si vous avez ~380 Go disque, raisonnement niveau O3 — impraticable sans multi-GPU massif |
| `deepseek-v3:671b` ⚠️ | 671 B | Raisonnement | **88 %** | MoE 37 B actifs en pratique (~390 Go disque), très rapide à l'inférence malgré sa taille brute |
| `deepseek-r1:70b` ⚠️ | 70 B | Raisonnement | **85 %** | Maximum puissance locale raisonnant, mais très lent sur RTX 5080 seul — à utiliser sur 2 GPU |
| `qwq:32b` | 32 B | Raisonnement | **85 %** | Raisonnement profond et structuré, concurrent direct de o1-mini, excellent pour Critic |
| `qwen3-coder:30b` | 30 B | Code | **87 %** | Meilleur modèle code 30 B local, à préférer pour la phase de génération de stratégie |
| `cogito:32b` | 32 B | Raisonnement | **84 %** | Raisonnement hybride top benchmarks open-source, combinaison idéale vitesse/qualité en ≤32 B |
| `deepseek-r1:32b` | 32 B | Raisonnement | **86 %** | Excellent raisonnement 32 B, parmi les meilleurs locaux pour le Builder sur RTX 5080 |
| `qwen3:32b` | 32 B | Général | **83 %** | Thinking + tools, flagship Alibaba 2025, très polyvalent pour tous les rôles Builder |
| `qwen3.5:35b` | 36 B | Général | **82 %** | Généraliste multimodal récent, haut de gamme local, bon pour Analyst + Strategist |
| `qwen3-30b-a3b:q4_k_m` | 30.5 B | Code | **80 %** | MoE coding/reasoning Q4, efficace en mémoire, bon compromis vitesse/qualité |
| `qwen3-vl:32b` | 33.4 B | Multimodal | **80 %** | Vision + langage + thinking, unique pour lire des graphiques si usage multimodal futur |
| `qwen2.5:32b` | 32 B | Général | **78 %** | Polyvalent haute qualité génération précédente, stable et fiable |
| `deepseek-coder-33b-local` | 33.3 B | Code | **81 %** | Spécialisé code dense, excellent debugger, Q5_K_M local |
| `llama4:16x17b` ⚠️ | 109 B | Multimodal | **75 %** | Meta MoE vision, très lourd, score limité par la lenteur locale et la moins bonne tenue sur raisonnement structuré |
| `llama3.3-70b-2gpu` ⚠️ | 70 B | Général | **80 %** | Llama 3.3 70 B multi-GPU RTX 5080+2060, excellent généraliste si distribué correctement |
| `llama3.3-70b-optimized` ⚠️ | 70 B | Général | **79 %** | Variante optimisée multi-GPU, quasi-identique à `-2gpu` |
| `llama3.3:70b-instruct-q4_K_M` ⚠️ | 70 B | Général | **78 %** | Q4 instruct, légèrement inférieur en qualité vs Q5 mais plus rapide |
| `nemotron:70b` ⚠️ | 70 B | Général | **77 %** | NVIDIA Llama 3.1 finetuné ultra-helpful, bon pour Analyst et réponses structurées |

### Modèles moyens (12–30 B paramètres)

| Modèle | Paramètres | Catégorie | Score Builder | Commentaire |
|--------|-----------|-----------|:-------------:|-------------|
| `phi4-reasoning:14b` | 14 B | Raisonnement | **81 %** | Rival des 70 B sur tâches complexes (Microsoft), meilleur 14 B local pour le Critic |
| `devstral:24b` | 24 B | Code | **80 %** | Meilleur agent code open-source Mistral, contexte 128 k, 1er choix local pour génération stratégie |
| `devstral-small-2:24b` | 24 B | Code | **79 %** | Agent code local contexte 393 k, Q4_K_M, excellent pour itérations longues du Builder |
| `phi4:14b` | 14 B | Raisonnement | **80 %** | SOTA Microsoft, raisonnement + maths avancés, très bon pour Validator |
| `cogito:14b` | 14 B | Raisonnement | **76 %** | Raisonnement hybride Deep Cogito, surpasse LLaMA/Qwen de même taille |
| `deepseek-r1-distill:14b` | 14 B | Raisonnement | **79 %** | Distillation R1 14 B, raisonnement efficace, bon rapport qualité/vitesse local |
| `qwen3:14b` | 14 B | Général | **78 %** | Thinking + tools, excellent équilibre, modèle polyvalent pour tous rôles |
| `magistral:24b` | 24 B | Raisonnement | **78 %** | Thinking Mistral compact, bon pour diagnostics et propositions hypothèses |
| `qwen3.5:27b` | 27 B | Général | **77 %** | Vision + tools + thinking, haut de gamme local 27 B |
| `mistral-small3.2:24b` | 24 B | Général | **75 %** | Vision + tools + 128 k contexte, bon généraliste pour les sessions longues |
| `glm-4.7-flash-23b-local` | 29.9 B | Code | **73 %** | MoE rapide polyvalent Q3_K_M, bon débit mais qualité raisonnement limitée |
| `gemma3:27b` | 27 B | Général | **72 %** | Très bonne qualité Google, polyvalent, moins orienté raisonnement que Qwen3 |
| `lfm2:24b` | 23.8 B | Général | **68 %** | Généraliste efficace 24 GB, acceptable pour usage local modéré |
| `gpt-oss:20b` | 20 B | Général | **72 %** | Version locale GPT-OSS 20 B, polyvalent mais taille limitée |
| `mistral:22b` | 22 B | Général | **70 %** | Puissant et raisonnablement rapide, bon pour itérations rapides |
| `gemma3:12b` | 12 B | Général | **68 %** | Bon équilibre qualité/vitesse Google 12 B |

### Modèles légers (< 12 B paramètres)

| Modèle | Paramètres | Catégorie | Score Builder | Commentaire |
|--------|-----------|-----------|:-------------:|-------------|
| `qwen3:8b` | 8 B | Général | **73 %** | Dernière génération Alibaba, thinking + tools, meilleur 8 B local pour le Builder |
| `qwen3.5:9b` | 9 B | Général | **72 %** | Vision + tools + thinking multimodal, excellent pour tests rapides |
| `cogito:8b` | 8 B | Raisonnement | **70 %** | Raisonnement hybride compact, surpasse les 8 B classiques |
| `deepseek-r1-distill:8b` | 8 B | Raisonnement | **68 %** | Distillation R1, raisonnement correct pour sa taille |
| `deepseek-r1:7b` | 7 B | Raisonnement | **67 %** | Compact raisonnement, utile pour pré-analyse rapide |
| `martain7r/finance-llama-8b:q4_k_m` | 8 B | Finance | **63 %** | Spécialisé trading/finance, score général modeste mais pertinent sur les métriques financières |
| `llama3.1:8b-local` | 8 B | Général | **60 %** | Rapide, bonne qualité de base, utile pour Analyst en mode warm-up |
| `mistral:7b-instruct` | 7 B | Général | **62 %** | Très rapide, polyvalent, bon pour les tests de connectivité et les runs préliminaires |
| `deepseek-moe-16b-local` | 16.4 B | Code | **65 %** | MoE 2.8 B actifs, ultra-rapide, capable pour les phases légères |
| `phi4-mini:3.8b` | 3.8 B | Général | **58 %** | Tools + multilingual Microsoft, utile uniquement comme fallback très léger |
| `gemma3:4b` | 4 B | Général | **52 %** | Ultra-compact vision, trop limité pour le raisonnement Builder mais rapide à charger |

---

## Récapitulatif par usage Builder

| Rôle Builder | Meilleur local | Meilleur cloud |
|---|---|---|
| **Analyst** | `qwen3-coder:30b` | `deepseek-v3.2` |
| **Strategist** | `deepseek-r1:32b` | `kimi-k2-thinking` |
| **Critic** | `phi4-reasoning:14b` | `cogito-2.1:671b` |
| **Validator** | `phi4:14b` | `gpt-oss:120b` |
| **Mode autonome 24/24** | `qwen3:8b` (veille) + `devstral:24b` | `devstral-2:123b` |

---

## Notes d'utilisation

- **Crédits cloud** : privilégier `deepseek-v3.2` et `kimi-k2-thinking` pour les sessions critiques ; utiliser `glm-4.6` ou `minimax-m2.5` pour les passes de validation légères.
- **Multi-GPU (RTX 5080 + RTX 2060)** : les modèles ≥ 70 B locaux nécessitent la distribution sur les deux GPUs — utiliser `llama3.3-70b-2gpu` comme référence de configuration.
- **Approbation manuelle** : tout modèle marqué ⚠️ `>50 B` requiert une confirmation explicite dans l'interface avant chargement.
- **Finance Llama** : score général bas, mais à privilégier quand l'objectif porte sur des métriques financières (PnL, drawdown, Sharpe) — le domaine spécifique compense la taille réduite.
