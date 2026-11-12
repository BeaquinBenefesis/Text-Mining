from textmining.synonym_utils import drop_shadowed


def test_drop_shadowed():
    authoritative = [
        ('T_1', ['epidermis'], []),
        ('T_2', ['plant epidermis'], []),
        ('T_3', ['PI3K-Akt signaling pathway'], []),
        ('T_4', ['PI3K signaling pathway'], []),
        # EXACT name shared by two terms: authoritative for both, stays on both
        ('T_5', ['drug pathway', 'drug pathway A'], []),
        ('T_6', ['drug pathway'], []),
    ]
    triples = [
        ('T_1', ['epidermis'], []),
        # RELATED synonym equal to the label of T_1, in another case
        ('T_2', ['Epidermis', 'plant epidermis'], ['PE']),
        # own name in another case, and a RELATED synonym shared with T_4
        ('T_3', ['PI3K Cascade', 'PI3K-AKT signaling pathway', 'PI3K-Akt signaling pathway'], []),
        ('T_4', ['PI3K Cascade', 'PI3K signaling pathway'], []),
        ('T_5', ['drug pathway', 'drug pathway A'], []),
        ('T_6', ['drug pathway'], []),
    ]

    kept, dropped = drop_shadowed(triples, authoritative)

    assert kept == [
        ('T_1', ['epidermis'], []),
        ('T_2', ['plant epidermis'], ['PE']),
        ('T_3', ['PI3K Cascade', 'PI3K-AKT signaling pathway', 'PI3K-Akt signaling pathway'], []),
        ('T_4', ['PI3K Cascade', 'PI3K signaling pathway'], []),
        ('T_5', ['drug pathway', 'drug pathway A'], []),
        ('T_6', ['drug pathway'], []),
    ]
    assert dropped == [('T_2', 'Epidermis', 'T_1')]
