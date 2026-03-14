import json
import time
from datetime import datetime
from pathlib import Path

progress_file = Path.home() / "Documents" / "dam" / "ingest_status.json"


def update(status, cur, tot):
    with open(progress_file, "w") as f:
        json.dump({"status": status, "current": cur, "total": tot, "timestamp": datetime.now().isoformat()}, f)


update("scanning", 0, 0)
time.sleep(2)
for i in range(1, 11):
    update("copying", i, 10)
    time.sleep(1)
update("idle", 0, 0)
print("done")
