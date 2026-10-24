# Qwen3-4B-Instruct-2507 · Q4_K_M

The GGUF model file is stored as three Git LFS parts (`model.gguf.part-*`). The parts concatenate to a 2,497,280,480-byte file with SHA-256 `85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9`.

Source: [Ollama qwen3:4b-instruct](https://ollama.com/library/qwen3:4b-instruct) and [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507). The upstream model is Apache-2.0; see [LICENSE](LICENSE). The Ollama model alias resolves to the same digest as the pinned Q4_K_M tag when these repository assets were prepared. `manifest.json` records the source tag, digest and checksum.

After installing Git LFS and cloning/pulling the repository, run `python3 scripts/prepare_qwen3_model.py`. It verifies each LFS object by rebuilding the GGUF in a temporary directory, then imports it into the local Ollama model store under the configured tag. It removes the temporary assembled GGUF after import.
