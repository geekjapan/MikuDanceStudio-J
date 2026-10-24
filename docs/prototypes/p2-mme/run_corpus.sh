apt-get update -qq >/dev/null; apt-get install -y -qq spirv-tools python3 >/dev/null 2>&1
spirv-val --version | head -1
SAMPLER_FIX=1 python3 /scripts/corpus.py /corpus /ray > /out/results-d3dbc.txt 2>&1
SAMPLER_FIX=1 DIRECT=1 LIST=/out/shaders-direct.tsv python3 /scripts/corpus.py /corpus /ray > /out/results-direct.txt 2>&1
python3 /scripts/corpus.py /corpus /ray > /out/results-d3dbc-nofix.txt 2>&1
