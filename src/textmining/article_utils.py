from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import mmap
from textmining.models import CandidateHit, NormalizedHit, HitGroup
from textmining.sentence_utils import parse_sentence_id
import logging
import time
import glob
from pathlib import Path
import os

logger = logging.getLogger(__name__)

@dataclass
class ArticleEvidence:
    unambiguous_entity_ids: Optional[set[str]] = field(default_factory=set)

@dataclass
class ArticleMetadata:
    article_id: str

@dataclass
class ArticleRecord:
    metadata: ArticleMetadata
    hits: list[CandidateHit] = field(default_factory=list)
    groups: list[HitGroup] = field(default_factory=list)
    evidence: ArticleEvidence = field(default_factory=ArticleEvidence)
    resolved_hits: list[CandidateHit] = field(default_factory=list)
    normalized_hits: list[NormalizedHit] = field(default_factory=list)


class ArticleSource(str, Enum):
    SYSTEM = 'SYSTEM'
    GOLD = 'GOLD'


class ArticleReader:
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.file = None
        self.mm = None
        self.index = None

    def __enter__(self):
        self.file = open(self.file_path, 'rb')
        self.mm = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.index = self._build_index()
        return self
    
    def __exit__(self, exc_type, exc, tb):
        if self.mm:
            self.mm.close()
        if self.file:
            self.file.close()

    def _build_index(self) -> dict[str, tuple[int, int]]:
        """One linear pass: article_id -> (byte_start, length) of its
        contiguous line-block. Assumes the file is grouped by article_id
        (true for prepare_corpus.sh output); raises if that assumption is
        ever violated instead of silently overwriting the earlier block."""
        start = time.time()
        index = {}
        pos, size = 0, self.mm.size()
        current_id, block_start = None, 0
        while pos < size:
            newline = self.mm.find(b'\n', pos)
            end = newline if newline != -1 else size
            line = self.mm[pos:end]
            if line:
                sent_id = line.split(b'\t', 1)[0].decode()
                article_id = parse_sentence_id(sent_id)[0]
                if article_id != current_id:
                    if current_id is not None:
                        index[current_id] = (block_start, pos - block_start)
                    if article_id in index:
                        logger.critical('Non-contiguous article block for %s in %s', article_id, self.file_path)
                        raise ValueError(
                            f"Non-contiguous article block for {article_id!r} "
                            f"in {self.file_path}: already indexed earlier in "
                            f"the file. File must be grouped by article_id."
                        )
                    current_id, block_start = article_id, pos
            pos = end + 1
        if current_id is not None:
            index[current_id] = (block_start, size - block_start)
        exec_time = time.time() - start
        logger.info('Built index for %s in %.2fs', self.file_path, exec_time)
        return index

    def fetch_article(self, article_id):
        if article_id not in self.index:
            raise ValueError(
                f"Index for {article_id} in {self.file_path} does not exist."
            )
        start, length = self.index[article_id]
        block = self.mm[start : start + length].decode('utf-8')
        return {
            sent_id: sent
            for raw_sent in block.split('\n') if raw_sent
            for sent_id, sent in [raw_sent.split('\t', 1)]
        }

class MultiArticleReader:
    
    def __init__(self, article_file_pattern: str):
        # file_path to ArticleReader
        paths = [Path(p) for p in glob.glob(article_file_pattern)]
        self._readers: dict[str, ArticleReader] = {
            path.name: None for path in paths
        }
        self._name_to_path = {
            os.path.basename(str(p)): p for p in paths
        }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close_all()
    
    def _get_reader(self, file_name: str) -> ArticleReader:
        if file_name not in self._name_to_path.keys():
            logger.critical('Unknown file name: %s', file_name)
            raise ValueError(f'Unknown file name: {file_name}')
        reader = self._readers.get(file_name)
        if reader is None:
            path = self._name_to_path[file_name]
            reader = ArticleReader(path)
            reader.__enter__()
            self._readers[file_name] = reader
        return reader

    def fetch_article(self, file_name: str, article_id: str) -> dict[str, str]:
        return self._get_reader(file_name).fetch_article(article_id)

    def close_all(self):
        for reader in self._readers.values():
            if reader is not None:
                reader.__exit__(None, None, None)
        self._readers.clear()