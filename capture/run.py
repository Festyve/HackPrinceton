"""Run fresh disposable containers and export three tiny evidence bundles.

Requires an already cached python:3.13-slim. Never pulls an image. Run from the
repository's Python environment so the existing ALIBI importer validates output.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from alibi.capture.manifest import COLLECTOR, LOCAL, package_capture

BASE_IMAGE = "python:3.13-slim"
MODES = ("complete", "missing-local-record", "benign-gap")
HERE = Path(__file__).resolve().parent


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "output")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output already exists; choose a fresh directory")
    try:
        run("docker", "info", "--format", "{{.ServerVersion}}")
        base = json.loads(run("docker", "image", "inspect", BASE_IMAGE))[0]
    except subprocess.CalledProcessError:
        parser.exit(2, f"Docker must be running with {BASE_IMAGE} cached. Any image download requires approval.\n")
    project = "alibi-capture-" + uuid.uuid4().hex[:10]
    compose = ("docker", "compose", "-p", project, "-f", str(HERE / "compose.yaml"))
    run(*compose, "build", "--pull=false")
    image = json.loads(run("docker", "image", "inspect", "alibi-capture:local"))[0]
    identities = {"service": image["Id"], "collector": image["Id"], "base": base["Id"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after all three runs finish and validate. A failed run leaves
    # neither a partial final bundle nor a half-written manifest.
    staging = Path(tempfile.mkdtemp(prefix=".capture-", dir=output.parent))
    try:
        private = staging / "private"
        private.mkdir(mode=0o700)
        for index, mode in enumerate(MODES, 1):
            bundle = staging / "evidence" / mode
            bundle.mkdir(parents=True)
            try:
                run(*compose, "up", "-d", "--no-build", "--pull", "never", "--wait")
                run(*compose, "exec", "-T", "service", "python", "/app/runtime.py",
                    "exercise", "--mode", mode)
                for service, artifact in (("service", LOCAL), ("collector", COLLECTOR)):
                    destination = bundle / artifact
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    # Docker's archive/cp API cannot see this tmpfs on some hosts.
                    # Binary stdout from exec preserves the original bytes.
                    destination.write_bytes(subprocess.check_output([
                        *compose, "exec", "-T", service, "cat", f"/data/evidence/{artifact}"]))
                control_path = private / f"{mode}.json"
                control_path.write_bytes(subprocess.check_output([
                    *compose, "exec", "-T", "service", "cat", "/data/control.json"]))
                control_path.chmod(0o600)
                control = json.loads(control_path.read_text())
                package_capture(bundle, f"capture-{index:03}", control, identities)
            finally:
                run(*compose, "down", "--volumes")
        (private / "provenance.json").write_text(json.dumps({
            "images": identities, "base_repo_digests": base.get("RepoDigests", []),
            "docker_version": run("docker", "version", "--format", "{{.Server.Version}}"),
            "compose_version": run("docker", "compose", "version", "--short"),
        }, indent=2) + "\n")
        os.rename(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(output)


if __name__ == "__main__":
    main()
