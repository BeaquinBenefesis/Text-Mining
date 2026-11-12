import argparse
import hashlib
import logging
import urllib.error
import urllib.request
import textmining.resources as res
from textmining.ontology import OntologyGraph, to_external_id
from textmining.synonym_utils import write_syn_file, drop_shadowed, case_sensitive_abbreviations, CASE_SENS_TAG
from textmining.enums import HitType, SynonymScope

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
    cached = OntologyGraph.load(source.cache_path) if source.cache_path.exists() else None

    roots_changed = cached is not None and not cached.built_with(source.roots, source.relationships)
    if roots_changed:
        logger.info("%s: cache built with roots %s over %s, configured roots %s over %s",
                    source.hit_type.name, cached.root_ids, cached.relationships,
                    source.roots, source.relationships)

    if offline or source.url is None:
        if cached is None or roots_changed:
            logger.info("%s: %s, building from local .obo", source.hit_type.name,
                        "roots or relationships changed" if roots_changed else "no cache and no network access")
            graph = OntologyGraph.from_obo(source.local_path, relationships=source.relationships,
                                           root_ids=source.roots, **source.obo_kwargs)
            graph.save(source.cache_path)
            return graph
        logger.info("%s: offline, keeping existing cache", source.hit_type.name)
        return None

    new_bytes = _fetch_obo_bytes(source.url)
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    old_hash = cached.source_hash if cached else None

    if cached is not None and old_hash == new_hash and not roots_changed:
        logger.info("%s: up to date", source.hit_type.name)
        return None

    if cached is not None and old_hash != new_hash and not _prompt_rebuild(source, old_hash, new_hash):
        logger.info("%s: rebuild declined, keeping existing cache", source.hit_type.name)
        return None

    source.local_path.write_bytes(new_bytes)
    graph = OntologyGraph.from_obo(source.local_path, relationships=source.relationships,
                                   root_ids=source.roots, **source.obo_kwargs)  # sets graph.source_hash itself
    graph.save(source.cache_path)
    logger.info("%s: rebuilt (%s)", source.hit_type.name, graph.source_hash[:8])
    return graph


def refresh_synonyms(source: "res.OntologySource", graph: OntologyGraph) -> None:
    for spec in res.EXTRACTABLE_SYNONYMS.get(source.hit_type, []):
        # the root terms stay in the graph, only their names are kept out of the synonym files
        excluded_ids = set() if spec.include_roots else {to_external_id(r) for r in spec.roots or ()}
        triples = [t for t in graph.extract_synonyms(spec.roots, scopes=spec.scopes) if t[0] not in excluded_ids]
        if excluded_ids:
            logger.info("%s: left out root term(s) %s", source.hit_type.name, sorted(excluded_ids))
        if set(spec.scopes) != {SynonymScope.EXACT}:
            # a looser-scope synonym must not shadow the label or EXACT synonym of another term
            authoritative = [t for t in graph.extract_synonyms(spec.roots, scopes=(SynonymScope.EXACT,))
                             if t[0] not in excluded_ids]
            triples, dropped = drop_shadowed(triples, authoritative)
            dropped_path = spec.output_path.with_suffix('.dropped.tsv')
            with open(dropped_path, 'w') as out:
                out.write('term_id\tsynonym\tauthoritative_term_ids\n')
                out.writelines('\t'.join(row) + '\n' for row in dropped)
            logger.info("%s: dropped %d synonym(s) shadowing another term's label or EXACT synonym -> %s",
                        source.hit_type.name, len(dropped), dropped_path)
        write_syn_file(spec.output_path, ((term_id, syns) for term_id, syns, _ in triples))
        abbrev_groups, dropped_abbrevs = [], []
        for term_id, _, abbrevs in triples:
            kept, dropped = case_sensitive_abbreviations(abbrevs)
            dropped_abbrevs.extend((term_id, a) for a in dropped)
            if kept:
                abbrev_groups.append((term_id, kept))
        write_syn_file(spec.abbreviation_output_path, abbrev_groups)
        dropped_path = spec.abbreviation_output_path.with_suffix('.dropped.tsv')
        with open(dropped_path, 'w') as out:
            out.write('term_id\tabbreviation\n')
            out.writelines(f'{term_id}\t{a}\n' for term_id, a in dropped_abbrevs)
        n_tagged = sum(a.endswith(CASE_SENS_TAG) for _, kept in abbrev_groups for a in kept)
        logger.info("%s: %d abbreviation(s) tagged case-sensitive, %d lowercase duplicate(s) dropped -> %s",
                    source.hit_type.name, n_tagged, len(dropped_abbrevs), dropped_path)
        logger.info("%s: re-extracted synonyms (scopes %s) -> %s", source.hit_type.name,
                    [s.value for s in spec.scopes], spec.output_path)
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
    parser.add_argument(
        "--rewrite-synonyms", action="store_true",
        help="Re-extract the synonym files also for unchanged ontologies, e.g. after a change to the synonym rules",
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
            if graph is None and args.rewrite_synonyms and source.hit_type in res.EXTRACTABLE_SYNONYMS:
                graph = OntologyGraph.load(source.cache_path)
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
