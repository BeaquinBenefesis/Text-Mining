import argparse
import hashlib
import logging
import urllib.error
import urllib.request
import textmining.resources as res
from textmining.ontology import OntologyGraph
from textmining.synonym_utils import write_syn_file
from textmining.types import HitType

logger = logging.getLogger(__name__)


def _fetch_obo_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()

def _prompt_rebuild(source: "res.OntologySource", old_hash: str | None, new_hash: str) -> bool:
    answer = input(
        f"{source.hit_type.name}: source changed "
        f"({old_hash[:8]} -> {new_hash[:8]}). Rebuild? [y/N] "
    ).strip().lower()
    return answer in ("y", "yes")


def refresh_ontology(source: "res.OntologySource", offline: bool = False) -> OntologyGraph | None:
    """The one primitive: fetch/hash/compare/prompt/rebuild for a single
    OntologySource. See refresh_data_notes.txt for the agreed flow. Returns
    the rebuilt OntologyGraph, or None if nothing was rebuilt (up to date,
    offline with an existing cache, or rebuild declined)."""
    cached = OntologyGraph.load(source.cache_path) if source.cache_path.exists() else None

    if offline or source.url is None:
        if cached is None:
            logger.info("%s: no cache and no network access, building from local .obo", source.hit_type.name)
            graph = OntologyGraph.from_obo(source.local_path, **source.obo_kwargs)
            graph.save(source.cache_path)
            return graph
        logger.info("%s: offline, keeping existing cache", source.hit_type.name)
        return None

    new_bytes = _fetch_obo_bytes(source.url)
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    old_hash = cached.source_hash if cached else None

    if cached is not None and old_hash == new_hash:
        logger.info("%s: up to date", source.hit_type.name)
        return None

    if cached is not None and not _prompt_rebuild(source, old_hash, new_hash):
        logger.info("%s: rebuild declined, keeping existing cache", source.hit_type.name)
        return None

    source.local_path.write_bytes(new_bytes)
    graph = OntologyGraph.from_obo(source.local_path, **source.obo_kwargs)  # sets graph.source_hash itself
    graph.save(source.cache_path)
    logger.info("%s: rebuilt (%s)", source.hit_type.name, graph.source_hash[:8])
    return graph


def refresh_synonyms(source: "res.OntologySource", graph: OntologyGraph) -> None:
    """Re-extract every ExtractedSynonymSpec registered for this HitType from
    the freshly rebuilt graph. HitTypes with no entry in EXTRACTABLE_SYNONYMS
    (e.g. TAXON, whose .syn files are static LINNAEUS dictionaries) are a
    silent no-op."""
    for spec in res.EXTRACTABLE_SYNONYMS.get(source.hit_type, []):
        triples = list(graph.extract_synonyms(spec.roots))
        write_syn_file(spec.output_path, ((term_id, syns) for term_id, syns, _ in triples))
        write_syn_file(
            spec.abbreviation_output_path,
            ((term_id, abbrevs) for term_id, _, abbrevs in triples if abbrevs),
        )
        logger.info("%s: re-extracted synonyms -> %s", source.hit_type.name, spec.output_path)
        logger.info("%s: re-extracted abbreviations -> %s", source.hit_type.name, spec.abbreviation_output_path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s | %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true",
        help="Skip network fetches (semantics still TBD, see refresh_data_notes.txt)",
    )
    parser.add_argument(
        "--only", nargs="+", metavar="HIT_TYPE",
        help="Restrict to these HitType names instead of refreshing every registered source",
    )
    args = parser.parse_args()

    sources = res.ONTOLOGY_SOURCES.values()
    if args.only:
        sources = []
        for arg in args.only:
            hit_type = HitType(arg)
            source = res.ONTOLOGY_SOURCES.get(hit_type)
            if source is None:
                parser.error(f"{arg} has no registered OntologySource (no .obo-based ontology for this HitType)")
            sources.append(source)

    for source in sources:
        try:
            graph = refresh_ontology(source, offline=args.offline)
            if graph is not None:
                refresh_synonyms(source, graph)
        except urllib.error.HTTPError as e:
            logger.error("%s: HTTP %s fetching %s", source.hit_type.name, e.code, source.url)
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                logger.error("%s: timed out fetching %s", source.hit_type.name, source.url)
            else:
                logger.error("%s: connection error fetching %s: %s", source.hit_type.name, source.url, e.reason)


if __name__ == "__main__":
    main()
