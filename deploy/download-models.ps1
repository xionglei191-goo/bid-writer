$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
docker compose run --rm embedding python -c "from sentence_transformers import SentenceTransformer; from FlagEmbedding import FlagReranker; SentenceTransformer('BAAI/bge-m3'); FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=False); print('models ready')"
