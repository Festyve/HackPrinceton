"""Package original container bytes using ALIBI's existing import contract."""
import json
from datetime import datetime
from pathlib import Path

from alibi.importing import load_capture, write_capture_manifest

LOCAL = "records/var/log/records-app/access.log"
COLLECTOR = "collector/collected/collected.log"


def package_capture(directory: Path, capture_id: str, control: dict, image: dict, *, origin="DOCKER"):
    """Write only operational metadata into the public manifest and validate it.

    The caller keeps `control` outside `directory`. SIM is used by local unit
    tests, while the Docker runner supplies observed container image identity.
    """
    start = datetime.fromisoformat(control["capture_start"])
    end = datetime.fromisoformat(control["capture_end"])
    per_artifact = {
        LOCAL: {"coverage_start": start.isoformat(), "coverage_end": end.isoformat(),
                "known_gaps": control["known_gaps"], "forwarded_to_collector": True},
        COLLECTOR: {"coverage_start": start.isoformat(), "coverage_end": end.isoformat()},
    }
    manifest_path = write_capture_manifest(
        directory, capture_id, "alibi-docker-capture", origin, start, end,
        per_artifact=per_artifact,
        operational_context={"logging_policy": {"forwarded_files": [
            {"host": "records", "file": "/var/log/records-app/access.log"}]}},
        notes=["Synthetic requests to a controlled test application. Collector acknowledges durable receipt."],
    )
    doc = json.loads(manifest_path.read_text())
    doc["captured_by"].update(version="1", image_digests=image)
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n")
    load_capture(directory)
    return manifest_path
