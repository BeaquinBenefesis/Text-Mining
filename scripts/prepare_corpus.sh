#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -euo pipefail

# --- CONFIGURATION (DEFAULTS) ---
INPUT_FILE=""
OUTPUT_DIR="."              # Default output directory is the current folder
OUTPUT_FILENAME="sorted_output.txt"
MEM_BUFFER="10G"
NUM_CORES="5"
NUM_CHUNKS="1"               # Default: no splitting (single chunk)
CHUNK_PREFIX="chunk_"
KEEP_SORTED="false"          # Keep the intermediate sorted file when splitting

usage() {
    echo "Usage: $0 -f <input_file> [-o <output_directory>] [-n <num_chunks>] [-k]"
    echo "  -f    Specify the input file to sort (Required)"
    echo "  -o    Specify the output directory (Optional, defaults to current directory)"
    echo "  -n    Specify the number of chunks to split the sorted corpus into (Optional, defaults to 1, i.e. no splitting)"
    echo "  -k    Keep the intermediate fully-sorted file when splitting (Optional, defaults to off to save disk space)"
    exit 1
}

while getopts "f:o:n:k" opt; do
    case "$opt" in
        f) INPUT_FILE="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        n) NUM_CHUNKS="$OPTARG" ;;
        k) KEEP_SORTED="true" ;;
        *) usage ;;
    esac
done

if [ -z "$INPUT_FILE" ]; then
    echo "Error: Missing required -f option." >&2
    usage
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: Input file '$INPUT_FILE' not found." >&2
    exit 1
fi

if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Error: Output directory '$OUTPUT_DIR' does not exist." >&2
    exit 1
fi

if ! [[ "$NUM_CHUNKS" =~ ^[0-9]+$ ]] || [ "$NUM_CHUNKS" -lt 1 ]; then
    echo "Error: -n must be a positive integer (got '$NUM_CHUNKS')." >&2
    exit 1
fi

FINAL_OUTPUT="$OUTPUT_DIR/$OUTPUT_FILENAME"

echo "Sorting '$INPUT_FILE' (this can take a while for large files)..." >&2
sort -V \
     -S "$MEM_BUFFER" \
     --parallel="$NUM_CORES" \
     -o "$FINAL_OUTPUT" \
     "$INPUT_FILE"

if [ "$NUM_CHUNKS" -eq 1 ]; then
    echo "Done. Sorted output: $FINAL_OUTPUT" >&2
    exit 0
fi

# --- SPLIT INTO CHUNKS WITHOUT BREAKING ARTICLE BOUNDARIES ---
# Single pass: track bytes written per chunk (cheap, no upfront wc -l needed),
# cut to a new chunk once the target size is hit AND we're at an article boundary.
FILE_SIZE=$(stat -c %s "$FINAL_OUTPUT")
TARGET_BYTES_PER_CHUNK=$(( (FILE_SIZE + NUM_CHUNKS - 1) / NUM_CHUNKS ))

echo "Splitting into $NUM_CHUNKS chunk(s) (~$(( TARGET_BYTES_PER_CHUNK / 1024 / 1024 )) MB each, article-aligned)..." >&2

awk -v outdir="$OUTPUT_DIR" \
    -v prefix="$CHUNK_PREFIX" \
    -v target="$TARGET_BYTES_PER_CHUNK" \
    -v max_chunks="$NUM_CHUNKS" \
    '
    function article_id(sent_id) {
        n = split(sent_id, parts, ".")
        out = parts[1]
        for (i = 2; i <= n - 2; i++) {
            out = out "." parts[i]
        }
        return out
    }

    BEGIN {
        chunk_num = 1
        bytes_in_chunk = 0
        prev_article = ""
        outfile = outdir "/" prefix chunk_num ".txt"
    }

    {
        split($0, fields, "\t")
        current_article = article_id(fields[1])

        if (bytes_in_chunk >= target && current_article != prev_article && chunk_num < max_chunks) {
            close(outfile)
            chunk_num++
            bytes_in_chunk = 0
            outfile = outdir "/" prefix chunk_num ".txt"
        }

        print $0 >> outfile
        bytes_in_chunk += length($0) + 1   # +1 for the newline
        prev_article = current_article
    }

    END {
        close(outfile)
        print "Wrote " chunk_num " chunk file(s)." > "/dev/stderr"
    }
    ' "$FINAL_OUTPUT"

if [ "$KEEP_SORTED" != "true" ]; then
    rm -f "$FINAL_OUTPUT"
fi

echo "Done. Chunks written to: $OUTPUT_DIR/${CHUNK_PREFIX}*.sent" >&2