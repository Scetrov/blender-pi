"""Install/uninstall both built archives into a disposable private test profile.

Never run against an artist's actual Blender or Pi configuration. No network,
package scripts, global installs, or persistent cleanup beyond the test profile.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(args, env, cwd=None):
    result = subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): "
                           f"{result.stdout[-1000:]} {result.stderr[-1000:]}")
    return result.stdout


def verify(archive, package, blender, npm):
    for path in (archive, package):
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or unsafe release input: " + str(path))
    if not blender.is_file() or not npm.is_file():
        raise ValueError("Missing test executables")
    with tempfile.TemporaryDirectory(prefix="blender-pi-release-install-") as directory:
        home = Path(directory)
        env = os.environ.copy()
        env.update({"HOME": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
                    "LOCALAPPDATA": str(home / "AppData" / "Local"),
                    "BLENDER_USER_CONFIG": str(home / "blender-config"),
                    "BLENDER_USER_SCRIPTS": str(home / "blender-scripts"),
                    "npm_config_cache": str(home / "npm-cache"),
                    "npm_config_offline": "true", "npm_config_ignore_scripts": "true"})
        cmd = [str(blender), "--background", "--factory-startup", "--command", "extension"]
        run([*cmd, "validate", str(archive)], env)
        run([*cmd, "install-file", "--repo", "user_default", str(archive)], env)
        installed = run([*cmd, "list"], env)
        if "blender_pi" not in installed:
            raise RuntimeError("Blender did not list the installed bridge")
        run([*cmd, "remove", "blender_pi"], env)
        if "blender_pi" in run([*cmd, "list"], env):
            raise RuntimeError("Blender bridge remained installed")
        prefix = home / "pi"
        options = ["--prefix", str(prefix), "--offline", "--ignore-scripts", "--no-package-lock",
                   "--no-audit", "--no-fund", "--legacy-peer-deps"]
        run([str(npm), "install", *options, "--no-save", str(package)], env)
        target = prefix / "node_modules" / "@scetrov" / "blender-pi"
        installed_manifest = json.loads((target / "package.json").read_text(encoding="utf-8"))
        if (installed_manifest.get("dependencies") or not (target / "bridge/LICENSE").is_file()
                or not (target / "extensions/index.ts").is_file()
                or not list((target / "skills").glob("*/SKILL.md"))):
            raise RuntimeError("npm installation is missing expected license, extension or skills")
        run([str(npm), "uninstall", *options, "@scetrov/blender-pi"], env)
        if target.exists():
            raise RuntimeError("npm package remained installed")
        return installed_manifest["version"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--platform")
    parser.add_argument("--executable")
    parser.add_argument("--npm", type=Path)
    args = parser.parse_args()
    try:
        blender = args.blender
        if blender is None:
            if not (args.fixture and args.platform and args.executable):
                raise ValueError("Specify --blender or fixture, platform and executable")
            folder = f"blender-5.2.2-{args.platform}"
            blender = args.fixture / folder / folder / args.executable
        npm = args.npm or shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise ValueError("npm executable unavailable")
        result = verify(args.archive.absolute(), args.package.absolute(),
                        Path(blender).absolute(), Path(npm).absolute())
        print(f"RELEASE_INSTALL_UNINSTALL_OK version={result}")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise SystemExit(f"Release installation failed: {error}") from None
