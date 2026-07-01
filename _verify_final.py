import ast, os
base = os.path.dirname(os.path.abspath(__file__))
total = 0
files_with_missing = {}
for d in ['agents', 'tools']:
    for root, dirs2, files in os.walk(os.path.join(base, d)):
        if '__pycache__' in root:
            continue
        for f in files:
            if f.endswith('.py'):
                fp = os.path.join(root, f)
                try:
                    with open(fp, 'r', encoding='utf-8') as fh:
                        source = fh.read()
                    tree = ast.parse(source)
                    m = []
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is None:
                            m.append((node.name, node.lineno))
                    if m:
                        rel = os.path.relpath(fp, base)
                        files_with_missing[rel] = m
                        total += len(m)
                except SyntaxError:
                    pass
if files_with_missing:
    for k, v in sorted(files_with_missing.items()):
        print(f'{k}: {len(v)}')
    print(f'TOTAL_MISSING = {total}')
else:
    print(f'TOTAL_MISSING = {total}')
