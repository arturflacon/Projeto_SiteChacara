"""Contexto enviado à IA: o arquivo contexto_projeto.md + dados atuais do banco.

Só vai o que é público: nome, comodidades e diária da chácara e as datas
confirmadas futuras. Nenhum dado de cliente (nome, telefone, observações).
"""
from functools import lru_cache
from pathlib import Path

from django.utils import timezone

from website import services as website_services

ARQUIVO_CONTEXTO = Path(__file__).resolve().parent / 'contexto_projeto.md'


@lru_cache(maxsize=1)
def contexto_fixo():
    return ARQUIVO_CONTEXTO.read_text(encoding='utf-8').strip()


def _moeda(valor):
    return f'R$ {valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _sim_nao(valor):
    return 'sim' if valor else 'não'


def dados_atuais():
    hoje = timezone.localdate()
    chacara = website_services.chacara_principal()
    if chacara is None:
        dados_chacara = 'Os dados da chácara ainda não foram cadastrados.'
    else:
        dados_chacara = '\n'.join([
            f'- Nome: {chacara.nome}',
            f'- Descrição: {chacara.descricao}',
            f'- Preço da diária: {_moeda(chacara.preco_diaria)}',
            f'- Quartos: {chacara.num_quartos}',
            f'- Banheiros: {chacara.num_banheiros}',
            f'- Piscina: {_sim_nao(chacara.tem_piscina)}',
            f'- Churrasqueira: {_sim_nao(chacara.tem_churrasqueira)}',
            f'- Estacionamento: {_sim_nao(chacara.tem_estacionamento)}',
        ])
    periodos = website_services.datas_confirmadas_futuras()
    if periodos:
        ocupadas = '\n'.join(f'- chegada {inicio:%d/%m/%Y}, saída {fim:%d/%m/%Y}' for inicio, fim in periodos)
    else:
        ocupadas = '- nenhuma data confirmada no momento'
    return (
        f'## Dados atuais (hoje é {hoje:%d/%m/%Y})\n\n'
        f'### A chácara\n{dados_chacara}\n\n'
        f'### Datas já confirmadas (indisponíveis)\n{ocupadas}\n'
        'Datas fora desta lista estão livres no momento, mas podem ser reservadas por outra pessoa.'
    )


def montar_contexto():
    return f'{contexto_fixo()}\n\n{dados_atuais()}'
