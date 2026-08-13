"""本地 OCR 模型目录。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OCR_MODEL_DIR = PROJECT_ROOT / "models"
