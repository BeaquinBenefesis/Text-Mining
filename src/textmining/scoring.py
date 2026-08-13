from dataclasses import dataclass
from textmining.types import HitType
from textmining.ontology import OntologyGraph
from textmining.ontology import to_internal_id

@dataclass(frozen=True)
class HitScore:
    ic: float # Information content

class HitScorer:
    def __init__(self, type_to_ontology: dict[HitType, OntologyGraph]):
        self._type_to_ontology = type_to_ontology
    
    def compute_score(self,
                     entity_type: HitType,
                     normalized_id: str):
        internal_id = to_internal_id(normalized_id)
        ic = self._type_to_ontology[entity_type].compute_ic(internal_id)
        return HitScore(ic)