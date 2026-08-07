from models import HitType
from src.textmining.ontology import OntologyGraph
from dataclasses import dataclass

@dataclass(frozen=True)
class HitScore:
    ic: float # Information content

class HitScorer:
    def __init__(self, type_to_ontology: dict[HitType, OntologyGraph]):
        self._type_to_ontology = type_to_ontology
    
    def compute_score(self,
                     entity_type: HitType,
                     normalized_id: str):
        ic = self.type_to_ontology[entity_type].compute_ic(normalized_id)
        return HitScore(ic)