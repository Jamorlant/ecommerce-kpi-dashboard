"""``python -m ecommerce_kpi`` 的入口，返回标准退出码。"""

from __future__ import annotations

import sys

from ecommerce_kpi.cli import main

if __name__ == "__main__":
    sys.exit(main())
