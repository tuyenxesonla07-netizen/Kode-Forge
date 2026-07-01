import ast
import pathlib

files = [
    r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline_phase1.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/agents/pipeline_phase2.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/agents/supervisor/code_generation.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/agents/supervisor/phase1.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/cli/pipeline.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/hitl/approval_chain.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/hitl/escalation.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/llm/plugin.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channel.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channels/discord_adapter.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/channels/email_adapter.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/config.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/messaging/multichannel_bus.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/quality/ast_validator.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/api.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/memory_manager.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/observability.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/cognitive/rag_cognitive.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/feedback/skill_manager.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/pipeline.py',
    r'D:/IDLE/Kode-Forge/project/KodeForge/tools/rag/search/retriever.py',
]

failed = 0
for f in files:
    try:
        ast.parse(pathlib.Path(f).read_text(encoding='utf-8'))
        name = f.replace('\\', '/').split('/')[-1]
        print('OK: ' + name)
    except SyntaxError as e:
        name = f.replace('\\', '/').split('/')[-1]
        print('FAIL: ' + name + ': ' + str(e))
        failed += 1

print('\n' + str(failed) + ' syntax errors')
