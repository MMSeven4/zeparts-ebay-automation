import sys
import pathlib
import os

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault(
    "DB_URL", "sqlite+aiosqlite:///./zeparts_dev.db"
)

import uvicorn

uvicorn.run(
    "src.admin.main:app",
    host="0.0.0.0",
    port=8080,
    reload=True
)
