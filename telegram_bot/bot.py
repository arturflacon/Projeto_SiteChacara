"""Lógica do bot: recebe um update do webhook, registra, limita e responde.

Regras de negócio vêm de website.services e a IA de assistente.services
(que usa ia.services.chamar_ia). A cada mensagem ou clique o usuário
vinculado é buscado de novo no banco — nunca se confia no botão.
"""
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from assistente import services as assistente_services
from ia.excecoes import CotaExcedida, IADesativada
from ia.models import RequisicaoIA
from website import services
from website.formatos import moeda, periodo
from website.models import Reserva

from . import api
from .models import CodigoVinculacao, MensagemTelegram, TentativaVinculoInvalida, VinculoTelegram

logger = logging.getLogger(__name__)

AVISO_LIMITE = 'Muitas mensagens, aguarde um pouco.'
FORMATO_CODIGO = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
FORMATO_CALLBACK = re.compile(r'^(apr|rec|can):(\d{1,12})$')
MAX_ITENS = 10

TEXTO_AJUDA = """Comandos:
/chacara — informações e diária atual
/disponibilidade — próximas datas já reservadas
/minhasreservas — seus pedidos (com botão para cancelar os pendentes)
/perguntar <dúvida> — pergunte ao assistente virtual
/vincular <código> — liga esta conversa à sua conta do site
/desvincular — desfaz o vínculo
/pendentes — pedidos aguardando decisão (só administração)
/ajuda — esta lista"""

TEXTO_SEM_VINCULO = ('Para usar este comando, vincule sua conta: no site, abra o menu com o seu nome '
                     '→ Conectar Telegram e siga as instruções.')


@dataclass
class Contexto:
    """Quem está falando com o bot nesta atualização."""

    chat_id: int
    telegram_user_id: int
    username: str
    vinculo: VinculoTelegram | None

    @property
    def usuario(self):
        return self.vinculo.usuario if self.vinculo else None


# ---------------------------------------------------------------------------
# Log, limites e envio
# ---------------------------------------------------------------------------

def _buscar_vinculo(chat_id, telegram_user_id):
    """O vínculo vale para a conversa E para a conta do Telegram que o fez."""
    return (
        VinculoTelegram.objects.select_related('usuario')
        .filter(chat_id=chat_id, telegram_user_id=telegram_user_id)
        .first()
    )


def _registrar_entrada(update_id, ctx, tipo, texto):
    """Grava a entrada. Devolve None se o update_id já foi processado (reenvio do Telegram)."""
    try:
        with transaction.atomic():
            return MensagemTelegram.objects.create(
                direcao=MensagemTelegram.ENTRADA, update_id=update_id, chat_id=ctx.chat_id,
                telegram_user_id=ctx.telegram_user_id, usuario=ctx.usuario, tipo=tipo,
                texto=texto[:MensagemTelegram.LIMITE_TEXTO],
            )
    except IntegrityError:
        logger.info('Update %s repetido: ignorado.', update_id)
        return None


def _registrar_saida(ctx, tipo, texto, aviso_limite=False):
    MensagemTelegram.objects.create(
        direcao=MensagemTelegram.SAIDA, chat_id=ctx.chat_id, usuario=ctx.usuario, tipo=tipo,
        texto=texto[:MensagemTelegram.LIMITE_TEXTO], aviso_limite=aviso_limite,
    )


def enviar(ctx, texto, teclado=None, aviso_limite=False):
    try:
        api.enviar_mensagem(ctx.chat_id, texto, teclado)
    except api.ErroTelegram as erro:
        logger.warning('Falha ao enviar mensagem para o chat %s: %s', ctx.chat_id, erro)
    _registrar_saida(ctx, MensagemTelegram.MENSAGEM, texto, aviso_limite)


def _responder_callback(ctx, callback_id, texto, aviso_limite=False):
    try:
        api.responder_callback(callback_id, texto, alerta=len(texto) > 60)
    except api.ErroTelegram as erro:
        logger.warning('Falha ao responder callback no chat %s: %s', ctx.chat_id, erro)
    _registrar_saida(ctx, MensagemTelegram.CALLBACK, texto, aviso_limite)


def _editar(ctx, message_id, texto):
    try:
        api.editar_mensagem(ctx.chat_id, message_id, texto)
    except api.ErroTelegram as erro:
        logger.warning('Falha ao editar mensagem no chat %s: %s', ctx.chat_id, erro)
    _registrar_saida(ctx, MensagemTelegram.MENSAGEM, texto)


def _janela_excedida(telegram_user_id):
    """Janela de tempo cujo limite o remetente passou (None se está dentro dos limites).

    Conta no banco (a mensagem atual já registrada): funciona com várias
    instâncias do App Engine atendendo ao mesmo tempo.
    """
    agora = timezone.now()
    entradas = MensagemTelegram.objects.filter(direcao=MensagemTelegram.ENTRADA, telegram_user_id=telegram_user_id)
    if entradas.filter(criado_em__gte=agora - timedelta(minutes=1)).count() > settings.TELEGRAM_LIMITE_POR_MINUTO:
        return timedelta(minutes=1)
    if entradas.filter(criado_em__gte=agora - timedelta(days=1)).count() > settings.TELEGRAM_LIMITE_POR_DIA:
        return timedelta(days=1)
    return None


def _avisar_limite_uma_vez(ctx, janela, callback_id=None):
    """Avisa uma única vez por janela; o resto é ignorado em silêncio."""
    ja_avisou = MensagemTelegram.objects.filter(
        direcao=MensagemTelegram.SAIDA, chat_id=ctx.chat_id, aviso_limite=True,
        criado_em__gte=timezone.now() - janela,
    ).exists()
    if ja_avisou:
        return
    if callback_id:
        _responder_callback(ctx, callback_id, AVISO_LIMITE, aviso_limite=True)
    else:
        enviar(ctx, AVISO_LIMITE, aviso_limite=True)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def processar_update(update):
    update_id = update.get('update_id')
    if 'callback_query' in update:
        _processar_callback(update_id, update['callback_query'])
    elif 'message' in update:
        _processar_mensagem(update_id, update['message'])
    # Outros tipos não são assinados (allowed_updates); se vierem, são ignorados.


def _processar_mensagem(update_id, mensagem):
    chat = mensagem.get('chat') or {}
    remetente = mensagem.get('from') or {}
    if chat.get('id') is None or remetente.get('id') is None:
        return
    ctx = Contexto(chat['id'], remetente['id'], remetente.get('username') or '',
                   _buscar_vinculo(chat['id'], remetente['id']))
    texto = (mensagem.get('text') or '').strip()
    eh_comando = texto.startswith('/')
    tipo = MensagemTelegram.COMANDO if eh_comando else MensagemTelegram.MENSAGEM
    if _registrar_entrada(update_id, ctx, tipo, texto or '(mensagem sem texto)') is None:
        return
    janela = _janela_excedida(ctx.telegram_user_id)
    if janela:
        _avisar_limite_uma_vez(ctx, janela)
        return
    if chat.get('type') != 'private':
        enviar(ctx, 'Por segurança, só converso em chat privado. Abra uma conversa direta comigo.')
        return
    if not eh_comando:
        enviar(ctx, 'Não entendi. Use /ajuda para ver os comandos ou /perguntar <sua dúvida>.')
        return
    comando, _, argumento = texto.partition(' ')
    comando = comando.split('@', 1)[0].lower()  # "/start@MeuBot" -> "/start"
    acao = COMANDOS.get(comando)
    if acao is None:
        enviar(ctx, 'Comando desconhecido. Use /ajuda para ver a lista.')
        return
    acao(ctx, argumento.strip())


def _processar_callback(update_id, callback):
    mensagem = callback.get('message') or {}
    chat_id = (mensagem.get('chat') or {}).get('id')
    remetente = callback.get('from') or {}
    if chat_id is None or remetente.get('id') is None or not callback.get('id'):
        return
    # Revalida no servidor quem está clicando: o vínculo é buscado de novo.
    ctx = Contexto(chat_id, remetente['id'], remetente.get('username') or '',
                   _buscar_vinculo(chat_id, remetente['id']))
    dado = callback.get('data') or ''
    if _registrar_entrada(update_id, ctx, MensagemTelegram.CALLBACK, dado) is None:
        return
    janela = _janela_excedida(ctx.telegram_user_id)
    if janela:
        _avisar_limite_uma_vez(ctx, janela, callback_id=callback['id'])
        return
    resposta, novo_texto = _executar_callback(ctx, dado)
    _responder_callback(ctx, callback['id'], resposta)
    if novo_texto and mensagem.get('message_id'):
        _editar(ctx, mensagem['message_id'], novo_texto)


def _executar_callback(ctx, dado):
    """Executa apr:/rec:/can:<id>. Devolve (texto do aviso, novo texto da mensagem ou None)."""
    correspondencia = FORMATO_CALLBACK.match(dado)
    if not correspondencia:
        return 'Botão inválido.', None
    if ctx.usuario is None:
        return TEXTO_SEM_VINCULO, None
    acao, reserva_id = correspondencia.group(1), int(correspondencia.group(2))
    try:
        # As funções de serviço checam permissão (admin/dono), status e conflito.
        if acao == 'apr':
            reserva, recusados = services.aprovar_reserva(reserva_id, ctx.usuario, 'Aprovado pelo Telegram.')
            texto = f'✅ Pedido #{reserva.pk} de {reserva.cliente.nome} ({periodo(reserva.data_inicio, reserva.data_fim)}) APROVADO.'
            if recusados:
                texto += f'\n{recusados} pedido(s) no mesmo período foram recusados automaticamente.'
            return 'Pedido aprovado.', texto
        if acao == 'rec':
            reserva = services.recusar_reserva(reserva_id, ctx.usuario, 'Recusado pelo Telegram.')
            return 'Pedido recusado.', (
                f'❌ Pedido #{reserva.pk} de {reserva.cliente.nome} '
                f'({periodo(reserva.data_inicio, reserva.data_fim)}) RECUSADO.')
        reserva = services.cancelar_pedido_cliente(reserva_id, ctx.usuario)
        return 'Pedido cancelado.', (
            f'Pedido #{reserva.pk} ({periodo(reserva.data_inicio, reserva.data_fim)}) CANCELADO por você.')
    except services.ErroRegraNegocio as erro:
        return str(erro), None


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def _nome_do_usuario(usuario):
    perfil = getattr(usuario, 'cliente', None) or getattr(usuario, 'administrador', None)
    return perfil.nome if perfil else usuario.username


def vincular(codigo, ctx):
    """Consome o código (uso único) e liga esta conversa ao dono dele. Devolve o User ou None."""
    if not FORMATO_CODIGO.match(codigo):
        return None
    agora = timezone.now()
    with transaction.atomic():
        # Consumo atômico: um único UPDATE ... WHERE usado_em IS NULL AND expira_em > agora.
        # Duas mensagens com o mesmo código ao mesmo tempo: só uma consegue.
        consumidos = (
            CodigoVinculacao.objects
            .filter(codigo=codigo, usado_em__isnull=True, expira_em__gt=agora)
            .update(usado_em=agora)
        )
        if consumidos != 1:
            return None
        usuario = CodigoVinculacao.objects.select_related('usuario').get(codigo=codigo).usuario
        # Uma conversa pertence a um único usuário, e o usuário a uma única conversa.
        VinculoTelegram.objects.filter(chat_id=ctx.chat_id).exclude(usuario=usuario).delete()
        ctx.vinculo, _ = VinculoTelegram.objects.update_or_create(
            usuario=usuario,
            defaults={'chat_id': ctx.chat_id, 'telegram_user_id': ctx.telegram_user_id, 'username': ctx.username},
        )
    return usuario


def cmd_start(ctx, argumento):
    if argumento:  # deep link t.me/<bot>?start=<código>
        cmd_vincular(ctx, argumento)
        return
    chacara = services.chacara_principal()
    nome = chacara.nome if chacara else 'Sítio de Lurdes'
    if ctx.usuario:
        situacao = f'Sua conta ({ctx.usuario.username}) está vinculada.'
    else:
        situacao = ('Para ver suas reservas por aqui, vincule sua conta: no site, abra o menu com o seu '
                    'nome → Conectar Telegram.')
    enviar(ctx, f'Olá! Eu sou o bot do {nome}.\n{situacao}\n\n{TEXTO_AJUDA}')


def cmd_ajuda(ctx, argumento):
    enviar(ctx, TEXTO_AJUDA)


def cmd_vincular(ctx, codigo):
    if not codigo:
        enviar(ctx, 'Use /vincular <código>. O código é gerado no site, em Conectar Telegram.')
        return
    uma_hora_atras = timezone.now() - timedelta(hours=1)
    tentativas = TentativaVinculoInvalida.objects.filter(
        telegram_user_id=ctx.telegram_user_id, criado_em__gte=uma_hora_atras).count()
    if tentativas >= settings.TELEGRAM_TENTATIVAS_VINCULO_POR_HORA:
        enviar(ctx, 'Muitas tentativas com código inválido. Tente de novo daqui a uma hora.')
        return
    usuario = vincular(codigo, ctx)
    if usuario is None:
        TentativaVinculoInvalida.objects.create(telegram_user_id=ctx.telegram_user_id)
        enviar(ctx, 'Código inválido, expirado ou já usado. Gere um novo no site, em Conectar Telegram.')
        return
    enviar(ctx, f'Pronto, {_nome_do_usuario(usuario)}! Sua conta "{usuario.username}" foi vinculada.\n'
                'Use /minhasreservas para ver seus pedidos ou /ajuda para ver tudo o que eu faço.')


def cmd_desvincular(ctx, argumento):
    if ctx.vinculo is None:
        enviar(ctx, 'Esta conversa não está vinculada a nenhuma conta.')
        return
    ctx.vinculo.delete()
    ctx.vinculo = None
    enviar(ctx, 'Conta desvinculada. Para vincular de novo, gere um código no site em Conectar Telegram.')


def cmd_chacara(ctx, argumento):
    chacara = services.chacara_principal()
    if chacara is None:
        enviar(ctx, 'A chácara ainda não foi cadastrada.')
        return
    comodidades = [nome for nome, tem in (('piscina', chacara.tem_piscina),
                                          ('churrasqueira', chacara.tem_churrasqueira),
                                          ('estacionamento', chacara.tem_estacionamento)) if tem]
    avaliacoes = services.resumo_avaliacoes(chacara)
    linhas = [
        f'🏡 {chacara.nome}',
        chacara.descricao[:600],
        '',
        f'Diária: {moeda(chacara.preco_diaria)}',
        f'{chacara.num_quartos} quartos · {chacara.num_banheiros} banheiros',
    ]
    if comodidades:
        linhas.append('Tem: ' + ', '.join(comodidades))
    if avaliacoes['total']:
        linhas.append(f"Avaliação: {avaliacoes['media']:.1f} de 5 ({avaliacoes['total']} avaliações)".replace('.', ',', 1))
    linhas.append('\nVeja as datas ocupadas com /disponibilidade.')
    enviar(ctx, '\n'.join(linhas))


def cmd_disponibilidade(ctx, argumento):
    periodos = services.datas_confirmadas_futuras()  # só datas: nenhum nome de cliente
    if not periodos:
        enviar(ctx, 'Nenhuma data confirmada no momento: todas estão livres! Faça seu pedido pelo site.')
        return
    linhas = [f'• {periodo(inicio, fim)}' for inicio, fim in periodos[:15]]
    if len(periodos) > 15:
        linhas.append(f'… e mais {len(periodos) - 15} período(s). Veja todos no site.')
    enviar(ctx, 'Datas já reservadas (o dia de saída fica livre para nova chegada):\n' + '\n'.join(linhas))


def _linha_reserva(reserva):
    valor = f' · {moeda(reserva.valor_total)}' if reserva.valor_total else ''
    return f'#{reserva.pk} · {periodo(reserva.data_inicio, reserva.data_fim)}{valor} · {reserva.get_status_display()}'


def cmd_minhasreservas(ctx, argumento):
    if ctx.usuario is None:
        enviar(ctx, TEXTO_SEM_VINCULO)
        return
    reservas = list(services.reservas_do_usuario(ctx.usuario)[:MAX_ITENS])
    if not reservas:
        enviar(ctx, 'Você ainda não tem reservas. Faça seu pedido pelo site.')
        return
    enviar(ctx, 'Suas últimas reservas:\n' + '\n'.join(_linha_reserva(r) for r in reservas))
    for reserva in reservas:
        if reserva.status == Reserva.STATUS_PENDENTE:
            enviar(ctx, f'Pedido pendente {_linha_reserva(reserva)}',
                   teclado=api.teclado_inline([[('Cancelar pedido', f'can:{reserva.pk}')]]))


def cmd_pendentes(ctx, argumento):
    if ctx.usuario is None:
        enviar(ctx, TEXTO_SEM_VINCULO)
        return
    if not services.usuario_eh_admin(ctx.usuario):
        enviar(ctx, 'Este comando é só para a administração.')
        return
    todos = services.pedidos_pendentes()
    pedidos = list(todos[:MAX_ITENS])
    if not pedidos:
        enviar(ctx, 'Nenhum pedido pendente. Tudo em dia!')
        return
    total = todos.count() if len(pedidos) == MAX_ITENS else len(pedidos)
    cabecalho = f'{total} pedido(s) pendente(s)'
    if total > MAX_ITENS:
        cabecalho += f'; mostrando os {MAX_ITENS} mais antigos'
    enviar(ctx, cabecalho + ':')
    for r in pedidos:
        observacoes = f'\nObs.: {r.observacoes[:200]}' if r.observacoes else ''
        enviar(ctx, f'#{r.pk} · {r.cliente.nome}\n{periodo(r.data_inicio, r.data_fim)}'
                    f'{" · " + moeda(r.valor_total) if r.valor_total else ""}{observacoes}',
               teclado=api.teclado_inline([[('Aprovar', f'apr:{r.pk}'), ('Recusar', f'rec:{r.pk}')]]))


def cmd_perguntar(ctx, texto):
    if ctx.usuario is None:
        enviar(ctx, TEXTO_SEM_VINCULO)
        return
    if not texto:
        enviar(ctx, 'Escreva a dúvida depois do comando. Ex.: /perguntar Tem piscina?')
        return
    if len(texto) > assistente_services.MAX_CARACTERES_PERGUNTA:
        enviar(ctx, f'A pergunta pode ter no máximo {assistente_services.MAX_CARACTERES_PERGUNTA} caracteres.')
        return
    try:
        resposta = assistente_services.perguntar(
            ctx.usuario, texto, RequisicaoIA.Origem.BOT, usar_historico=False)
    except (CotaExcedida, IADesativada) as erro:
        enviar(ctx, str(erro))
        return
    enviar(ctx, resposta.texto if resposta.sucesso else resposta.erro)


COMANDOS = {
    '/start': cmd_start,
    '/ajuda': cmd_ajuda,
    '/help': cmd_ajuda,
    '/vincular': cmd_vincular,
    '/desvincular': cmd_desvincular,
    '/chacara': cmd_chacara,
    '/disponibilidade': cmd_disponibilidade,
    '/minhasreservas': cmd_minhasreservas,
    '/pendentes': cmd_pendentes,
    '/perguntar': cmd_perguntar,
}
