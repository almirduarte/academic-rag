"""Códigos de setor persistidos em users.use_setor; nunca renumerar os existentes."""
SECTORS = {
    1: 'Comando',
    2: 'Superintendência de Ensino (SE)',
    3: 'Superintendência de Administração (SA)',
    4: 'ComCA - Oficiais',
    5: 'ComCA - Aspirantes',
    6: 'ComCA - Saúde',
    7: 'Centro de Informática (CInf)',
    8: 'SE - SOEPE',
}


def validate_sector(value: int) -> int:
    if value not in SECTORS:
        raise ValueError('Selecione um setor válido.')
    return value
