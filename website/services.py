"""Regras de negócio do Sítio de Lurdes.

Funções de domínio usadas pelas views do site E pelo bot do Telegram. Nenhuma
view muda o status de uma reserva diretamente: tudo passa por aqui, para que
as regras (permissão, status, conflito de datas, histórico) valham igual em
todos os canais.

Quando uma regra é violada, as funções levantam ``ErroRegraNegocio`` com uma
mensagem pronta para mostrar ao usuário.
"""
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from .models import Chacara, HistoricoReserva, Reserva

GRUPO_ADMIN = 'Administradores'


class ErroRegraNegocio(Exception):
    """Violação de regra de negócio. ``str(erro)`` é a mensagem amigável."""


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def chacara_principal():
    """A única chácara do sistema (ou None se ainda não foi cadastrada)."""
    return Chacara.objects.order_by('pk').first()


def usuario_eh_admin(user):
    """Admin = superuser, perfil ``Administrador`` ou membro do grupo ``Administradores``."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    # hasattr: sem perfil, o acesso levanta RelatedObjectDoesNotExist, que
    # também é um AttributeError.
    if user.is_superuser or hasattr(user, 'administrador'):
        return True
    return user.groups.filter(name=GRUPO_ADMIN).exists()


def datas_confirmadas_futuras():
    """Períodos (início, fim) das reservas confirmadas que ainda não terminaram.

    Só as datas saem do banco: nenhum dado do cliente (pode ir para visitantes,
    para a IA e para o bot).
    """
    return list(
        Reserva.objects
        .filter(status=Reserva.STATUS_CONFIRMADA, data_fim__gte=timezone.localdate())
        .order_by('data_inicio')
        .values_list('data_inicio', 'data_fim')
    )


def reservas_do_usuario(usuario):
    """Reservas do cliente ligado ao usuário (vazio para quem não é cliente)."""
    return (
        Reserva.objects
        .filter(cliente__usuario=usuario)
        .select_related('cliente', 'chacara')
        .order_by('-data_pedido')
    )


def pedidos_pendentes():
    """Pedidos aguardando decisão, do mais antigo para o mais novo."""
    return (
        Reserva.objects
        .filter(status=Reserva.STATUS_PENDENTE)
        .select_related('cliente', 'chacara')
        .order_by('data_pedido')
    )


# ---------------------------------------------------------------------------
# Movimento: histórico de status e recusa automática
# ---------------------------------------------------------------------------

def registrar_historico(reserva, status_anterior, usuario, observacao=''):
    """Grava em HistoricoReserva a mudança de status que acabou de acontecer."""
    return HistoricoReserva.objects.create(
        reserva=reserva,
        status_anterior=status_anterior,
        status_novo=reserva.status,
        alterado_por=usuario,
        observacao=observacao,
    )


def recusar_pendentes_sobrepostas(reserva, usuario):
    """Recusa os pedidos PENDENTES da mesma chácara que conflitam com uma
    reserva recém-confirmada. Devolve quantos foram recusados."""
    agora = timezone.now()
    # select_related: o save() de cada reserva lê chacara.preco_diaria;
    # sem isto seria 1 consulta extra à chácara por pedido recusado.
    pendentes = reserva.sobrepostas(Reserva.STATUS_PENDENTE).select_related('chacara')
    total = 0
    for pedido in pendentes:
        pedido.status = Reserva.STATUS_RECUSADA
        pedido.data_decisao = agora
        pedido.save(update_fields=['status', 'data_decisao'])
        registrar_historico(
            pedido, Reserva.STATUS_PENDENTE, usuario,
            'Recusado automaticamente: período confirmado para outro pedido.',
        )
        total += 1
    return total


# ---------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------

def validar_periodo(data_inicio, data_fim):
    """Mínimo de 1 diária e chegada a partir de hoje."""
    if not data_inicio or not data_fim:
        raise ErroRegraNegocio('Informe a data de chegada e a de saída.')
    if data_fim <= data_inicio:
        raise ErroRegraNegocio(
            'A data de saída deve ser posterior à data de chegada (mínimo de 1 diária).')
    if data_inicio < timezone.localdate():
        raise ErroRegraNegocio('A data de chegada não pode estar no passado.')


def criar_pedido_reserva(cliente, data_inicio, data_fim, observacoes=''):
    """Cria um pedido PENDENTE para a chácara principal e grava o histórico."""
    validar_periodo(data_inicio, data_fim)
    chacara = chacara_principal()
    if chacara is None:
        raise ErroRegraNegocio('Nenhuma chácara cadastrada no sistema.')

    reserva = Reserva(
        cliente=cliente,
        chacara=chacara,
        data_inicio=data_inicio,
        data_fim=data_fim,
        observacoes=observacoes or '',
        status=Reserva.STATUS_PENDENTE,
    )
    if reserva.sobrepostas(Reserva.STATUS_CONFIRMADA).exists():
        raise ErroRegraNegocio(
            'Já existe uma reserva confirmada nesse período. '
            'Consulte a página de disponibilidade e escolha outras datas.'
        )
    with transaction.atomic():
        reserva.save()
        registrar_historico(reserva, '', cliente.usuario, 'Pedido criado pelo cliente.')
    return reserva


def _reserva_pendente_travada(reserva_id):
    """Busca a reserva travando antes a linha da chácara (no PostgreSQL).

    A chácara é travada PRIMEIRO: duas decisões simultâneas sobre a mesma
    chácara passam uma de cada vez e nenhuma delas segura uma reserva que a
    outra precise recusar (o que daria deadlock). No SQLite o
    select_for_update é ignorado (o banco já serializa as escritas).
    Deve ser chamada dentro de transaction.atomic().
    """
    chacara_id = Reserva.objects.filter(pk=reserva_id).values_list('chacara_id', flat=True).first()
    if chacara_id is None:
        raise ErroRegraNegocio('Pedido não encontrado.')
    Chacara.objects.select_for_update().get(pk=chacara_id)
    # Relida depois da trava: o status pode ter mudado enquanto esperávamos.
    reserva = (
        Reserva.objects.select_for_update(of=('self',))
        .select_related('cliente', 'chacara')
        .get(pk=reserva_id)
    )
    if reserva.status != Reserva.STATUS_PENDENTE:
        raise ErroRegraNegocio(f'O pedido #{reserva.pk} não está mais pendente.')
    return reserva


def _exigir_admin(usuario):
    if not usuario_eh_admin(usuario):
        raise ErroRegraNegocio('Apenas a administração pode aprovar ou recusar pedidos.')


def aprovar_reserva(reserva_id, por_usuario, observacao=''):
    """Confirma um pedido pendente e recusa os pendentes que conflitam com ele.

    Devolve ``(reserva, quantidade_recusada_automaticamente)``.
    """
    _exigir_admin(por_usuario)
    with transaction.atomic():
        reserva = _reserva_pendente_travada(reserva_id)
        # O clean() do model não roda no save(): revalida o conflito aqui,
        # já com as linhas travadas.
        if reserva.sobrepostas(Reserva.STATUS_CONFIRMADA).exists():
            raise ErroRegraNegocio(
                f'Não foi possível aprovar o pedido de {reserva.cliente.nome}: '
                'já existe uma reserva confirmada nesse período.'
            )
        reserva.status = Reserva.STATUS_CONFIRMADA
        reserva.data_decisao = timezone.now()
        reserva.save()
        registrar_historico(reserva, Reserva.STATUS_PENDENTE, por_usuario, observacao)
        recusados = recusar_pendentes_sobrepostas(reserva, por_usuario)
    return reserva, recusados


def recusar_reserva(reserva_id, por_usuario, observacao=''):
    """Recusa um pedido pendente."""
    _exigir_admin(por_usuario)
    with transaction.atomic():
        reserva = _reserva_pendente_travada(reserva_id)
        reserva.status = Reserva.STATUS_RECUSADA
        reserva.data_decisao = timezone.now()
        reserva.save(update_fields=['status', 'data_decisao'])
        registrar_historico(reserva, Reserva.STATUS_PENDENTE, por_usuario, observacao)
    return reserva


def cancelar_pedido_cliente(reserva_id, usuario):
    """O próprio cliente cancela o pedido enquanto ele está PENDENTE.

    O registro não é apagado: o status vira CANCELADA e fica no histórico.
    Pedido de outro usuário responde como "não encontrado" (não revela que existe).
    """
    with transaction.atomic():
        try:
            reserva = (
                Reserva.objects.select_for_update()
                .select_related('chacara')
                .get(pk=reserva_id, cliente__usuario=usuario)
            )
        except Reserva.DoesNotExist:
            raise ErroRegraNegocio('Pedido não encontrado.') from None
        if reserva.status != Reserva.STATUS_PENDENTE:
            raise ErroRegraNegocio('Só é possível cancelar pedidos pendentes.')
        reserva.status = Reserva.STATUS_CANCELADA
        reserva.save(update_fields=['status'])
        registrar_historico(reserva, Reserva.STATUS_PENDENTE, usuario, 'Cancelado pelo cliente.')
    return reserva


def garantir_grupo_admin(user):
    """Coloca o usuário no grupo Administradores (criando o grupo se preciso)."""
    grupo, _ = Group.objects.get_or_create(name=GRUPO_ADMIN)
    user.groups.add(grupo)
