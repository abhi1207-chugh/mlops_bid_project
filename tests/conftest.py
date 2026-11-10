import os
import sys

for p in ("/app/services/api", "/app/services/worker", "/app/services", "/app"):
    if p not in sys.path:
        sys.path.insert(0, p)
