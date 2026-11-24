<?php
declare(strict_types=1);

function farol_sectors(): array
{
    // Códigos existentes preservados; espelha app/sectors.py e ck_users_setor.
    return [
        1 => 'Comando',
        2 => 'Superintendência de Ensino (SE)',
        3 => 'Superintendência de Administração (SA)',
        4 => 'ComCA - Oficiais',
        5 => 'ComCA - Aspirantes',
        6 => 'ComCA - Saúde',
        7 => 'Centro de Informática (CInf)',
        8 => 'SE - SOEPE',
    ];
}
