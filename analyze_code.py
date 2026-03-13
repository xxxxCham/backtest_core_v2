import ast
import os
from collections import defaultdict

stats = defaultdict(int)
for root, dirs, files in os.walk('.'):
    # Skip hidden directories and cache
    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', '.venv']]

    for file in files:
        if file.endswith('.py') and not file.startswith('.'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        stats['functions'] += 1
                    elif isinstance(node, ast.ClassDef):
                        stats['classes'] += 1
                    elif isinstance(node, ast.Import):
                        stats['imports'] += len(node.names)
                    elif isinstance(node, ast.ImportFrom):
                        stats['imports'] += len(node.names) if node.names else 1

                # Count lines
                lines = content.split('\n')
                stats['total_lines'] += len(lines)
                stats['code_lines'] += sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))

            except Exception as e:
                print(f"Error parsing {filepath}: {e}")

print(f"Fichiers analysés: {len([f for root, dirs, files in os.walk('.') for file in files if file.endswith('.py') and not file.startswith('.') and not any(d in root for d in ['__pycache__', '.venv'])])}")
print(f"Classes: {stats['classes']}")
print(f"Fonctions: {stats['functions']}")
print(f"Imports: {stats['imports']}")
print(f"Lignes totales: {stats['total_lines']:,}")
print(f"Lignes de code: {stats['code_lines']:,}")
print(f"Ratio code/comment: {stats['code_lines']/stats['total_lines']:.2%}" if stats['total_lines'] > 0 else "Ratio: N/A")