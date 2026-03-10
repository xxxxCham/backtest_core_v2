# Correction Configuration GPU - Résumé

**Date**: 2026-01-06
**Objectif**: Corriger la répartition GPU pour prioriser RTX 5080 (GPU 0) sur RTX 2060 (GPU 1)

---

## 🔍 Problème Détecté

### Configuration GPU Réelle (nvidia-smi)
```
GPU 0 = RTX 5080 (16 GB VRAM)          ← GPU PRIORITAIRE
GPU 1 = RTX 2060 SUPER (8 GB VRAM)     ← GPU SECONDAIRE
GPU 2 = AMD iGPU (NON VISIBLE)         ← Pas CUDA, ignorée automatiquement
```

### Erreurs Identifiées

1. **Indices GPU inversés** dans les commentaires des scripts
   - ❌ Commentaires disaient "GPU 1 = RTX 5080" (FAUX)
   - ✅ Réalité: GPU 0 = RTX 5080

2. **Ordre de priorité inversé**
   - ❌ `CUDA_VISIBLE_DEVICES="1,0"` → RTX 2060 en premier
   - ✅ Devrait être `"0,1"` → RTX 5080 en premier

3. **Détection incorrecte du nombre de GPUs**
   - Risque de détecter 3 GPUs au lieu de 2 (si iGPU visible)

---

## ✅ Corrections Appliquées

### 1. **tests/Start-OllamaMultiGPU.ps1**
```diff
- # GPU 1 (RTX 5080) = Primaire
- # GPU 0 (RTX 2060 SUPER) = Secondaire
- $env:CUDA_VISIBLE_DEVICES = "1,0"
+ # GPU 0 (RTX 5080) = Primaire
+ # GPU 1 (RTX 2060 SUPER) = Secondaire
+ $env:CUDA_VISIBLE_DEVICES = "0,1"  # RTX 5080 en premier ✅
```

### 2. **run_streamlit_multigpu.bat**
```diff
- set CUDA_VISIBLE_DEVICES=1,0
+ set CUDA_VISIBLE_DEVICES=0,1
```

### 3. **.vscode/launch.json**
```diff
- "CUDA_VISIBLE_DEVICES": "1,0"
+ "CUDA_VISIBLE_DEVICES": "0,1"
```

### 4. **tests/configure_ollama_multigpu.py**

**a) Fonction `get_gpu_count()` - Filtrage iGPU**
```diff
def get_gpu_count():
-   """Retourne le nombre de GPUs disponibles."""
+   """Retourne le nombre de GPUs CUDA disponibles (ignore iGPU)."""
    try:
        result = subprocess.run(
-           ["nvidia-smi", "--list-gpus"],
+           ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
            ...
        )
+       # Filtrer uniquement les GPUs NVIDIA (ignore AMD iGPU)
+       lines = result.stdout.strip().split('\n')
+       cuda_gpus = [line for line in lines if line and 'NVIDIA' in line]
+       return len(cuda_gpus)
```

**b) Fonction `set_environment_variables()` - Documentation**
```diff
+ # CUDA_VISIBLE_DEVICES : tous les GPUs CUDA (0 = RTX 5080, 1 = RTX 2060)
+ # Priorité : GPU 0 (plus puissante) en premier
  gpu_ids = ",".join(str(i) for i in range(num_gpu))
```

### 5. **restart_ollama_multigpu.bat** ✅
- Déjà correct (`CUDA_VISIBLE_DEVICES=0,1`)
- Aucune modification nécessaire

---

## 🎯 Résultat Final

### Configuration GPU Correcte
```bash
CUDA_VISIBLE_DEVICES=0,1
```

**Ordre d'utilisation par Ollama** :
1. **GPU 0 (RTX 5080)** - 16 GB VRAM - Charge principale
2. **GPU 1 (RTX 2060)** - 8 GB VRAM - Charge secondaire
3. **iGPU AMD** - Ignorée (pas CUDA)

### Variables d'Environnement Multi-GPU
```bash
CUDA_VISIBLE_DEVICES=0,1      # RTX 5080 + RTX 2060
OLLAMA_NUM_GPU=2              # 2 GPUs actifs
OLLAMA_GPU_OVERHEAD=0         # Pas d'overhead
OLLAMA_MAX_LOADED_MODELS=1    # 1 modèle à la fois
OLLAMA_FLASH_ATTENTION=1      # Flash Attention activé
```

---

## 🧪 Tests Recommandés

### 1. Vérifier la configuration GPU
```bash
nvidia-smi --query-gpu=index,name,memory.total --format=csv
```

**Sortie attendue** :
```
index, name, memory.total [MiB]
0, NVIDIA GeForce RTX 5080, 16303 MiB
1, NVIDIA GeForce RTX 2060 SUPER, 8192 MiB
```

### 2. Tester Ollama Multi-GPU
```powershell
# Démarrer Ollama avec configuration corrigée
.\tests\Start-OllamaMultiGPU.ps1

# Dans un autre terminal
nvidia-smi -l 1

# Lancer un modèle 70B
ollama run llama3.3-70b-2gpu "Analyse le marché Bitcoin"
```

**Vérifier** :
- GPU 0 et GPU 1 montrent activité dans nvidia-smi
- VRAM utilisée sur les 2 GPUs
- GPU 0 a plus de charge que GPU 1 (car prioritaire)

### 3. Tester Streamlit
```batch
run_streamlit_multigpu.bat
```

Vérifier dans l'UI :
- Modèles chargés correctement
- Backtests utilisent GPU 0 en priorité
- Multi-GPU fonctionne pour gros modèles

---

## 📊 Impact Attendu

### Performances
- ✅ **GPU 0 (RTX 5080)** utilisée en priorité (16 GB > 8 GB)
- ✅ Meilleure répartition charge pour modèles 70B
- ✅ Backtests plus rapides (GPU la plus puissante en premier)

### Stabilité
- ✅ Plus de confusion sur indices GPU
- ✅ iGPU correctement ignorée
- ✅ Configuration cohérente dans tous les scripts

---

## 🔗 Fichiers Modifiés

| Fichier | Modification | Statut |
|---------|--------------|--------|
| `tests/Start-OllamaMultiGPU.ps1` | CUDA_VISIBLE_DEVICES + commentaires | ✅ Corrigé |
| `run_streamlit_multigpu.bat` | CUDA_VISIBLE_DEVICES | ✅ Corrigé |
| `.vscode/launch.json` | CUDA_VISIBLE_DEVICES | ✅ Corrigé |
| `tests/configure_ollama_multigpu.py` | Filtrage iGPU + docs | ✅ Corrigé |
| `restart_ollama_multigpu.bat` | Aucune | ✅ Déjà correct |

---

## 💡 Notes Importantes

1. **iGPU AMD** : Non visible par nvidia-smi, donc jamais utilisée par CUDA/Ollama
2. **Ordre GPU** : GPU 0 est **toujours** prioritaire dans `CUDA_VISIBLE_DEVICES`
3. **Redémarrage** : Ollama doit être redémarré pour appliquer les changements
4. **Vérification** : Utiliser `nvidia-smi` pendant inférence pour confirmer

---

**Corrections appliquées le** : 2026-01-06
**Validé par** : Claude Sonnet 4.5
