from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoProvedor:
    """O que todo provedor devolve: texto e tokens gastos."""

    texto: str
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_total: int = 0

    def __post_init__(self):
        if not self.tokens_total:
            object.__setattr__(self, 'tokens_total', self.tokens_entrada + self.tokens_saida)
