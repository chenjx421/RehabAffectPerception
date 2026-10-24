"""Switch only the tested model ID in the private environment file."""
import os
from pathlib import Path


path = Path("/etc/rehabaffect/observations.env")
if os.geteuid() != 0 or path.is_symlink():
    raise RuntimeError("Root-owned private configuration required")
lines = path.read_text().splitlines()
matches = [index for index, line in enumerate(lines) if line.startswith("REHAB_OBSERVATION_MODEL=")]
if len(matches) != 1 or lines[matches[0]] != "REHAB_OBSERVATION_MODEL=qwen3.8-max":
    raise RuntimeError("Unexpected current model")
backup = path.with_name("observations.env.before-flash")
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "wb") as handle:
    handle.write(path.read_bytes())
    handle.flush()
    os.fsync(handle.fileno())
lines[matches[0]] = "REHAB_OBSERVATION_MODEL=glm-5.3-flash"
temporary = path.with_name("observations.env.switch")
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as handle:
    handle.write("\n".join(lines) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
temporary.replace(path)
print("Tested model selected; credentials and sample authorization preserved.")
