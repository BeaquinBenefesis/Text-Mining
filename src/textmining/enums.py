from enum import Enum

class GroupStatus(str, Enum):
    DEFAULT = 'DEFAULT'
    EXACT_MATCH = 'EXACT_MATCH'
    RESOLVED = 'RESOLVED'
    AMBIGUOUS_ID = 'AMBIGUOUS_ID'
    AMBIGUOUS_ENTITY_TYPE = 'AMBIGUOUS_ENTITY_TYPE'
    FAILURE = 'FAILURE'

class HitType(str, Enum):
    MIR = 'MIR'
    TAXON = 'TAXON'
    DISEASE = 'DISEASE'
    TISSUE = 'TISSUE'
    CELL = 'CELL'
    PATHWAY = 'PATHWAY'
    BIOLOGICAL_PROCESS = 'BIOLOGICAL_PROCESS'

class SynonymType(str, Enum):
    STANDARD = 'STANDARD'
    ABBREVIATION = 'ABBREVIATION'
    INFERRED_ABBREVIATION = 'INFERRED_ABBREVIATION'

class NormalizationStatus(str, Enum):
    NORMALIZED = 'NORMALIZED' # Successful exact normalization
    FALLBACK = 'FALLBACK' # Normalized using a fallback heuristic
    #AMBIGUOUS = 'AMBIGUOUS' # Normalization matched multiple entities
    UNKNOWN_ENTITY = 'UNKNOWN_ENTITY' # Could not normalize
    FILTERED = 'FILTERED' # Probably a false positive, filter out
    IN_BLACKLIST = 'IN_BLACKLIST' # Known terms of high ambiguity, low confidence hit

class NormalizationTargetType(str, Enum):
    MIR_FAMILY = 'MIR_FAMILY'
    MIR_PRECURSOR = 'MIR_PRECURSOR'
    MIR_MATURE = 'MIR_MATURE'
