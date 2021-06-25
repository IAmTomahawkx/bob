import subprocess
import sys
import os
import pathlib

release = True

deps = {"lex": "arg_lex", "safe_regex": "safe_regex"}

args = ["cargo", "build"]
if release:
    args.append("--release")

for dep, lib in deps.items():
    print(f"============================\nStarting build of {dep}\n============================")
    p = pathlib.Path("deps", dep)
    # if "target" in os.listdir(p):
    #    os.rmdir(pathlib.Path(p, "target"))

    subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr, cwd=p.absolute())
    if "target" not in os.listdir(p):
        raise RuntimeError(f"Failed to build {dep}")

    target = pathlib.Path(p, "target", "release" if release else "debug")
    to = pathlib.Path("deps")

    if sys.platform == "win32":
        target = pathlib.Path(target, f"{lib}.dll")
        to = pathlib.Path(to, lib + ".pyd")
    elif sys.platform == "darwin":
        target = pathlib.Path(target, f"lib{lib}.dylib")
        to = pathlib.Path(to, lib + ".so")
    else:
        target = pathlib.Path(target, f"lib{lib}.so")
        to = pathlib.Path(to, lib + ".so")

    print(f"moving {target} to {to}")

    if to.exists():
        os.remove(to)

    target.rename(to)
