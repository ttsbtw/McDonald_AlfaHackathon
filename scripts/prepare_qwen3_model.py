#!/usr/bin/env python3
"""Reassemble the tracked Qwen GGUF parts, verify them, and import into Ollama."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models/qwen3-4b-instruct-2507-q4_K_M"


def main():
    manifest = json.loads((MODEL_DIR / "manifest.json").read_text())
    parts = sorted(MODEL_DIR.glob("model.gguf.part-*"))
    if len(parts) != 3:
        raise SystemExit("Ожидались 3 LFS-части модели. Установите Git LFS и выполните git lfs pull.")

    hasher = hashlib.sha256()
    total_size = 0
    with tempfile.TemporaryDirectory(prefix="qwen3-4b-") as temporary:
        temp_dir = Path(temporary)
        gguf = temp_dir / "model.gguf"
        with gguf.open("wb") as destination:
            for part in parts:
                with part.open("rb") as source:
                    first_bytes = source.read(64)
                    if first_bytes.startswith(b"version https://git-lfs.github.com/spec/v1"):
                        raise SystemExit("Вместо весов загружены LFS-указатели. Установите Git LFS и выполните git lfs pull.")
                    source.seek(0)
                    while chunk := source.read(8 * 1024 * 1024):
                        destination.write(chunk)
                        hasher.update(chunk)
                        total_size += len(chunk)

        if total_size != manifest["size_bytes"] or hasher.hexdigest() != manifest["sha256"]:
            raise SystemExit("Размер или SHA-256 модели не совпал с manifest.json; импорт отменён.")

        modelfile = temp_dir / "Modelfile"
        modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
        model_tag = os.environ.get("OLLAMA_MODEL", manifest["ollama_tag"])
        subprocess.run(["ollama", "create", model_tag, "-f", str(modelfile)], check=True)
        print(f"Готово: {model_tag}; контрольная сумма проверена.")


if __name__ == "__main__":
    main()
