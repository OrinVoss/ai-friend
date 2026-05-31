@echo off
echo Starting Qwen3.5 Embedding Server on port 8080...
memory\llama-bin\llama-server.exe ^
  -m memory\Qwen3.5-0.8B-Q6_K.gguf ^
  --embeddings ^
  --port 8080 ^
  -ngl 99 ^
  --ctx-size 2048 ^
  --batch-size 512 ^
  --threads 4 ^
  --host 127.0.0.1
echo Embedding server stopped.
