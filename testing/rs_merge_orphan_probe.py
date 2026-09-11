"""Compatibility CLI/import alias for the production native orphan recorder."""
import sys
from modules import orphan_import_probe as _implementation

if __name__ == '__main__':
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
