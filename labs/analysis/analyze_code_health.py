#!/usr/bin/env python3
"""
Outil d'analyse de la santé du code et détection de code mort
Utilise plusieurs méthodes pour identifier les problèmes potentiels
"""
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


class CodeHealthAnalyzer:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.all_functions = set()
        self.all_classes = set()
        self.all_imports = defaultdict(set)
        self.function_calls = defaultdict(set)
        self.class_usage = defaultdict(set)
        self.file_dependencies = defaultdict(set)

    def analyze_file(self, file_path: Path) -> Dict:
        """Analyse un fichier Python pour extraire les métadonnées"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            # Collecte des informations
            functions = []
            classes = []
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
                    self.all_functions.add(f"{file_path.stem}.{node.name}")

                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                    self.all_classes.add(f"{file_path.stem}.{node.name}")

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                        self.all_imports[str(file_path)].add(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        import_name = f"{module}.{alias.name}" if module else alias.name
                        imports.append(import_name)
                        self.all_imports[str(file_path)].add(import_name)

                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.function_calls[str(file_path)].add(node.func.id)

            return {
                'functions': functions,
                'classes': classes,
                'imports': imports,
                'lines': len(content.split('\n')),
                'size_kb': file_path.stat().st_size / 1024
            }

        except Exception as e:
            print(f"⚠️ Erreur analyse {file_path}: {e}")
            return {'functions': [], 'classes': [], 'imports': [], 'lines': 0, 'size_kb': 0}

    def find_large_files(self, min_lines: int = 500) -> List[Tuple[Path, int, float]]:
        """Trouve les fichiers volumineux candidats à la refactorisation"""
        large_files = []

        for py_file in self.root_path.rglob("*.py"):
            if ".venv" in str(py_file) or "__pycache__" in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    lines = len(f.read().split('\n'))
                size_kb = py_file.stat().st_size / 1024

                if lines >= min_lines:
                    large_files.append((py_file, lines, size_kb))
            except Exception:
                continue

        return sorted(large_files, key=lambda x: x[1], reverse=True)

    def find_unused_imports(self) -> Dict[str, List[str]]:
        """Détecte les imports potentiellement inutilisés"""
        unused_imports = defaultdict(list)

        for file_path, imports in self.all_imports.items():
            file_calls = self.function_calls.get(file_path, set())

            for import_name in imports:
                # Extraction du nom de base pour la vérification
                base_name = import_name.split('.')[-1]

                # Vérification si l'import est utilisé
                if (base_name not in file_calls and
                    not any(base_name in call for call in file_calls)):
                    unused_imports[file_path].append(import_name)

        return unused_imports

    def find_complex_functions(self, min_complexity: int = 10) -> List[Tuple[str, int]]:
        """Trouve les fonctions complexes (approximation basique)"""
        complex_funcs = []

        for py_file in self.root_path.rglob("*.py"):
            if ".venv" in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Recherche approximative de complexité (nombre de if/for/while/try)
                complexity_keywords = ['if ', 'for ', 'while ', 'try:', 'except:', 'elif ']

                in_function = False
                current_function = None
                function_complexity = 0

                for line in content.split('\n'):
                    line_stripped = line.strip()

                    if line_stripped.startswith('def '):
                        if current_function and function_complexity >= min_complexity:
                            complex_funcs.append((f"{py_file.name}::{current_function}", function_complexity))

                        current_function = line_stripped.split('(')[0].replace('def ', '')
                        function_complexity = 0
                        in_function = True

                    elif in_function and any(kw in line_stripped for kw in complexity_keywords):
                        function_complexity += 1

                    elif line_stripped.startswith('def ') or line_stripped.startswith('class '):
                        if current_function and function_complexity >= min_complexity:
                            complex_funcs.append((f"{py_file.name}::{current_function}", function_complexity))
                        in_function = False
                        current_function = None
                        function_complexity = 0

            except Exception:
                continue

        return sorted(complex_funcs, key=lambda x: x[1], reverse=True)

    def find_duplicate_code(self, min_length: int = 5) -> List[Tuple[str, str, str]]:
        """Détecte les duplications de code potentielles"""
        code_blocks = defaultdict(list)

        for py_file in self.root_path.rglob("*.py"):
            if ".venv" in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    lines = f.read().split('\n')

                # Recherche de blocs de code similaires
                for i in range(len(lines) - min_length):
                    block = '\n'.join(lines[i:i+min_length])
                    block_clean = re.sub(r'\s+', ' ', block.strip())

                    if len(block_clean) > 50:  # Ignorer les petits blocs
                        code_blocks[block_clean].append((str(py_file), i+1))

            except Exception:
                continue

        duplicates = []
        for block, locations in code_blocks.items():
            if len(locations) > 1:
                for loc in locations:
                    duplicates.append((loc[0], f"Line {loc[1]}", block[:100] + "..."))

        return duplicates

    def generate_report(self):
        """Génère un rapport complet"""
        print("🏥 ANALYSE DE SANTÉ DU CODE")
        print("=" * 50)

        # 1. Fichiers volumineux
        print("\n📊 FICHIERS VOLUMINEUX (candidats refactorisation)")
        large_files = self.find_large_files(300)
        for i, (file_path, lines, size_kb) in enumerate(large_files[:10]):
            priority = "🔴 HAUTE" if lines > 1000 else "🟡 MOYENNE" if lines > 600 else "🟢 FAIBLE"
            print(f"{i+1:2d}. {file_path.name:<30} {lines:4d} lignes {size_kb:5.1f}KB {priority}")

        # 2. Analyse complexité
        print("\n🧠 FONCTIONS COMPLEXES (candidats simplification)")
        complex_funcs = self.find_complex_functions(8)
        for func, complexity in complex_funcs[:10]:
            print(f"  • {func:<50} Complexité: {complexity}")

        # 3. Imports inutilisés
        print("\n🧹 IMPORTS POTENTIELLEMENT INUTILISÉS")
        unused = self.find_unused_imports()
        files_with_unused = [(f, imports) for f, imports in unused.items() if imports]
        files_with_unused.sort(key=lambda x: len(x[1]), reverse=True)

        for file_path, imports in files_with_unused[:5]:
            file_name = Path(file_path).name
            print(f"  📁 {file_name:<30} {len(imports)} imports suspects")
            for imp in imports[:3]:
                print(f"     → {imp}")

        # 4. Duplications
        print("\n🔄 CODE DUPLIQUÉ")
        duplicates = self.find_duplicate_code(4)
        dup_groups = defaultdict(list)
        for file_path, location, code in duplicates:
            dup_groups[code].append((file_path, location))

        for i, (code, locations) in enumerate(list(dup_groups.items())[:5]):
            if len(locations) > 1:
                print(f"  🔄 Duplication #{i+1}: {len(locations)} occurrences")
                for loc in locations[:3]:
                    print(f"     → {Path(loc[0]).name} ({loc[1]})")

        # 5. Recommandations
        print("\n💡 RECOMMANDATIONS PRIORITAIRES")
        if large_files:
            top_file = large_files[0]
            print(f"  1. Refactoriser {top_file[0].name} ({top_file[1]} lignes)")
            if 'ui' in str(top_file[0]) and 'sidebar' in str(top_file[0]):
                print("     → Séparer logique métier / affichage UI")
            elif 'cli' in str(top_file[0]):
                print("     → Extraire handlers de commandes")
            elif 'agent' in str(top_file[0]):
                print("     → Séparer agents par responsabilité")

        if complex_funcs:
            print("  2. Simplifier fonctions complexes (complexité > 8)")

        if unused:
            total_unused = sum(len(imports) for imports in unused.values())
            print(f"  3. Nettoyer {total_unused} imports inutilisés")

        print(f"\n✅ Analyse terminée sur {len(list(self.root_path.rglob('*.py')))} fichiers Python")


def main():
    if len(sys.argv) > 1:
        root_path = sys.argv[1]
    else:
        root_path = "."

    analyzer = CodeHealthAnalyzer(root_path)
    analyzer.generate_report()


if __name__ == "__main__":
    main()
