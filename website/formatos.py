"""Formatação em português usada fora dos templates (IA e bot do Telegram)."""


def moeda(valor):
    """Decimal('1500.5') -> 'R$ 1.500,50'."""
    return f'R$ {valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def periodo(inicio, fim):
    """Datas de chegada e saída: '03/12/2026 a 06/12/2026'."""
    return f'{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}'
