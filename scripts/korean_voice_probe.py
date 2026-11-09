#!/usr/bin/env python3
# Copyright (c) 2026 MekaHime Inc.
# SPDX-License-Identifier: MIT
"""Read-only Korean G2P check, run by setup_tts in a bounded voice-env child.

The guard is process-wide and irreversible. Never run this probe inside the voice
server: a disposable child keeps Korean failures separate from other languages.
This guards the pinned Python bootstrap paths, not arbitrary hostile native code.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

_DENIED: list[str] = []
_GUARDED = False


def _deny(action: str) -> None:
    _DENIED.append(action)
    raise RuntimeError(f"verification prohibited {action}")


def install_verification_guard() -> None:
    """Deny process creation, networking and filesystem mutation before imports."""
    global _GUARDED
    if _GUARDED:
        return
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event == "socket.gethostname":
            return  # Local metadata lookup; no socket is created or connected.
        if (event == "subprocess.Popen" and args[0] in (None, "lscpu") and
                (args[1] == "lscpu" or args[1] == ["lscpu"])):
            # NumPy treats this optional CPU probe as unsupported when it cannot run.
            raise FileNotFoundError("verification does not run lscpu")
        if event.startswith(("subprocess.", "socket.", "urllib.Request")) or event in {
            "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
            "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink",
            "os.truncate", "os.chmod", "os.chown", "os.utime", "shutil.copyfile",
        }:
            _deny(event)
        if event == "open":
            _, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            ):
                _deny("file write")

    sys.addaudithook(audit)
    _GUARDED = True


def prerequisites(engine: Path) -> None:
    """Check packages and local data without importing g2pk2 or text.korean.

    g2pk2 0.0.3 checks cmudict.zip at import, even if an unpacked copy exists,
    and installs eunjeon (Windows) or python-mecab-ko in its constructor.
    """
    names = ["g2pk2", "jamo", "ko_pron", "nltk", "mecab", "mecab_ko_dic"]
    specs = {name: importlib.util.find_spec(name) for name in names}
    missing = [name for name, spec in specs.items() if spec is None]
    if missing:
        raise RuntimeError("missing package(s): " + ", ".join(missing) +
                           " (mecab is provided by python-mecab-ko)")
    dictionary = Path(importlib.import_module("mecab_ko_dic").dictionary_path)
    rc = Path(next(iter(specs["mecab"].submodule_search_locations))) / "mecabrc"
    files = [dictionary / name for name in ("sys.dic", "unk.dic", "matrix.bin", "char.bin")]
    files.append(rc)
    missing_files = [str(path) for path in files if not path.is_file()]
    if missing_files:
        raise RuntimeError("missing Mecab dictionary/data: " + ", ".join(missing_files))

    nltk = importlib.import_module("nltk")
    downloader = importlib.import_module("nltk.downloader")

    def no_download(*args, **kwargs):
        _deny("NLTK download")

    nltk.download = no_download
    downloader.download = no_download
    downloader.Downloader.download = no_download
    downloader.Downloader.incr_download = no_download
    nltk.data.path.insert(0, str(engine / "nltk_data"))
    for resource in ("corpora/cmudict.zip", "corpora/cmudict/cmudict"):
        try:
            nltk.data.find(resource)
        except LookupError as exc:
            raise RuntimeError(f"missing NLTK data: {resource} in {engine / 'nltk_data'}") from exc


def install_windows_mecab() -> None:
    """Use the wheel-backed tokenizer in g2pk2 and GPT-SoVITS's Windows subclass."""
    import g2pk2
    from mecab import MeCab

    class WheelG2p(g2pk2.G2p):
        def __init__(self, *args, **kwargs):
            # Bypass both g2pk2's installer and win_G2p's eunjeon dictionary-copy workaround.
            self.check_mecab = lambda: None
            super().__init__(*args, **kwargs)

        def get_mecab(self):
            return MeCab()

    g2pk2.G2p = WheelG2p


def probe(engine: str | Path, *, windows: bool | None = None, gsv_dir: str | Path | None = None) -> dict:
    """Return {ok, detail}; success is a G2P smoke check, not audio acceptance."""
    install_verification_guard()
    engine = Path(engine)
    try:
        windows = sys.platform == "win32" if windows is None else windows
        # NLTK path validation asks for a temp root; avoid tempfile's write-based discovery.
        tempfile.tempdir = str(engine.resolve())
        prerequisites(engine)
        if windows:
            install_windows_mecab()
        gsv = Path(gsv_dir) if gsv_dir is not None else engine / "GPT-SoVITS"
        sys.path.insert(0, str(gsv / "GPT_SoVITS"))
        korean = importlib.import_module("text.korean")
        phones = korean.g2p("안녕하세요")
        if _DENIED:
            raise RuntimeError("verification prohibited " + _DENIED[0])
        if not isinstance(phones, (list, tuple)) or not phones or not all(
            isinstance(phone, str) and phone for phone in phones
        ):
            raise RuntimeError("Korean G2P returned no usable phonemes")
        return {"ok": True, "detail": "Korean G2P smoke passed (not synthesis/pronunciation acceptance)"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:1200]}


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1], gsv_dir=sys.argv[2] if len(sys.argv) > 2 else None), ensure_ascii=True))
