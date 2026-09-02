#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -euo pipefail

# --- CONFIGURATION (DEFAULTS) ---
INPUT_FILE=""
OUTPUT_DIR="."              # Default output directory is the current folder
OUTPUT_FILENAME="sorted_output.sent"
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
# Sort on the same (article_id, section_num, sentence_num) fields, with the
# same string/numeric split, that hit_utils.py's external hit sort uses --
# NOT `sort -V`, which orders article_id numerically (e.g. "3318" before
# "103093") while hit sorting orders it as a plain string (e.g. "103093"
# before "3318"). Sample corpus + hits must agree here or the single-pass
# SentenceReader ends up asked for a sentence it already scanned past.
# Sort keys are prepended (not appended) so they can be stripped back off
# with sed regardless of any tabs embedded in the sentence text itself.
LC_ALL=C awk -F'\t' 'BEGIN{OFS="\t"} {
    s=$1
    if (match(s, /^(.+)\.([0-9]+)\.([0-9]+)$/, a))
        print a[1], a[2], a[3], $0
    else
        print s, "0", "0", $0
}' "$INPUT_FILE" \
    | LC_ALL=C sort -t$'\t' -k1,1 -k2,2n -k3,3n \
          -S "$MEM_BUFFER" \
          -T "$OUTPUT_DIR" \
          --parallel="$NUM_CORES" \
    | sed 's/^[^\t]*\t[^\t]*\t[^\t]*\t//' \
    > "$FINAL_OUTPUT"

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

# LC_ALL=C: the corpus contains stray non-UTF8 bytes (truncated multibyte characters
# from the source articles), which make gawk warn in a UTF-8 locale; it also makes
# length($0) below a true byte count rather than a character count, so the chunk size
# accounting matches TARGET_BYTES_PER_CHUNK.
LC_ALL=C awk -v outdir="$OUTPUT_DIR" \
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
        outfile = outdir "/" prefix chunk_num ".sent"
    }

    {
        split($0, fields, "\t")
        current_article = article_id(fields[1])

        if (bytes_in_chunk >= target && current_article != prev_article && chunk_num < max_chunks) {
            close(outfile)
            chunk_num++
            bytes_in_chunk = 0
            outfile = outdir "/" prefix chunk_num ".sent"
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