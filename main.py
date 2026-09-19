"""AT小PP 顶层启动入口。

从项目根目录运行，保证包路径正确；PyInstaller 也以本文件为入口。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.main import main  

if __name__ == "__main__":
    sys.exit(main())     