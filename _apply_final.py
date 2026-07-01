"""Single-pass atomic batch apply for R5B unused-import removals."""
import pathlib

A = []  # (description, filepath, old, new)

# 1. agents/pipeline.py — delete List from typing
A.append(('1. pipeline.py List', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline.py',
    'from typing import Any, Dict, List, Optional',
    'from typing import Any, Dict, Optional'))

# 2. agents/pipeline.py — remove Requirement
A.append(('2. pipeline.py Requirement', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline.py',
    'from agents.supervisor import CodexSupervisor, Requirement',
    'from agents.supervisor import CodexSupervisor'))

# 3. pipeline_phase1.py — remove import os
A.append(('3. pipeline_phase1.py os', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline_phase1.py',
    'import logging\nimport os\nimport threading',
    'import logging\nimport threading'))

# 4. pipeline_phase1.py — remove Tracer, PipelineMetrics import
A.append(('4. pipeline_phase1.py Tracer', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline_phase1.py',
    '        from tools.observability import Tracer, PipelineMetrics\n',
    ''))

# 5. pipeline_phase2.py — keep Optional, remove Any, Dict, List
A.append(('5. pipeline_phase2.py Optional', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline_phase2.py',
    'from typing import Any, Dict, List',
    'from typing import Optional'))

# 6. code_generation.py — remove Optional
A.append(('6. code_generation.py Optional', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/supervisor/code_generation.py',
    'from typing import Any, Dict, Optional',
    'from typing import Any, Dict'))

# 7. phase1.py — remove List
A.append(('7. phase1.py List', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/supervisor/phase1.py',
    'from typing import Any, Dict, List, Optional',
    'from typing import Any, Dict, Optional'))

# 8. phase1.py — remove ModuleTask
A.append(('8. phase1.py ModuleTask', r'D:/IDLE/Kode-Forge/project/KodeForge/agents/supervisor/phase1.py',
    'from agents.supervisor.types import Requirement, ModuleTask, CompiledPipeline',
    'from agents.supervisor.types import Requirement, CompiledPipeline'))

# 11. cli/pipeline.py — remove import sys
A.append(('11. cli/pipeline.py sys', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/cli/pipeline.py',
    'import argparse\nimport sys',
    'import argparse'))

# 12. hitl/approval_chain.py — remove import dataclasses
A.append(('12. approval_chain.py dataclasses', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/hitl/approval_chain.py',
    'import dataclasses\nfrom dataclasses import dataclass, field',
    'from dataclasses import dataclass, field'))

# 13. hitl/escalation.py — remove import dataclasses
A.append(('13. escalation.py dataclasses', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/hitl/escalation.py',
    'import asyncio\nimport dataclasses\nimport logging',
    'import asyncio\nimport logging'))

# 15. messaging/channel.py — delete Any, Callable
A.append(('15. channel.py Any,Callable', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channel.py',
    'from typing import Any, Callable, Optional',
    'from typing import Optional'))

# 16. discord_adapter.py — remove import discord inside try block
A.append(('16. discord_adapter.py discord', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channels/discord_adapter.py',
    '        try:\n            import discord\n            # discord.py',
    '        try:\n            # discord.py'))

# 17. email_adapter.py — remove import os
A.append(('17. email_adapter.py os', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channels/email_adapter.py',
    'import logging\nimport os',
    'import logging'))

# 18. config.py — remove import os
A.append(('18. config.py os', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/config.py',
    'import logging\nimport os',
    'import logging'))

# 19. multichannel_bus.py — delete Optional
A.append(('19. multichannel_bus.py Optional', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/multichannel_bus.py',
    'from typing import Any, Callable, Optional',
    'from typing import Any, Callable'))

# 20. ast_validator.py — remove import sys
A.append(('20. ast_validator.py sys', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/quality/ast_validator.py',
    'import ast\nimport sys',
    'import ast'))

# 22. memory_manager.py — delete Sequence
A.append(('22. memory_manager.py Sequence', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/memory_manager.py',
    'from typing import Any, Sequence',
    'from typing import Any'))

# 23. memory_manager.py — remove RAGConfig, Document line
A.append(('23. memory_manager.py RAGConfig,Document', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/memory_manager.py',
    '\nfrom tools.rag.rag_types import RAGConfig, Document',
    ''))

# 24. observability.py — remove import os
A.append(('24. observability.py os', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/observability.py',
    'import json\nimport logging\nimport os',
    'import json\nimport logging'))

# 25-27. rag_cognitive.py — remove json, logging, threading
A.append(('25-27. rag_cognitive.py json,logging,threading', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/rag_cognitive.py',
    'import json\nimport logging\nimport re\nimport threading',
    'import re'))

# 28. skill_manager.py — delete Sequence
A.append(('28. skill_manager.py Sequence', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/feedback/skill_manager.py',
    'from typing import Any, Sequence',
    'from typing import Any'))

# 29. rag/pipeline.py — remove import numpy as np
A.append(('29. rag/pipeline.py numpy', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/pipeline.py',
    '\nimport numpy as np',
    ''))

# 30. retriever.py — remove import warnings (NOOP if pre-existing; just try)
A.append(('30. retriever.py warnings', r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/search/retriever.py',
    'import math\nimport warnings',
    'import math'))

# Group by file, apply all replacements for each file in one read/write cycle
files = {}
for desc, fp, old, new in A:
    if fp not in files:
        files[fp] = []
    files[fp].append((desc, old, new))

success = 0
skipped = 0
for fp, replacements in files.items():
    p = pathlib.Path(fp)
    content = p.read_text(encoding='utf-8')
    orig = content
    applied_here = []
    for desc, old, new in replacements:
        if old in content:
            content = content.replace(old, new, 1)
            applied_here.append(desc)
        else:
            skipped += 1
    if content != orig:
        p.write_text(content, encoding='utf-8')
        name = fp.replace('\\', '/').split('/')[-1]
        for d in applied_here:
            print('APPLIED: ' + name + ' -- ' + d)
        success += len(applied_here)

print('\nTotal applied: ' + str(success))
print('Skipped (already done or not found): ' + str(skipped))
