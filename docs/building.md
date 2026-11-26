# Building Blender with Toast

Toast needs a Blender build from the fork
[varomix/blender](https://github.com/varomix/blender), branch `toast`: the fork adds the Toast
geometry node, the C++ node plugin loader and (on Linux) a built-in kernel compiler. This add-on
is a submodule of the fork, `toast/addon`, installed with Blender and enabled by default.

The fork builds like Blender itself, so Blender's
[build instructions](https://developer.blender.org/docs/handbook/building_blender/) apply; this
page has the short version and what is specific to Toast.

| | Linux x64 | macOS (Apple silicon) | Windows |
| --- | --- | --- | --- |
| Toast node | yes | yes | not yet |
| Built-in kernel compiler | yes | not yet: uses Xcode's `clang++` | not yet |
| C++ node plugins (Bricker) | yes | yes (new, report problems) | not yet |
| Portable package script | yes | no | no |

## macOS

You need an Apple silicon Mac (Blender 5.3 only has precompiled libraries for arm64), about
30 GB of free disk space, Xcode or the Xcode Command Line Tools, and [Homebrew](https://brew.sh).

```sh
xcode-select --install
brew install cmake git-lfs
git lfs install
```

### Clone

```sh
mkdir -p ~/blender-git && cd ~/blender-git
git clone --branch toast https://github.com/varomix/blender.git
cd blender
git submodule update --init toast/addon
make update
```

`make update` downloads Blender's precompiled libraries for macOS (several GB) and Blender's Git
LFS files. Both come from projects.blender.org: the fork's `.lfsconfig` points there, since
GitHub doesn't store LFS files for forks.

### Build

```sh
make
```

The first build takes 30 to 60 minutes. The result is `~/blender-git/build_darwin/bin/Blender.app`.
Start it from Terminal to see Toast's messages:

```sh
~/blender-git/build_darwin/bin/Blender.app/Contents/MacOS/Blender
```

### Check that it works

1. Preferences > Add-ons > Toast is enabled and says
   `Built-in compiler: not in this Blender, in use: external`. On macOS, Toast compiles kernels
   with Xcode's `clang++`, a little slower than the built-in compiler on Linux.
2. Turn on Preferences > Save & Load > **Auto Run Python Scripts**.
3. Add a Geometry Nodes modifier to a cube, then Add > Toast > Toast. In the sidebar (N) > Node >
   Toast, open **Templates** and pick "Displace with noise": the cube changes a moment later.
4. Add > Toast lists **Bricker**. If it doesn't, the plugin didn't load; Terminal says why. As a
   fallback, start Blender with `TOAST_PLUGIN_PATH=~/blender-git/build_darwin/bin/toast_plugins`.

## Linux

Install the system packages Blender needs, as in Blender's
[Linux build instructions](https://developer.blender.org/docs/handbook/building_blender/linux/)
(a compiler, CMake, Git and Git LFS), then:

```sh
mkdir -p ~/blender-git && cd ~/blender-git
git clone --branch toast https://github.com/varomix/blender.git
cd blender
git submodule update --init toast/addon
make update
make
~/blender-git/build_linux/bin/blender
```

The build includes the built-in kernel compiler (`bin/lib/libtoast_jit.so`, made from the clang
and LLVM in Blender's precompiled libraries), so Toast needs no compiler installed. Preferences >
Add-ons > Toast should say `Built-in compiler: available, in use: builtin`.

To make a portable archive (Blender, the add-on, the plugins, the guide and a settings folder of
its own), run `build_files/toast/package_portable.sh` from the fork. It writes
`../packages/blender-<version>-toast-<commit>-linux-x64.tar.xz`.

## Running the tests

The tests need Python 3 with numpy and, for the Blender tests, the fork's Blender. Without
`TOAST_BLENDER`, they look for `~/blender-git/build_linux_5.3/bin/blender` and skip the Blender
tests if it isn't there. The simplest Python to use is the one inside the Blender build, which
already has numpy (a system Python may not have numpy, or may not allow installing it):

```sh
cd ~/blender-git/blender/toast/addon
# macOS:
export TOAST_BLENDER=~/blender-git/build_darwin/bin/Blender.app/Contents/MacOS/Blender
PY=$(ls ~/blender-git/build_darwin/bin/Blender.app/Contents/Resources/*/python/bin/python3.* | head -1)
# Linux:
export TOAST_BLENDER=~/blender-git/build_linux/bin/blender
PY=$(ls ~/blender-git/build_linux/bin/*/python/bin/python3.* | head -1)

$PY -m unittest discover -s tests -v
```

These include bit-for-bit comparisons between Blender's nodes and Toast's noise and random
functions, and between the Toast node in Blender and the test harness. The Bricker plugin has its
own regression test in the fork:

```sh
$TOAST_BLENDER -b --factory-startup \
  --python ~/blender-git/blender/source/blender/nodes/geometry/nodes/toast/tests/bricker_golden.py
```

## Updating

```sh
cd ~/blender-git/blender
git pull
git submodule update toast/addon
make
```

## Working on the add-on

To edit this add-on and see changes in Blender without reinstalling, point the build at your
checkout and install it as a link instead of a copy (use `build_darwin` on macOS):

```sh
cmake -DTOAST_ADDON_DIR=/path/to/toast -DTOAST_ADDON_LINK=ON ~/blender-git/build_linux
cmake --build ~/blender-git/build_linux --target install
```

After editing `docs/guide.md`, regenerate the HTML guide with `python3 docs/build_guide.py`.

## Problems

If the build or the tests fail, open an issue on
[varomix/toast](https://github.com/varomix/toast/issues) with the output. On macOS, the parts
most likely to need fixes are the plugin loading and the bit-for-bit noise tests, since they
have not run on a Mac yet.
