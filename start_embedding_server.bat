@echo off
rem H-04: port is passed by caller (embedding_endpoint) as %1, default 8080.
rem Previously hardcoded 8080 - app connected to 18080 and never reached it.
set PORT=%1
if "%PORT%"=="" set PORT=8080
echo Starting Qwen3.5 Embedding Server on port %PORT%...
memory\llama-bin\llama-server.exe ^
  -m memory\Qwen3.5-0.8B-Q6_K.gguf ^
  --embeddings ^
  --pooling mean ^
  --port %PORT% ^
  -ngl 99 ^
  --ctx-size 2048 ^
  --batch-size 512 ^
  --threads 4 ^
  --host 127.0.0.1
echo Embedding server stopped.
