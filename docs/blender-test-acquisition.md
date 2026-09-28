# Blender 5.2.2 test fixture acquisition

`scripts/acquire_blender.py {linux-x64|windows-x64} <empty-test-directory>` downloads the **official Blender 5.2.2** archive from `https://download.blender.org/release/Blender5.2/`, then tries fixed NLUUG and Clarkson mirrors if a download fails, is truncated, or fails verification. Every source must match the exact official SHA-256 and archive size before extraction; exhausted sources fail closed. The extractor rejects unsafe archive paths and refuses to overwrite an existing installation. It requires network only to fetch the archive; do not run it inside the default network-isolated test sandbox. CI may fetch to a disposable job directory, verify, then run Blender offline. The script does not install the extension, change system Blender preferences, or run downloaded code.

SHA-256 values (official [Blender 5.2.2 checksum list](https://download.blender.org/release/Blender5.2/blender-5.2.2.sha256), checked 2026-09-27):

| Platform | Archive | SHA-256 |
| --- | --- | --- |
| Linux x64 | `blender-5.2.2-linux-x64.tar.xz` | `84098912789dc450e95697c4184fb8a90acbe5111c2ba4aede3fecb57806a168` |
| Windows x64 | `blender-5.2.2-windows-x64.zip` | `3849d17a682cba006075aaa3f3597ecb5c9c30ec31035b2e092c53e40679b535` |

Start headless tests with `--background --factory-startup`. On Linux set `HOME` to a fresh temporary directory; on Windows set `APPDATA` and `LOCALAPPDATA` to fresh temporary directories. Do not mount a maintainer's Blender configuration or credentials into test isolation. These hashes pin archive bytes, not the trustworthiness of upstream Blender or of the CI runner. GUI viewport capture is not verified by a headless test.
