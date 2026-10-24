"""Copia os registros do antigo website.UsoIA para ia.RequisicaoIA.

O UsoIA guardava só tokens e custo (o texto das mensagens não era
armazenado); a origem é deduzida do tipo: CHAT -> ASSISTENTE, ANALISE -> ANALISE.
Depois desta migration, a website.0009 apaga o UsoIA.
"""
from django.db import migrations

ORIGEM_POR_TIPO = {'CHAT': 'ASSISTENTE', 'ANALISE': 'ANALISE'}
AVISO = 'Registro migrado do UsoIA (o texto das mensagens não era armazenado).'


def copiar_uso_ia(apps, schema_editor):
    UsoIA = apps.get_model('website', 'UsoIA')
    RequisicaoIA = apps.get_model('ia', 'RequisicaoIA')
    novos = []
    for uso in UsoIA.objects.all().order_by('pk').iterator():
        prompt = f'Análise do pedido #{uso.reserva_id}. {AVISO}' if uso.reserva_id else AVISO
        novos.append(RequisicaoIA(
            usuario_id=uso.usuario_id,
            origem=ORIGEM_POR_TIPO.get(uso.tipo, 'ASSISTENTE'),
            prompt=prompt,
            tokens_entrada=uso.tokens_entrada,
            tokens_saida=uso.tokens_saida,
            tokens_total=uso.tokens_entrada + uso.tokens_saida,
            sucesso=True,
            criado_em=uso.data,  # criado_em usa default (não auto_now_add): a data original é mantida
        ))
    RequisicaoIA.objects.bulk_create(novos, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('ia', '0001_initial'),
        ('website', '0008_avaliacao'),
    ]

    operations = [
        # Volta sem copiar de volta: o UsoIA recriado fica vazio.
        migrations.RunPython(copiar_uso_ia, migrations.RunPython.noop),
    ]
