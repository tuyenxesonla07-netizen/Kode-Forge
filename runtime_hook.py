# PyInstaller runtime hook — auto-executed before main script
# Handles frozen-binary environment setup for cross-platform consistency
import sys
import os

if getattr(sys, 'frozen', False):
    os.environ['KODEFORGE_FROZEN'] = '1'
    # Fix encoding on Windows: force UTF-8 so ✓/✗ emoji don't crash on GBK locales
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Ensure consistent home detection on Windows runners
    if sys.platform == 'win32':
        os.environ.setdefault('USERPROFILE', os.path.expanduser('~'))
