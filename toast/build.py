# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compile generated C++ to a shared library, cached by a hash of everything that affects it.

Cache layout, in ``~/.cache/toast`` (or ``$TOAST_CACHE_DIR``), per kernel:
``<key>.so`` the kernel, ``<key>.cpp`` the generated source (for debugging), ``<key>.json`` the
signature. A cache hit skips the frontend and the compiler entirely.
"""

import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .compiler import collect_libraries, compile_source
from .errors import ToastBuildError
from .version import VERSION

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
RUNTIME_HEADER = RUNTIME_DIR / "toast_rt.h"

# No -ffast-math: noise must match Blender bit for bit. -ffp-contract=off keeps the compiler
# from fusing a*b+c into FMA, which would change rounding. -fwrapv makes int overflow wrap.
CXX_FLAGS = (
    "-std=c++17",
    "-O3",
    # Apple's clang may reject -march=native on Apple silicon; its default target is fine there.
    *(() if sys.platform == "darwin" else ("-march=native",)),
    "-fPIC",
    "-shared",
    "-fno-math-errno",
    "-ffp-contract=off",
    "-fwrapv",
    "-fvisibility=hidden",
)
COMPILERS = ("clang++", "g++")


@dataclass
class Kernel:
    key: str
    so_path: Path
    cpp_path: Path
    signature: dict
    cached: bool


def cache_dir():
    d = os.environ.get("TOAST_CACHE_DIR")
    path = Path(d) if d else Path.home() / ".cache" / "toast"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_compiler(preferred=None):
    """Return the C++ compiler path: ``preferred``, ``$TOAST_CXX``, then clang++, then g++."""
    for cand in (preferred, os.environ.get("TOAST_CXX"), *COMPILERS):
        if not cand:
            continue
        path = shutil.which(cand)
        if path:
            return path
    raise ToastBuildError(
        "no C++ compiler found: install clang++ or g++, or set TOAST_CXX to one"
    )


@functools.lru_cache(maxsize=None)
def compiler_id(cxx):
    out = subprocess.run([cxx, "--version"], capture_output=True, text=True, check=False)
    first = (out.stdout or out.stderr).splitlines()
    return f"{cxx}|{first[0] if first else 'unknown'}"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def kernel_key(source, run_over, cxx, libs=None):
    parts = {
        "source": source,
        "libs": sorted((libs or {}).items()),
        "run_over": run_over,
        "toast": VERSION,
        "runtime": _sha256(RUNTIME_HEADER.read_bytes()),
        "compiler": compiler_id(cxx),
        "flags": CXX_FLAGS,
    }
    return _sha256(json.dumps(parts, sort_keys=True).encode())[:32]


def _write_atomic(path, data, mode="w"):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, mode) as f:
        f.write(data)
    os.replace(tmp, path)


def build(source, run_over="points", cxx=None, force=False, lib_resolver=None):
    """Compile Toast ``source`` to a kernel. Raises ToastError for errors in the user's code.

    ``lib_resolver(module)`` returns the source of a ``toast_lib`` library (default: files in the
    library folders, see ``libraries.py``). Library sources are part of the cache key.
    """
    from .libraries import file_resolver

    cxx = find_compiler(cxx)
    libs = collect_libraries(source, lib_resolver or file_resolver)
    key = kernel_key(source, run_over, cxx, libs)
    d = cache_dir()
    so_path, cpp_path, sig_path = d / f"{key}.so", d / f"{key}.cpp", d / f"{key}.json"

    if not force and so_path.exists() and sig_path.exists():
        return Kernel(key, so_path, cpp_path, json.loads(sig_path.read_text()), cached=True)

    result = compile_source(source, run_over, libs)
    _write_atomic(cpp_path, result.cpp)

    fd, tmp_so = tempfile.mkstemp(dir=d, prefix=f".{key}.", suffix=".so")
    os.close(fd)
    cmd = [cxx, *CXX_FLAGS, f"-I{RUNTIME_DIR}", str(cpp_path), "-o", tmp_so]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        os.unlink(tmp_so)
        raise ToastBuildError(
            f"C++ compile failed (this is a Toast bug, not your code).\n"
            f"Source: {cpp_path}\n{proc.stderr}"
        )
    os.replace(tmp_so, so_path)
    _write_atomic(sig_path, json.dumps(result.signature, indent=1, sort_keys=True))
    return Kernel(key, so_path, cpp_path, result.signature, cached=False)


def self_contained(cpp):
    """Generated C++ with toast_rt.h inlined, so a compiler needs no include path."""
    include = '#include "toast_rt.h"'
    assert include in cpp
    # Without `#pragma once`: in a main file clang warns about it ("1 warning generated").
    runtime = RUNTIME_HEADER.read_text().replace("#pragma once\n", "", 1)
    return cpp.replace(include, runtime, 1)


def build_source(source, run_over="points", force=False, lib_resolver=None):
    """Translate Toast ``source`` for Blender's built-in compiler: writes self-contained C++ to
    the cache and returns a Kernel whose ``so_path`` is that ``.cpp`` file. The Toast node
    compiles it in memory (and caches the object). Needs no external compiler.
    """
    from .libraries import file_resolver

    libs = collect_libraries(source, lib_resolver or file_resolver)
    parts = {
        "source": source,
        "libs": sorted((libs or {}).items()),
        "run_over": run_over,
        "toast": VERSION,
        "runtime": _sha256(RUNTIME_HEADER.read_bytes()),
        "backend": "builtin",
    }
    key = _sha256(json.dumps(parts, sort_keys=True).encode())[:32]
    d = cache_dir()
    cpp_path, sig_path = d / f"{key}.cpp", d / f"{key}.json"
    if not force and cpp_path.exists() and sig_path.exists():
        return Kernel(key, cpp_path, cpp_path, json.loads(sig_path.read_text()), cached=True)
    result = compile_source(source, run_over, libs)
    _write_atomic(cpp_path, self_contained(result.cpp))
    _write_atomic(sig_path, json.dumps(result.signature, indent=1, sort_keys=True))
    return Kernel(key, cpp_path, cpp_path, result.signature, cached=False)


def build_shader_cpu(cpp, backend="builtin", cxx=None):
    """The C++ of a shader node's function for Cycles on the CPU (``ShaderSource.cpu``), cached by
    its content: a self-contained ``.cpp`` for Blender's built-in compiler, or with the external
    backend a ``.so``. Returns the path for the node's ``kernel_path``."""
    parts = {"cpu": cpp, "toast": VERSION, "runtime": _sha256(RUNTIME_HEADER.read_bytes()),
             "backend": backend}  # fmt: skip
    if backend != "builtin":
        cxx = find_compiler(cxx)
        parts["compiler"] = compiler_id(cxx)
        parts["flags"] = CXX_FLAGS
    key = "shader_" + _sha256(json.dumps(parts, sort_keys=True).encode())[:32]
    d = cache_dir()
    cpp_path = d / f"{key}.cpp"
    if backend == "builtin":
        if not cpp_path.exists():
            _write_atomic(cpp_path, self_contained(cpp))
        return cpp_path
    so_path = d / f"{key}.so"
    if so_path.exists():
        return so_path
    _write_atomic(cpp_path, cpp)
    fd, tmp_so = tempfile.mkstemp(dir=d, prefix=f".{key}.", suffix=".so")
    os.close(fd)
    cmd = [cxx, *CXX_FLAGS, f"-I{RUNTIME_DIR}", str(cpp_path), "-o", tmp_so]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        os.unlink(tmp_so)
        raise ToastBuildError(f"C++ compile failed (this is a Toast bug, not your code).\n"
                              f"Source: {cpp_path}\n{proc.stderr}")  # fmt: skip
    os.replace(tmp_so, so_path)
    return so_path
