import json
from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs

from django.contrib.auth.models import AnonymousUser, Group, User
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ia.excecoes import ErroProvedorIA
from ia.models import RequisicaoIA
from ia.provedores.base import ResultadoProvedor
from ia.services import consumo_do_mes

from . import analise_pedido, services
from .forms import ClienteForm, ReservaClienteForm
from .models import Administrador, Avaliacao, Chacara, Cliente, HistoricoReserva, Reserva
from .templatetags.sitio_tags import estrelas, telefone


def make_chacara(**kwargs):
    defaults = dict(
        nome='Chácara Teste',
        descricao='Descrição',
        preco_diaria=Decimal('500.00'),
        num_quartos=3,
        num_banheiros=2,
    )
    defaults.update(kwargs)
    return Chacara.objects.create(**defaults)


def make_user(username='clienteuser', password='testpass123'):
    return User.objects.create_user(username=username, password=password)


def make_admin_user(username='adminuser', password='testpass123'):
    user = User.objects.create_user(username=username, password=password)
    Administrador.objects.create(nome='Admin Teste', usuario=user)
    return user


class ReservaFluxoTest(TestCase):
    def setUp(self):
        self.chacara = make_chacara()
        self.user = make_user()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=self.user)
        self.admin_user = make_admin_user()
        self.hoje = date.today()

    def test_pedido_cria_com_status_pendente(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
        )
        self.assertEqual(reserva.status, Reserva.STATUS_PENDENTE)

    def test_valor_total_calculado_automaticamente(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
        )
        # 3 dias × R$ 500,00 = R$ 1.500,00
        self.assertEqual(reserva.valor_total, 1500)

    def test_admin_aprova_reserva(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
        )
        self.assertEqual(reserva.status, Reserva.STATUS_PENDENTE)

        c = Client()
        c.login(username='adminuser', password='testpass123')
        response = c.post(reverse('reserva_aprovar', args=[reserva.pk]))
        self.assertRedirects(response, reverse('pedidos_pendentes'))

        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.STATUS_CONFIRMADA)
        self.assertIsNotNone(reserva.data_decisao)

    def test_reserva_confirmada_aparece_no_calendario(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
            status=Reserva.STATUS_CONFIRMADA,
        )
        c = Client()
        response = c.get(reverse('calendario_reservas'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(reserva, response.context['reservas'])

    def test_reserva_pendente_nao_aparece_no_calendario(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
        )
        c = Client()
        response = c.get(reverse('calendario_reservas'))
        self.assertNotIn(reserva, response.context['reservas'])

    def test_sobreposicao_com_confirmada_invalida(self):
        Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=15),
            status=Reserva.STATUS_CONFIRMADA,
        )
        nova = Reserva(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=12),
            data_fim=self.hoje + timedelta(days=17),
        )
        with self.assertRaises(ValidationError):
            nova.full_clean()

    def test_data_fim_anterior_a_inicio_invalida(self):
        reserva = Reserva(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=15),
            data_fim=self.hoje + timedelta(days=10),
        )
        with self.assertRaises(ValidationError):
            reserva.full_clean()

    def test_admin_recusa_reserva(self):
        reserva = Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
        )
        c = Client()
        c.login(username='adminuser', password='testpass123')
        c.post(reverse('reserva_recusar', args=[reserva.pk]))
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.STATUS_RECUSADA)

    def test_cliente_nao_autenticado_nao_acessa_reserva_create(self):
        c = Client()
        response = c.get(reverse('reserva_create'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('reserva_create')}")


class AcessoPorDonoTest(TestCase):
    """Garante que cada cliente só mexe nos próprios dados/pedidos."""

    def setUp(self):
        self.chacara = make_chacara()
        self.user = make_user(username='dono')
        self.cliente = Cliente.objects.create(nome='Dono', telefone='11999990000', usuario=self.user)
        self.outro_user = make_user(username='intruso')
        self.outro_cliente = Cliente.objects.create(nome='Intruso', telefone='11888887777', usuario=self.outro_user)
        self.hoje = date.today()

    def _reserva(self, status=Reserva.STATUS_PENDENTE):
        return Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=10),
            data_fim=self.hoje + timedelta(days=13),
            status=status,
        )

    def test_cliente_nao_edita_cadastro_de_outro(self):
        c = Client()
        c.login(username='intruso', password='testpass123')
        response = c.get(reverse('cliente_update', args=[self.cliente.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cliente_ve_propria_reserva(self):
        reserva = self._reserva()
        c = Client()
        c.login(username='dono', password='testpass123')
        response = c.get(reverse('minha_reserva_detail', args=[reserva.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cliente_nao_ve_reserva_de_outro(self):
        reserva = self._reserva()
        c = Client()
        c.login(username='intruso', password='testpass123')
        response = c.get(reverse('minha_reserva_detail', args=[reserva.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cliente_nao_edita_reserva_confirmada(self):
        reserva = self._reserva(status=Reserva.STATUS_CONFIRMADA)
        c = Client()
        c.login(username='dono', password='testpass123')
        response = c.get(reverse('minha_reserva_update', args=[reserva.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cliente_sem_permissao_nao_acessa_area_admin(self):
        c = Client()
        c.login(username='dono', password='testpass123')
        response = c.get(reverse('pedidos_pendentes'))
        # GroupRequiredMixin com raise_exception=False redireciona ao login.
        self.assertEqual(response.status_code, 302)


class FiltroListagensTest(TestCase):
    """Conferência da skill django-filter-listagens nas listas de reserva."""

    def setUp(self):
        self.chacara = make_chacara()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        self.outro_cliente = Cliente.objects.create(
            nome='Maria Souza', telefone='11888887777', usuario=make_user(username='maria'))
        make_admin_user()
        self.hoje = date.today()

    def _reserva(self, cliente=None, dias=10, status=Reserva.STATUS_PENDENTE):
        inicio = self.hoje + timedelta(days=dias)
        return Reserva.objects.create(
            cliente=cliente or self.cliente,
            chacara=self.chacara,
            data_inicio=inicio,
            data_fim=inicio + timedelta(days=2),
            status=status,
        )

    def _navegador(self, username):
        c = Client()
        c.login(username=username, password='testpass123')
        return c

    def test_lista_sem_parametros_mostra_so_as_reservas_do_cliente(self):
        minha = self._reserva()
        alheia = self._reserva(cliente=self.outro_cliente)
        response = self._navegador('clienteuser').get(reverse('minhas_reservas'))
        self.assertIn(minha, response.context['reservas'])
        self.assertNotIn(alheia, response.context['reservas'])

    def test_filtro_nao_mostra_reservas_de_outro_cliente(self):
        self._reserva(cliente=self.outro_cliente, status=Reserva.STATUS_CONFIRMADA)
        confirmada = self._reserva(dias=20, status=Reserva.STATUS_CONFIRMADA)
        self._reserva()
        response = self._navegador('clienteuser').get(
            reverse('minhas_reservas'), {'status': Reserva.STATUS_CONFIRMADA})
        self.assertEqual(list(response.context['reservas']), [confirmada])

    def test_busca_por_parte_do_nome_do_cliente(self):
        joao = self._reserva()
        self._reserva(cliente=self.outro_cliente)
        response = self._navegador('adminuser').get(reverse('pedidos_pendentes'), {'cliente': 'SILV'})
        self.assertEqual(list(response.context['reservas']), [joao])

    def test_faixa_de_datas_inclui_o_ultimo_dia(self):
        reserva = self._reserva()
        hoje = timezone.localdate()  # data_pedido é DateTimeField
        response = self._navegador('adminuser').get(reverse('pedidos_pendentes'), {
            'data_inicio_max': reserva.data_inicio.isoformat(),
            'data_pedido_min': hoje.isoformat(),
            'data_pedido_max': hoje.isoformat(),
        })
        self.assertEqual(list(response.context['reservas']), [reserva])

    def test_paginacao_mantem_a_busca(self):
        for dias in range(11):
            self._reserva(dias=dias)
        self._reserva(cliente=self.outro_cliente)
        c = self._navegador('adminuser')
        url = reverse('pedidos_pendentes')

        response = c.get(url, {'cliente': 'silva'})
        self.assertContains(response, 'Página 1 de 2')
        self.assertContains(response, 'href="?cliente=silva&amp;page=2" rel="next">Próxima</a>')
        self.assertContains(response, '<span class="page-link">Anterior</span>')  # desabilitado

        response = c.get(url, {'cliente': 'silva', 'page': 2})
        self.assertContains(response, 'href="?cliente=silva&amp;page=1" rel="prev">Anterior</a>')
        self.assertContains(response, '<span class="page-link">Próxima</span>')  # desabilitado
        self.assertEqual([r.cliente for r in response.context['reservas']], [self.cliente])

    def test_limpar_volta_para_a_lista_sem_parametros(self):
        url = reverse('minhas_reservas')
        response = self._navegador('clienteuser').get(url, {'status': Reserva.STATUS_PENDENTE})
        self.assertContains(response, f'<a href="{url}" class="btn btn-outline-secondary">')

    def test_disponibilidade_publica_nao_filtra_por_cliente(self):
        response = Client().get(reverse('calendario_reservas'))
        self.assertIn('data_inicio', response.context['filter'].form.fields)
        self.assertNotIn('cliente', response.context['filter'].form.fields)


class PluginsJQueryTest(TestCase):
    """jQuery Mask, Bootbox e DataTables carregados no modelo.html e
    inicializados em static/js/site.js."""

    SCRIPTS_EM_ORDEM = [
        'ajax/libs/jquery/3.7.1/jquery.min.js',
        'ajax/libs/jquery.mask/1.14.16/jquery.mask.min.js',
        'ajax/libs/bootbox.js/6.0.0/bootbox.min.js',
        'ajax/libs/datatables.net/2.1.8/dataTables.min.js',
        'ajax/libs/datatables.net-bs5/2.1.8/dataTables.bootstrap5.min.js',
        'ajax/libs/bootstrap/5.3.3/js/bootstrap.bundle.min.js',
        '/static/js/site.js',
    ]

    def setUp(self):
        self.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        make_admin_user()
        inicio = timezone.localdate() + timedelta(days=10)
        self.reserva = Reserva.objects.create(
            cliente=self.cliente, chacara=self.chacara, data_inicio=inicio, data_fim=inicio + timedelta(days=3))
        self.cli = Client()
        self.cli.login(username='clienteuser', password='testpass123')
        self.admin = Client()
        self.admin.login(username='adminuser', password='testpass123')

    def test_modelo_carrega_jquery_plugins_bootstrap_e_site_js_nessa_ordem(self):
        html = Client().get(reverse('index')).content.decode()
        posicoes = [html.index(script) for script in self.SCRIPTS_EM_ORDEM]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertIn('cdnjs.cloudflare.com/ajax/libs/datatables.net-bs5/2.1.8/dataTables.bootstrap5.min.css', html)

    def test_mascara_de_telefone_no_cadastro_e_em_meus_dados(self):
        self.assertContains(Client().get(reverse('signup')), 'class="mascara-telefone')
        response = self.cli.get(reverse('cliente_update', args=[self.cliente.pk]))
        self.assertContains(response, 'class="mascara-telefone')

    def test_bootbox_nos_formularios_de_decisao_exclusao_e_cancelamento(self):
        response = self.admin.get(reverse('pedidos_pendentes'))
        self.assertContains(response, 'data-confirmar="Aprovar o pedido de João Silva', count=1)
        self.assertContains(response, 'data-confirmar="Recusar o pedido de João Silva', count=1)
        for url in (reverse('reserva_aprovar', args=[self.reserva.pk]),
                    reverse('reserva_recusar', args=[self.reserva.pk]),
                    reverse('reserva_delete', args=[self.reserva.pk])):
            with self.subTest(url):
                self.assertContains(self.admin.get(url), 'data-confirmar="')
        self.assertContains(self.cli.get(reverse('minha_reserva_delete', args=[self.reserva.pk])), 'data-confirmar="')

    def test_listas_paginadas_no_servidor_nao_usam_datatables(self):
        self.reserva.status = Reserva.STATUS_CONFIRMADA
        self.reserva.save()
        paginas = [
            (self.cli, 'minhas_reservas'), (self.admin, 'pedidos_pendentes'),
            (self.admin, 'reservas_todas'), (Client(), 'calendario_reservas'),
        ]
        for navegador, nome in paginas:
            with self.subTest(nome):
                response = navegador.get(reverse(nome))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'table-datatable')


# ---------------------------------------------------------------------------
# 3º trimestre: movimento, filtros, paginação, telefone e validação de datas
# ---------------------------------------------------------------------------

class MovimentoReservaTest(TestCase):
    """form_valid das views gravando HistoricoReserva e recusando conflitos."""

    def setUp(self):
        self.chacara = make_chacara()
        self.user = make_user()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=self.user)
        self.outro = Cliente.objects.create(
            nome='Maria Souza', telefone='11888887777', usuario=make_user(username='maria'))
        self.admin_user = make_admin_user()
        self.hoje = date.today()
        self.admin = Client()
        self.admin.login(username='adminuser', password='testpass123')

    def _reserva(self, cliente=None, inicio=10, fim=13, status=Reserva.STATUS_PENDENTE):
        return Reserva.objects.create(
            cliente=cliente or self.cliente,
            chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=inicio),
            data_fim=self.hoje + timedelta(days=fim),
            status=status,
        )

    def test_aprovar_recusa_pendentes_sobrepostos_e_grava_historico(self):
        aprovada = self._reserva(inicio=10, fim=13)
        conflitante = self._reserva(cliente=self.outro, inicio=12, fim=15)
        # Começa no dia da saída da aprovada: não conflita.
        vizinha = self._reserva(cliente=self.outro, inicio=13, fim=16)

        response = self.admin.post(reverse('reserva_aprovar', args=[aprovada.pk]))
        self.assertRedirects(response, reverse('pedidos_pendentes'))

        for r in (aprovada, conflitante, vizinha):
            r.refresh_from_db()
        self.assertEqual(aprovada.status, Reserva.STATUS_CONFIRMADA)
        self.assertEqual(conflitante.status, Reserva.STATUS_RECUSADA)
        self.assertIsNotNone(conflitante.data_decisao)
        self.assertEqual(vizinha.status, Reserva.STATUS_PENDENTE)

        h = aprovada.historico.get()
        self.assertEqual((h.status_anterior, h.status_novo), (Reserva.STATUS_PENDENTE, Reserva.STATUS_CONFIRMADA))
        self.assertEqual(h.alterado_por, self.admin_user)
        h = conflitante.historico.get()
        self.assertEqual(h.status_novo, Reserva.STATUS_RECUSADA)
        self.assertIn('Recusado automaticamente', h.observacao)
        self.assertFalse(vizinha.historico.exists())

    def test_nao_aprova_pedido_que_conflita_com_confirmada(self):
        self._reserva(cliente=self.outro, inicio=10, fim=15, status=Reserva.STATUS_CONFIRMADA)
        pedido = self._reserva(inicio=12, fim=14)

        response = self.admin.post(reverse('reserva_aprovar', args=[pedido.pk]), follow=True)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_PENDENTE)
        self.assertFalse(pedido.historico.exists())
        self.assertContains(response, 'já existe uma reserva confirmada nesse período')
        self.assertContains(response, 'alert alert-danger')  # MESSAGE_TAGS: error -> danger

    def test_tela_de_aprovacao_registra_observacao(self):
        pedido = self._reserva()
        self.assertEqual(self.admin.get(reverse('reserva_aprovar', args=[pedido.pk])).status_code, 200)
        self.admin.post(reverse('reserva_aprovar', args=[pedido.pk]), {'observacao': 'Sinal pago.'})
        self.assertEqual(pedido.historico.get().observacao, 'Sinal pago.')

    def test_recusar_grava_historico(self):
        pedido = self._reserva()
        self.admin.post(reverse('reserva_recusar', args=[pedido.pk]))
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_RECUSADA)
        self.assertIsNotNone(pedido.data_decisao)
        self.assertEqual(pedido.historico.get().status_novo, Reserva.STATUS_RECUSADA)

    def test_cliente_cancelando_muda_status_e_nao_apaga(self):
        pedido = self._reserva()
        c = Client()
        c.login(username='clienteuser', password='testpass123')
        response = c.post(reverse('minha_reserva_delete', args=[pedido.pk]))
        self.assertRedirects(response, reverse('minhas_reservas'))

        pedido.refresh_from_db()  # continua existindo
        self.assertEqual(pedido.status, Reserva.STATUS_CANCELADA)
        h = pedido.historico.get()
        self.assertEqual((h.status_anterior, h.status_novo), (Reserva.STATUS_PENDENTE, Reserva.STATUS_CANCELADA))
        self.assertEqual(h.alterado_por, self.user)

    def test_criar_pedido_grava_historico_inicial(self):
        c = Client()
        c.login(username='clienteuser', password='testpass123')
        c.post(reverse('reserva_create'), {
            'data_inicio': (self.hoje + timedelta(days=20)).isoformat(),
            'data_fim': (self.hoje + timedelta(days=22)).isoformat(),
            'observacoes': '',
        })
        reserva = Reserva.objects.get(cliente=self.cliente)
        h = reserva.historico.get()
        self.assertEqual((h.status_anterior, h.status_novo), ('', Reserva.STATUS_PENDENTE))
        self.assertEqual(h.alterado_por, self.user)

    def test_edicao_admin_que_muda_status_grava_historico(self):
        pedido = self._reserva()
        self.admin.post(reverse('reserva_update', args=[pedido.pk]), {
            'chacara': self.chacara.pk,
            'data_inicio': pedido.data_inicio.isoformat(),
            'data_fim': pedido.data_fim.isoformat(),
            'observacoes': '',
            'status': Reserva.STATUS_CONFIRMADA,
        })
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_CONFIRMADA)
        self.assertIsNotNone(pedido.data_decisao)
        self.assertEqual(pedido.historico.get().status_novo, Reserva.STATUS_CONFIRMADA)

    def test_historico_aparece_no_detalhe(self):
        pedido = self._reserva()
        self.admin.post(reverse('reserva_aprovar', args=[pedido.pk]))
        response = self.admin.get(reverse('reserva_detail', args=[pedido.pk]))
        self.assertContains(response, 'Histórico')
        self.assertContains(response, 'Confirmada</strong>')

    def test_admin_sem_perfil_cliente_nao_faz_pedido(self):
        response = self.admin.get(reverse('reserva_create'), follow=True)
        self.assertRedirects(response, reverse('pedidos_pendentes'))
        self.assertContains(response, 'Apenas clientes fazem pedidos')

    def test_admin_so_pelo_grupo_ve_detalhe_e_menu(self):
        user = make_user(username='dogrupo')
        user.groups.add(Group.objects.get_or_create(name='Administradores')[0])
        pedido = self._reserva()
        c = Client()
        c.login(username='dogrupo', password='testpass123')
        response = c.get(reverse('reserva_detail', args=[pedido.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('reservas_todas'))  # menu Admin + botão Voltar


class FiltrosTerceiroTrimestreTest(TestCase):
    """django-filter com icontains, exact, gte e lte."""

    def setUp(self):
        self.chacara = make_chacara()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        self.outro = Cliente.objects.create(
            nome='Maria Souza', telefone='11888887777', usuario=make_user(username='maria'))
        make_admin_user()
        self.hoje = date.today()

    def _reserva(self, cliente=None, dias=10, status=Reserva.STATUS_PENDENTE):
        inicio = self.hoje + timedelta(days=dias)
        return Reserva.objects.create(
            cliente=cliente or self.cliente, chacara=self.chacara,
            data_inicio=inicio, data_fim=inicio + timedelta(days=1), status=status,
        )

    def _navegador(self, username):
        c = Client()
        c.login(username=username, password='testpass123')
        return c

    def test_minhas_reservas_status_exact_so_do_proprio_cliente(self):
        minha = self._reserva(status=Reserva.STATUS_CONFIRMADA)
        self._reserva(cliente=self.outro, dias=20, status=Reserva.STATUS_CONFIRMADA)
        self._reserva(dias=30)
        response = self._navegador('clienteuser').get(
            reverse('minhas_reservas'), {'status': Reserva.STATUS_CONFIRMADA})
        self.assertEqual(list(response.context['reservas']), [minha])

    def test_minhas_reservas_intervalo_de_datas(self):
        self._reserva(dias=5)
        dentro = self._reserva(dias=10)
        self._reserva(dias=15)
        dia = (self.hoje + timedelta(days=10)).isoformat()
        response = self._navegador('clienteuser').get(
            reverse('minhas_reservas'), {'data_inicio__gte': dia, 'data_inicio__lte': dia})
        self.assertEqual(list(response.context['reservas']), [dentro])

    def test_todas_reservas_nome_icontains(self):
        joao = self._reserva()
        self._reserva(cliente=self.outro)
        response = self._navegador('adminuser').get(reverse('reservas_todas'), {'cliente__nome': 'SILV'})
        self.assertEqual(list(response.context['reservas']), [joao])

    def test_todas_reservas_intervalo_gte_lte_inclui_os_limites(self):
        self._reserva(dias=4)
        a = self._reserva(dias=5)
        b = self._reserva(cliente=self.outro, dias=8)
        self._reserva(dias=9)
        response = self._navegador('adminuser').get(reverse('reservas_todas'), {
            'data_inicio__gte': (self.hoje + timedelta(days=5)).isoformat(),
            'data_inicio__lte': (self.hoje + timedelta(days=8)).isoformat(),
        })
        # ordering = ['-data_inicio']
        self.assertEqual(list(response.context['reservas']), [b, a])

    def test_todas_reservas_status_exact(self):
        self._reserva()
        recusada = self._reserva(dias=20, status=Reserva.STATUS_RECUSADA)
        response = self._navegador('adminuser').get(reverse('reservas_todas'), {'status': 'RECUSADA'})
        self.assertEqual(list(response.context['reservas']), [recusada])

    def test_todas_reservas_restrita_ao_admin(self):
        response = self._navegador('clienteuser').get(reverse('reservas_todas'))
        self.assertEqual(response.status_code, 302)

    def test_paginacao_preserva_os_filtros(self):
        for dias in range(11):
            self._reserva(dias=dias)
        self._reserva(cliente=self.outro)
        c = self._navegador('adminuser')
        url = reverse('reservas_todas')
        filtros = {'cliente__nome': 'silva', 'status': 'PENDENTE'}

        response = c.get(url, filtros)
        self.assertContains(response, 'Página 1 de 2')
        self.assertContains(response, 'href="?cliente__nome=silva&amp;status=PENDENTE&amp;page=2" rel="next">Próxima</a>')

        response = c.get(url, {**filtros, 'page': 2})
        self.assertContains(response, 'href="?cliente__nome=silva&amp;status=PENDENTE&amp;page=1" rel="prev">Anterior</a>')
        self.assertEqual(len(response.context['reservas']), 1)


class UrlComParametrosTagTest(TestCase):
    """Templatetag própria website/templatetags/url_params.py."""

    def _render(self, query, trecho):
        request = RequestFactory().get('/lista/', query)
        return Template('{% load url_params %}' + trecho).render(Context({'request': request}))

    def _query(self, html):
        self.assertTrue(html.startswith('?'), html)
        return parse_qs(unescape(html)[1:], keep_blank_values=True)

    def test_troca_a_pagina_e_preserva_todos_os_filtros(self):
        html = self._render(
            {'status': 'PENDENTE', 'cliente__nome': 'João Silva', 'data_inicio__gte': '', 'page': '1'},
            '{% url_com_parametros page=3 %}')
        self.assertEqual(self._query(html), {
            'status': ['PENDENTE'], 'cliente__nome': ['João Silva'],
            'data_inicio__gte': [''], 'page': ['3'],
        })

    def test_insere_a_pagina_quando_nao_existe(self):
        html = self._render({'status': 'CONFIRMADA'}, '{% url_com_parametros page=2 %}')
        self.assertEqual(self._query(html), {'status': ['CONFIRMADA'], 'page': ['2']})

    def test_none_remove_o_parametro(self):
        html = self._render({'status': 'PENDENTE', 'page': '4'}, '{% url_com_parametros page=None %}')
        self.assertEqual(self._query(html), {'status': ['PENDENTE']})

    def test_preserva_parametro_com_varios_valores(self):
        html = self._render({'status': ['PENDENTE', 'CONFIRMADA']}, '{% url_com_parametros page=2 %}')
        self.assertEqual(self._query(html)['status'], ['PENDENTE', 'CONFIRMADA'])

    def test_valor_malicioso_sai_codificado(self):
        html = self._render({'cliente__nome': '"><script>alert(1)</script>'}, '{% url_com_parametros page=2 %}')
        self.assertNotIn('<script>', html)
        self.assertNotIn('"', html)
        self.assertEqual(self._query(html)['cliente__nome'], ['"><script>alert(1)</script>'])

    def test_paginas_proximas_com_reticencias(self):
        paginator = Paginator(list(range(200)), 10)  # 20 páginas
        html = Template(
            '{% load url_params %}{% paginas_proximas page_obj as p %}{{ p|join:"," }}'
        ).render(Context({'page_obj': paginator.page(7)}))
        self.assertEqual(html, '1,…,5,6,7,8,9,…,20')

    def test_partial_usa_a_tag_nos_numeros(self):
        cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        hoje = timezone.localdate()
        for dias in range(25):
            inicio = hoje + timedelta(days=dias * 3 + 1)
            Reserva.objects.create(cliente=cliente, chacara=chacara,
                                   data_inicio=inicio, data_fim=inicio + timedelta(days=1))
        c = Client()
        c.login(username='clienteuser', password='testpass123')
        response = c.get(reverse('minhas_reservas'), {'status': 'PENDENTE', 'page': 2})
        self.assertContains(response, '<li class="page-item active" aria-current="page"><span class="page-link">2</span></li>')
        self.assertContains(response, 'href="?status=PENDENTE&amp;page=3">3</a>')
        self.assertContains(response, 'href="?status=PENDENTE&amp;page=1">1</a>')


class AlterarSenhaTest(TestCase):
    """O admin do Django também tem registration/password_change_form.html e,
    por vir antes no INSTALLED_APPS, tomava o lugar da tela do site."""

    def test_usa_a_tela_do_site(self):
        user = make_user()
        c = Client()
        c.force_login(user)
        response = c.get(reverse('password_change'))
        self.assertTemplateUsed(response, 'website/senha_alterar.html')
        self.assertContains(response, '<title>Alterar Senha — Sítio de Lurdes</title>', html=True)
        response = c.post(reverse('password_change'), {
            'old_password': 'testpass123', 'new_password1': 'NovaSenha!2026', 'new_password2': 'NovaSenha!2026'},
            follow=True)
        self.assertTemplateUsed(response, 'website/senha_alterada.html')


class TelefoneTest(TestCase):
    """Máscara (00) 00000-0000 no navegador; só dígitos no banco."""

    def test_cadastro_aceita_telefone_mascarado_e_salva_so_digitos(self):
        response = Client().post(reverse('signup'), {
            'username': 'novo', 'email': 'novo@exemplo.com',
            'password1': 'SenhaForte!2026', 'password2': 'SenhaForte!2026',
            'nome': 'Cliente Novo', 'telefone': '(46) 99999-8888',
        })
        self.assertRedirects(response, reverse('index'))
        self.assertEqual(Cliente.objects.get(usuario__username='novo').telefone, '46999998888')

    def test_meus_dados_aceita_telefone_mascarado(self):
        cliente = Cliente.objects.create(nome='João', telefone='11999990000', usuario=make_user())
        c = Client()
        c.login(username='clienteuser', password='testpass123')
        c.post(reverse('cliente_update', args=[cliente.pk]), {'nome': 'João', 'telefone': '(46) 3523-1234'})
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefone, '4635231234')

    def test_telefone_incompleto_e_invalido(self):
        form = ClienteForm(data={'nome': 'X', 'telefone': '(46) 9999'})
        self.assertFalse(form.is_valid())
        self.assertIn('telefone', form.errors)

    def test_filtro_telefone_formata(self):
        self.assertEqual(telefone('46999998888'), '(46) 99999-8888')
        self.assertEqual(telefone('4635231234'), '(46) 3523-1234')


class ValidacaoDatasPedidoTest(TestCase):
    def setUp(self):
        self.chacara = make_chacara()
        self.cliente = Cliente.objects.create(nome='João', telefone='11999990000', usuario=make_user())
        self.hoje = date.today()

    def _form(self, inicio, fim):
        return ReservaClienteForm(data={
            'data_inicio': inicio.isoformat(), 'data_fim': fim.isoformat(), 'observacoes': ''})

    def test_data_no_passado_e_invalida(self):
        form = self._form(self.hoje - timedelta(days=1), self.hoje + timedelta(days=2))
        self.assertFalse(form.is_valid())
        self.assertIn('data_inicio', form.errors)

    def test_saida_igual_a_chegada_e_invalida(self):
        dia = self.hoje + timedelta(days=5)
        form = self._form(dia, dia)
        self.assertFalse(form.is_valid())
        self.assertIn('posterior', form.errors['data_fim'][0])

    def test_model_exige_no_minimo_uma_diaria(self):
        dia = self.hoje + timedelta(days=5)
        reserva = Reserva(cliente=self.cliente, chacara=self.chacara, data_inicio=dia, data_fim=dia)
        with self.assertRaises(ValidationError):
            reserva.full_clean()


class CalendarioEventosTest(TestCase):
    """Eventos do FullCalendar montados no get_context_data."""

    def setUp(self):
        self.chacara = make_chacara()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        make_admin_user()
        hoje = date.today()
        self.futura = Reserva.objects.create(
            cliente=self.cliente, chacara=self.chacara, status=Reserva.STATUS_CONFIRMADA,
            data_inicio=hoje + timedelta(days=3), data_fim=hoje + timedelta(days=5))
        Reserva.objects.create(  # já terminou: fica fora do calendário
            cliente=self.cliente, chacara=self.chacara, status=Reserva.STATUS_CONFIRMADA,
            data_inicio=hoje - timedelta(days=10), data_fim=hoje - timedelta(days=8))
        Reserva.objects.create(  # pendente: fica fora do calendário
            cliente=self.cliente, chacara=self.chacara,
            data_inicio=hoje + timedelta(days=20), data_fim=hoje + timedelta(days=22))

    def test_visitante_ve_so_reservado(self):
        response = Client().get(reverse('calendario_reservas'))
        self.assertEqual(response.context['eventos'], [{
            'title': 'Reservado',
            'start': self.futura.data_inicio.isoformat(),
            'end': self.futura.data_fim.isoformat(),
            'allDay': True,
        }])
        self.assertContains(response, 'id="eventos-data"')
        self.assertNotContains(response, 'João Silva')

    def test_admin_ve_nome_do_cliente(self):
        c = Client()
        c.login(username='adminuser', password='testpass123')
        response = c.get(reverse('calendario_reservas'))
        self.assertEqual(response.context['eventos'][0]['title'], 'Reservado — João Silva')


# ---------------------------------------------------------------------------
# website/services.py — regras de negócio compartilhadas (site e bot)
# ---------------------------------------------------------------------------

class ServicesTest(TestCase):
    def setUp(self):
        # A migration 0003 já cria a chácara do sistema; os testes usam ela.
        self.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.chacara.preco_diaria = Decimal('500.00')
        self.chacara.save()
        self.user = make_user()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=self.user)
        self.outro_user = make_user(username='maria')
        self.outro = Cliente.objects.create(nome='Maria Souza', telefone='11888887777', usuario=self.outro_user)
        self.admin_user = make_admin_user()
        self.hoje = timezone.localdate()

    def _reserva(self, cliente=None, inicio=10, fim=13, status=Reserva.STATUS_PENDENTE):
        return Reserva.objects.create(
            cliente=cliente or self.cliente, chacara=self.chacara,
            data_inicio=self.hoje + timedelta(days=inicio),
            data_fim=self.hoje + timedelta(days=fim), status=status,
        )

    # -- consultas -----------------------------------------------------------

    def test_chacara_principal_e_a_primeira_cadastrada(self):
        make_chacara(nome='Outra')
        self.assertEqual(services.chacara_principal(), self.chacara)

    def test_chacara_principal_sem_cadastro(self):
        Chacara.objects.all().delete()
        self.assertIsNone(services.chacara_principal())

    def test_usuario_eh_admin(self):
        do_grupo = make_user(username='dogrupo')
        do_grupo.groups.add(Group.objects.get_or_create(name='Administradores')[0])
        super_user = User.objects.create_superuser('raiz', 'raiz@exemplo.com', 'testpass123')
        self.assertTrue(services.usuario_eh_admin(self.admin_user))   # perfil Administrador
        self.assertTrue(services.usuario_eh_admin(do_grupo))          # grupo
        self.assertTrue(services.usuario_eh_admin(super_user))        # superuser
        self.assertFalse(services.usuario_eh_admin(self.user))
        self.assertFalse(services.usuario_eh_admin(AnonymousUser()))
        self.assertFalse(services.usuario_eh_admin(None))

    def test_admin_required_mixin_usa_a_mesma_regra(self):
        do_grupo = make_user(username='dogrupo')
        do_grupo.groups.add(Group.objects.get_or_create(name='Administradores')[0])
        c = Client()
        c.login(username='dogrupo', password='testpass123')
        self.assertEqual(c.get(reverse('pedidos_pendentes')).status_code, 200)

    def test_datas_confirmadas_futuras_so_datas_e_so_futuras(self):
        futura = self._reserva(inicio=5, fim=7, status=Reserva.STATUS_CONFIRMADA)
        self._reserva(inicio=-10, fim=-8, status=Reserva.STATUS_CONFIRMADA)  # já passou
        self._reserva(inicio=20, fim=22)                                       # pendente
        self.assertEqual(services.datas_confirmadas_futuras(), [(futura.data_inicio, futura.data_fim)])

    def test_reservas_do_usuario_e_pedidos_pendentes(self):
        minha = self._reserva()
        alheia = self._reserva(cliente=self.outro, inicio=20, fim=22)
        self._reserva(inicio=30, fim=32, status=Reserva.STATUS_CONFIRMADA)
        self.assertNotIn(alheia, services.reservas_do_usuario(self.user))
        self.assertIn(minha, services.reservas_do_usuario(self.user))
        self.assertEqual(list(services.pedidos_pendentes()), [minha, alheia])
        with self.assertNumQueries(1):  # select_related: cliente e chácara no mesmo SELECT
            [(r.cliente.nome, r.chacara.nome) for r in services.pedidos_pendentes()]

    # -- criar_pedido_reserva -----------------------------------------------

    def test_criar_pedido_reserva(self):
        reserva = services.criar_pedido_reserva(
            self.cliente, self.hoje + timedelta(days=3), self.hoje + timedelta(days=5), 'Aniversário')
        self.assertEqual(reserva.status, Reserva.STATUS_PENDENTE)
        self.assertEqual(reserva.chacara, self.chacara)
        self.assertEqual(reserva.valor_total, Decimal('1000.00'))
        self.assertEqual(reserva.historico.get().alterado_por, self.user)

    def test_criar_pedido_valida_datas_e_conflito(self):
        self._reserva(cliente=self.outro, inicio=10, fim=15, status=Reserva.STATUS_CONFIRMADA)
        casos = [
            (5, 5, 'mínimo de 1 diária'),
            (6, 4, 'mínimo de 1 diária'),
            (-1, 2, 'passado'),
            (12, 14, 'Já existe uma reserva confirmada'),
        ]
        for inicio, fim, mensagem in casos:
            with self.subTest(inicio=inicio, fim=fim):
                with self.assertRaisesMessage(services.ErroRegraNegocio, mensagem):
                    services.criar_pedido_reserva(
                        self.cliente, self.hoje + timedelta(days=inicio), self.hoje + timedelta(days=fim))
        # O dia de saída da confirmada fica livre para uma nova entrada.
        services.criar_pedido_reserva(self.cliente, self.hoje + timedelta(days=15), self.hoje + timedelta(days=16))
        self.assertEqual(Reserva.objects.filter(cliente=self.cliente).count(), 1)

    # -- aprovar / recusar ---------------------------------------------------

    def test_aprovar_reserva(self):
        pedido = self._reserva(inicio=10, fim=13)
        conflitante = self._reserva(cliente=self.outro, inicio=12, fim=15)
        reserva, recusados = services.aprovar_reserva(pedido.pk, self.admin_user, 'Sinal pago.')
        self.assertEqual(reserva.status, Reserva.STATUS_CONFIRMADA)
        self.assertIsNotNone(reserva.data_decisao)
        self.assertEqual(recusados, 1)
        conflitante.refresh_from_db()
        self.assertEqual(conflitante.status, Reserva.STATUS_RECUSADA)
        self.assertEqual(reserva.historico.get().observacao, 'Sinal pago.')

    def test_aprovar_exige_admin_pendente_e_sem_conflito(self):
        pedido = self._reserva(inicio=10, fim=13)
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'Apenas a administração'):
            services.aprovar_reserva(pedido.pk, self.user)
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'não encontrado'):
            services.aprovar_reserva(999999, self.admin_user)

        self._reserva(cliente=self.outro, inicio=11, fim=12, status=Reserva.STATUS_CONFIRMADA)
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'já existe uma reserva confirmada'):
            services.aprovar_reserva(pedido.pk, self.admin_user)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_PENDENTE)
        self.assertIsNone(pedido.data_decisao)

        recusado = self._reserva(inicio=40, fim=42, status=Reserva.STATUS_RECUSADA)
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'não está mais pendente'):
            services.aprovar_reserva(recusado.pk, self.admin_user)

    def test_recusar_reserva(self):
        pedido = self._reserva()
        with self.assertRaises(services.ErroRegraNegocio):
            services.recusar_reserva(pedido.pk, self.user)
        reserva = services.recusar_reserva(pedido.pk, self.admin_user, 'Data indisponível.')
        self.assertEqual(reserva.status, Reserva.STATUS_RECUSADA)
        self.assertIsNotNone(reserva.data_decisao)
        self.assertEqual(reserva.historico.get().observacao, 'Data indisponível.')
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'não está mais pendente'):
            services.recusar_reserva(pedido.pk, self.admin_user)

    # -- cancelar_pedido_cliente ---------------------------------------------

    def test_cancelar_pedido_cliente(self):
        pedido = self._reserva()
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'não encontrado'):
            services.cancelar_pedido_cliente(pedido.pk, self.outro_user)  # não é o dono
        reserva = services.cancelar_pedido_cliente(pedido.pk, self.user)
        self.assertEqual(reserva.status, Reserva.STATUS_CANCELADA)
        self.assertEqual(reserva.historico.get().alterado_por, self.user)

    def test_cancelar_so_pendente(self):
        confirmada = self._reserva(status=Reserva.STATUS_CONFIRMADA)
        with self.assertRaisesMessage(services.ErroRegraNegocio, 'Só é possível cancelar pedidos pendentes'):
            services.cancelar_pedido_cliente(confirmada.pk, self.user)


# ---------------------------------------------------------------------------
# Framework de mensagens: toda Create/Update/Delete e toda decisão avisam
# ---------------------------------------------------------------------------

def ultima_mensagem(response):
    """Texto da mensagem mais recente (sem uma página renderizada entre os
    POSTs, as mensagens anteriores continuam pendentes no cookie)."""
    return [str(m) for m in get_messages(response.wsgi_request)][-1]


class MensagensTest(TestCase):
    def setUp(self):
        self.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.user = make_user()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=self.user)
        self.admin_user = make_admin_user()
        self.hoje = timezone.localdate()
        self.cli = Client()
        self.cli.login(username='clienteuser', password='testpass123')
        self.admin = Client()
        self.admin.login(username='adminuser', password='testpass123')

    def _reserva(self, inicio=10, fim=13, status=Reserva.STATUS_PENDENTE):
        return Reserva.objects.create(
            cliente=self.cliente, chacara=self.chacara, status=status,
            data_inicio=self.hoje + timedelta(days=inicio), data_fim=self.hoje + timedelta(days=fim))

    def test_alert_dismissivel_abaixo_da_navbar(self):
        pedido = self._reserva()
        response = self.admin.post(reverse('reserva_recusar', args=[pedido.pk]), follow=True)
        self.assertContains(response, 'alert alert-success alert-dismissible')
        self.assertContains(response, 'data-bs-dismiss="alert"')
        html = response.content.decode()
        self.assertLess(html.index('</nav>'), html.index('id="mensagens"'))

    def test_signup(self):
        response = Client().post(reverse('signup'), {
            'username': 'novo', 'email': 'novo@exemplo.com',
            'password1': 'SenhaForte!2026', 'password2': 'SenhaForte!2026',
            'nome': 'Cliente Novo', 'telefone': '(46) 99999-8888',
        })
        self.assertIn('Bem-vindo(a), Cliente Novo!', ultima_mensagem(response))

    def test_edicao_dos_dados_do_cliente(self):
        response = self.cli.post(reverse('cliente_update', args=[self.cliente.pk]),
                                 {'nome': 'João S.', 'telefone': '(11) 99999-0000'})
        self.assertEqual(ultima_mensagem(response), 'Seus dados foram atualizados, João S..')

    def test_criar_editar_e_cancelar_pedido(self):
        inicio = self.hoje + timedelta(days=20)
        fim = inicio + timedelta(days=2)
        response = self.cli.post(reverse('reserva_create'), {
            'data_inicio': inicio.isoformat(), 'data_fim': fim.isoformat(), 'observacoes': ''})
        self.assertIn(f'Pedido de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} enviado!', ultima_mensagem(response))

        pedido = Reserva.objects.get(cliente=self.cliente)
        response = self.cli.post(reverse('minha_reserva_update', args=[pedido.pk]), {
            'data_inicio': inicio.isoformat(), 'data_fim': fim.isoformat(), 'observacoes': 'Família'})
        self.assertIn(f'Pedido #{pedido.pk} atualizado', ultima_mensagem(response))

        response = self.cli.post(reverse('minha_reserva_delete', args=[pedido.pk]))
        self.assertEqual(ultima_mensagem(response), f'Pedido de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} cancelado.')

    def test_edicao_e_exclusao_de_reserva_pelo_admin(self):
        pedido = self._reserva()
        response = self.admin.post(reverse('reserva_update', args=[pedido.pk]), {
            'chacara': self.chacara.pk, 'data_inicio': pedido.data_inicio.isoformat(),
            'data_fim': pedido.data_fim.isoformat(), 'observacoes': '', 'status': Reserva.STATUS_PENDENTE})
        self.assertEqual(ultima_mensagem(response), f'Reserva #{pedido.pk} de João Silva atualizada.')

        response = self.admin.post(reverse('reserva_delete', args=[pedido.pk]))
        self.assertEqual(ultima_mensagem(response), f'Reserva #{pedido.pk} de João Silva excluída.')

    def test_edicao_da_chacara(self):
        response = self.admin.post(reverse('chacara_update', args=[self.chacara.pk]), {
            'nome': 'Sítio de Lurdes', 'descricao': 'Descrição', 'preco_diaria': '600.00',
            'num_quartos': 3, 'num_banheiros': 2})
        self.assertEqual(ultima_mensagem(response), 'Informações da chácara "Sítio de Lurdes" atualizadas.')

    def test_cadastro_de_administrador(self):
        novo = make_user(username='novoadmin')
        response = self.admin.post(reverse('administrador_create'), {'nome': 'Ana Admin', 'usuario': novo.pk})
        self.assertEqual(ultima_mensagem(response), 'Administrador Ana Admin cadastrado com sucesso.')

    def test_aprovar_e_recusar(self):
        a = self._reserva(inicio=10, fim=13)
        response = self.admin.post(reverse('reserva_aprovar', args=[a.pk]))
        self.assertEqual(ultima_mensagem(response), 'Pedido de João Silva aprovado.')

        b = self._reserva(inicio=30, fim=32)
        response = self.admin.post(reverse('reserva_recusar', args=[b.pk]))
        self.assertEqual(ultima_mensagem(response), 'Pedido de João Silva recusado.')

    def test_erro_de_regra_vira_mensagem_de_erro(self):
        self._reserva(inicio=10, fim=15, status=Reserva.STATUS_CONFIRMADA)
        pedido = self._reserva(inicio=12, fim=14)
        response = self.admin.post(reverse('reserva_aprovar', args=[pedido.pk]))
        mensagens = list(get_messages(response.wsgi_request))
        self.assertEqual(len(mensagens), 1)
        self.assertEqual(mensagens[0].level_tag, 'danger')
        self.assertIn('já existe uma reserva confirmada', str(mensagens[0]))


# ---------------------------------------------------------------------------
# Registros por usuário — classe 2: Avaliacao (CRUD restrito ao dono)
# ---------------------------------------------------------------------------

class AvaliacaoTest(TestCase):
    def setUp(self):
        self.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.hoje = timezone.localdate()
        self.dono = make_user(username='dono')
        self.cliente = Cliente.objects.create(nome='Dono', telefone='11999990000', usuario=self.dono)
        self.intruso_user = make_user(username='intruso')
        self.intruso_cliente = Cliente.objects.create(
            nome='Intruso', telefone='11888887777', usuario=self.intruso_user)
        self.concluida = self._reserva(self.cliente, -10, -7, Reserva.STATUS_CONFIRMADA)
        self.avaliacao = Avaliacao.objects.create(
            usuario=self.dono, reserva=self.concluida, nota=5, comentario='Lugar maravilhoso, comentário privado.')
        self.c_dono = self._navegador('dono')
        self.c_intruso = self._navegador('intruso')

    def _reserva(self, cliente, inicio, fim, status):
        return Reserva.objects.create(
            cliente=cliente, chacara=self.chacara, status=status,
            data_inicio=self.hoje + timedelta(days=inicio), data_fim=self.hoje + timedelta(days=fim))

    def _navegador(self, username):
        c = Client()
        c.login(username=username, password='testpass123')
        return c

    # -- isolamento por dono ---------------------------------------------------

    def test_outro_usuario_recebe_404(self):
        for nome in ('avaliacao_detail', 'avaliacao_update', 'avaliacao_delete'):
            with self.subTest(nome):
                url = reverse(nome, args=[self.avaliacao.pk])
                self.assertEqual(self.c_intruso.get(url).status_code, 404)
                self.assertEqual(self.c_dono.get(url).status_code, 200)

    def test_post_de_outro_usuario_nao_altera_nem_exclui(self):
        self.c_intruso.post(reverse('avaliacao_update', args=[self.avaliacao.pk]), {'nota': 1, 'comentario': 'x'})
        self.c_intruso.post(reverse('avaliacao_delete', args=[self.avaliacao.pk]))
        self.avaliacao.refresh_from_db()
        self.assertEqual(self.avaliacao.nota, 5)

    def test_lista_mostra_so_as_do_dono(self):
        alheia_reserva = self._reserva(self.intruso_cliente, -20, -18, Reserva.STATUS_CONFIRMADA)
        alheia = Avaliacao.objects.create(usuario=self.intruso_user, reserva=alheia_reserva, nota=2)
        response = self.c_dono.get(reverse('minhas_avaliacoes'))
        self.assertEqual(list(response.context['avaliacoes']), [self.avaliacao])
        response = self.c_intruso.get(reverse('minhas_avaliacoes'))
        self.assertEqual(list(response.context['avaliacoes']), [alheia])

    def test_anonimo_vai_para_o_login(self):
        for url in (reverse('minhas_avaliacoes'), reverse('avaliacao_create'),
                    reverse('avaliacao_detail', args=[self.avaliacao.pk])):
            with self.subTest(url):
                response = Client().get(url)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    # -- criação ---------------------------------------------------------------

    def test_cria_avaliacao_preenchendo_o_usuario_logado(self):
        outra = self._reserva(self.cliente, -5, -3, Reserva.STATUS_CONFIRMADA)
        response = self.c_dono.post(reverse('avaliacao_create'), {
            'reserva': outra.pk, 'nota': 4, 'comentario': 'Muito bom', 'usuario': self.intruso_user.pk})
        nova = Avaliacao.objects.get(reserva=outra)
        self.assertRedirects(response, reverse('avaliacao_detail', args=[nova.pk]))
        self.assertEqual(nova.usuario, self.dono)  # o "usuario" do POST é ignorado
        self.assertEqual(ultima_mensagem(response), 'Avaliação enviada. Obrigado por contar como foi a sua estadia!')

    def test_nao_avalia_reserva_de_outro_usuario(self):
        alheia = self._reserva(self.intruso_cliente, -6, -4, Reserva.STATUS_CONFIRMADA)
        response = self.c_dono.post(reverse('avaliacao_create'), {'reserva': alheia.pk, 'nota': 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn('reserva', response.context['form'].errors)
        self.assertFalse(Avaliacao.objects.filter(reserva=alheia).exists())

    def test_so_oferece_reservas_elegiveis(self):
        elegivel = self._reserva(self.cliente, -5, 0, Reserva.STATUS_CONFIRMADA)    # saiu hoje
        futura = self._reserva(self.cliente, 5, 8, Reserva.STATUS_CONFIRMADA)       # ainda não aconteceu
        pendente = self._reserva(self.cliente, -30, -28, Reserva.STATUS_PENDENTE)   # nunca confirmada
        alheia = self._reserva(self.intruso_cliente, -40, -38, Reserva.STATUS_CONFIRMADA)
        response = self.c_dono.get(reverse('avaliacao_create'), {'reserva': elegivel.pk})
        opcoes = list(response.context['form'].fields['reserva'].queryset)
        self.assertEqual(opcoes, [elegivel])  # self.concluida já foi avaliada
        self.assertEqual(response.context['form'].initial['reserva'], elegivel.pk)
        for reserva in (futura, pendente, alheia, self.concluida):
            with self.subTest(reserva=reserva.pk):
                response = self.c_dono.post(reverse('avaliacao_create'), {'reserva': reserva.pk, 'nota': 3})
                self.assertIn('reserva', response.context['form'].errors)

    def test_model_clean_barra_reserva_futura_e_alheia(self):
        futura = self._reserva(self.cliente, 5, 8, Reserva.STATUS_CONFIRMADA)
        with self.assertRaises(ValidationError):
            Avaliacao(usuario=self.dono, reserva=futura, nota=4).full_clean()
        alheia = self._reserva(self.intruso_cliente, -6, -4, Reserva.STATUS_CONFIRMADA)
        with self.assertRaises(ValidationError):
            Avaliacao(usuario=self.dono, reserva=alheia, nota=4).full_clean()
        with self.assertRaises(ValidationError):
            Avaliacao(usuario=self.intruso_user, reserva=alheia, nota=6).full_clean()

    # -- edição e exclusão -------------------------------------------------------

    def test_edita_e_exclui_a_propria(self):
        response = self.c_dono.post(reverse('avaliacao_update', args=[self.avaliacao.pk]),
                                    {'nota': 4, 'comentario': 'Mudei de ideia'})
        self.assertEqual(ultima_mensagem(response), 'Avaliação atualizada.')
        self.avaliacao.refresh_from_db()
        self.assertEqual((self.avaliacao.nota, self.avaliacao.reserva), (4, self.concluida))

        response = self.c_dono.post(reverse('avaliacao_delete', args=[self.avaliacao.pk]))
        self.assertRedirects(response, reverse('minhas_avaliacoes'))
        self.assertEqual(ultima_mensagem(response), 'Avaliação excluída.')
        self.assertFalse(Avaliacao.objects.exists())

    # -- integração com as outras telas -----------------------------------------

    def test_link_avaliar_na_lista_de_reservas(self):
        elegivel = self._reserva(self.cliente, -5, -2, Reserva.STATUS_CONFIRMADA)
        futura = self._reserva(self.cliente, 5, 8, Reserva.STATUS_CONFIRMADA)
        response = self.c_dono.get(reverse('minhas_reservas'))
        self.assertContains(response, f'{reverse("avaliacao_create")}?reserva={elegivel.pk}')
        self.assertNotContains(response, f'?reserva={futura.pk}')
        self.assertContains(response, reverse('avaliacao_detail', args=[self.avaliacao.pk]))  # já avaliada

    def test_menu_tem_minhas_avaliacoes_para_cliente(self):
        self.assertContains(self.c_dono.get(reverse('index')), reverse('minhas_avaliacoes'))
        self.assertNotContains(Client().get(reverse('index')), reverse('minhas_avaliacoes'))

    def test_pagina_da_chacara_mostra_so_o_agregado(self):
        outra = self._reserva(self.intruso_cliente, -30, -28, Reserva.STATUS_CONFIRMADA)
        Avaliacao.objects.create(usuario=self.intruso_user, reserva=outra, nota=4, comentario='Comentário do intruso')
        response = Client().get(reverse('chacara_unica'))
        self.assertEqual(response.context['avaliacoes'], {'media': 4.5, 'total': 2})
        self.assertContains(response, '4,5')
        self.assertContains(response, '2 avaliações')
        self.assertNotContains(response, 'comentário privado')
        self.assertNotContains(response, 'Comentário do intruso')
        self.assertNotContains(response, 'Dono')

    def test_chacara_sem_avaliacoes(self):
        Avaliacao.objects.all().delete()
        self.assertContains(Client().get(reverse('chacara_unica')), 'Ainda sem avaliações')

    def test_filtro_de_estrelas(self):
        self.assertEqual(estrelas(4.5), ['bi-star-fill'] * 4 + ['bi-star-half'])
        self.assertEqual(estrelas(3), ['bi-star-fill'] * 3 + ['bi-star'] * 2)
        self.assertEqual(estrelas(None), ['bi-star'] * 5)


class AcessoPorDonoReservaTest(TestCase):
    """Classe 1 — Reserva: listar, ver, alterar e cancelar só as próprias."""

    def setUp(self):
        self.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.dono = make_user(username='dono')
        self.cliente = Cliente.objects.create(nome='Dono', telefone='11999990000', usuario=self.dono)
        intruso = make_user(username='intruso')
        Cliente.objects.create(nome='Intruso', telefone='11888887777', usuario=intruso)
        inicio = timezone.localdate() + timedelta(days=10)
        self.reserva = Reserva.objects.create(
            cliente=self.cliente, chacara=self.chacara, data_inicio=inicio, data_fim=inicio + timedelta(days=2))
        self.intruso = Client()
        self.intruso.login(username='intruso', password='testpass123')

    def test_outro_cliente_recebe_404_em_todas_as_telas_da_reserva(self):
        for nome in ('minha_reserva_detail', 'minha_reserva_update', 'minha_reserva_delete', 'reserva_detail'):
            with self.subTest(nome):
                self.assertEqual(self.intruso.get(reverse(nome, args=[self.reserva.pk])).status_code, 404)

    def test_post_de_outro_cliente_nao_altera_nem_cancela(self):
        self.intruso.post(reverse('minha_reserva_update', args=[self.reserva.pk]), {
            'data_inicio': self.reserva.data_inicio.isoformat(),
            'data_fim': (self.reserva.data_fim + timedelta(days=5)).isoformat(), 'observacoes': 'invadido'})
        self.intruso.post(reverse('minha_reserva_delete', args=[self.reserva.pk]))
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, Reserva.STATUS_PENDENTE)
        self.assertEqual(self.reserva.observacoes, '')

    def test_lista_do_outro_cliente_nao_inclui_a_reserva(self):
        response = self.intruso.get(reverse('minhas_reservas'))
        self.assertNotIn(self.reserva, response.context['reservas'])


# ---------------------------------------------------------------------------
# Otimização de consultas (docs/otimizacoes.md): o número de queries de cada
# tela não pode crescer com a quantidade de registros (N+1).
# ---------------------------------------------------------------------------

class NumeroDeConsultasTest(TestCase):
    """Base de toda página logada: sessão (1) + usuário já com cliente e
    administrador (1, BackendComPerfil). O cliente ainda paga 1 consulta aos
    grupos (usuario_eh_admin, uma vez por requisição); o admin com perfil
    Administrador não. Se um teste destes falhar, alguém tirou um
    select_related/prefetch_related ou criou uma consulta por linha."""

    @classmethod
    def setUpTestData(cls):
        cls.chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        hoje = timezone.localdate()
        cls.user = make_user()
        cls.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=cls.user)
        outro = Cliente.objects.create(nome='Maria Souza', telefone='11888887777', usuario=make_user(username='maria'))
        cls.admin_user = make_admin_user()
        for i in range(12):  # mais que uma página (paginate_by = 10)
            inicio = hoje - timedelta(days=300 + i * 5)
            passada = Reserva.objects.create(cliente=cls.cliente, chacara=cls.chacara, status=Reserva.STATUS_CONFIRMADA,
                                             data_inicio=inicio, data_fim=inicio + timedelta(days=2))
            Avaliacao.objects.create(usuario=cls.user, reserva=passada, nota=4)
            inicio = hoje + timedelta(days=30 + i * 5)
            Reserva.objects.create(cliente=outro, chacara=cls.chacara,
                                   data_inicio=inicio, data_fim=inicio + timedelta(days=2))
            Reserva.objects.create(cliente=cls.cliente, chacara=cls.chacara, status=Reserva.STATUS_CONFIRMADA,
                                   data_inicio=inicio + timedelta(days=2), data_fim=inicio + timedelta(days=4))
        cls.pendente = Reserva.objects.filter(status=Reserva.STATUS_PENDENTE).first()
        for _ in range(3):
            HistoricoReserva.objects.create(reserva=cls.pendente, status_novo=Reserva.STATUS_PENDENTE,
                                            alterado_por=cls.admin_user)

    def setUp(self):
        self.cli = Client()
        self.cli.force_login(self.user)
        self.admin = Client()
        self.admin.force_login(self.admin_user)

    def _confere(self, navegador, url, consultas):
        with self.assertNumQueries(consultas):
            response = navegador.get(url)
        self.assertEqual(response.status_code, 200)
        return response

    def test_listas_do_cliente(self):
        # base (2) + grupos (1) + contagem da paginação + página (com chácara e avaliação no JOIN)
        self._confere(self.cli, reverse('minhas_reservas'), 5)
        # ... + "ainda tem reserva para avaliar?"
        self._confere(self.cli, reverse('minhas_avaliacoes'), 6)

    def test_listas_do_admin(self):
        # base (2) + contagem + página (cliente e chácara no JOIN)
        self._confere(self.admin, reverse('pedidos_pendentes'), 4)
        self._confere(self.admin, reverse('reservas_todas'), 4)

    def test_disponibilidade_publica(self):
        # visitante: contagem + página + eventos do calendário
        self._confere(Client(), reverse('calendario_reservas'), 3)

    def test_detalhe_da_reserva_com_historico(self):
        # base (2) + reserva/cliente/chácara (JOIN) + histórico + quem alterou (prefetch)
        self._confere(self.admin, reverse('reserva_detail', args=[self.pendente.pk]), 5)

    def test_perfil_vem_junto_com_o_usuario(self):
        response = self.cli.get(reverse('index'))
        user = response.wsgi_request.user
        with self.assertNumQueries(0):  # já vieram no SELECT do usuário
            self.assertEqual(user.cliente, self.cliente)
            self.assertFalse(hasattr(user, 'administrador'))


# ---------------------------------------------------------------------------
# IA — análise do pedido (website/analise_pedido.py, via ia.services.chamar_ia).
# O provedor é sempre mockado: nenhum teste acessa a internet.
# ---------------------------------------------------------------------------

CHAVE_TESTE = 'chave-de-teste'
GERAR = 'ia.provedores.gemini.gerar'

ANALISE_VALIDA = {
    'tipo_evento': 'aniversário',
    'convidados_estimados': 30,
    'resumo': 'Aniversário de 30 pessoas com som.',
    'pontos_de_atencao': ['Muitas pessoas para 3 quartos', 'Som alto'],
    'nivel_atencao': 'alto',
}


def resultado_json(dados, entrada=300, saida=60):
    texto = dados if isinstance(dados, str) else json.dumps(dados)
    return ResultadoProvedor(texto=texto, tokens_entrada=entrada, tokens_saida=saida)


@override_settings(GEMINI_API_KEY=CHAVE_TESTE)
class AnalisePedidoTest(TestCase):
    def setUp(self):
        self.user = make_user()
        self.cliente = Cliente.objects.create(nome='Fulano Secreto', telefone='46991234567', usuario=self.user)
        self.navegador = Client()
        self.navegador.login(username='clienteuser', password='testpass123')
        self.inicio = date.today() + timedelta(days=30)

    def _pedir(self, observacoes='Aniversário de 30 anos, uns 30 convidados, com som.'):
        return self.navegador.post(reverse('reserva_create'), {
            'data_inicio': self.inicio.isoformat(),
            'data_fim': (self.inicio + timedelta(days=2)).isoformat(),
            'observacoes': observacoes,
        })

    @patch(GERAR)
    def test_json_valido_salva_analise_e_audita(self, gerar):
        gerar.return_value = resultado_json({**ANALISE_VALIDA, 'extra': 'descartar'})

        self.assertRedirects(self._pedir(), reverse('minhas_reservas'))

        reserva = Reserva.objects.get()
        self.assertEqual(reserva.analise_ia, ANALISE_VALIDA)  # chave extra descartada
        self.assertIsNotNone(reserva.analise_ia_em)
        requisicao = RequisicaoIA.objects.get()
        self.assertEqual((requisicao.origem, requisicao.usuario, requisicao.sucesso),
                         (RequisicaoIA.Origem.ANALISE, self.user, True))
        self.assertIn(f'Pedido #{reserva.pk}', requisicao.prompt)
        # Nome e telefone do cliente não vão para o modelo; o JSON é exigido.
        kwargs = gerar.call_args.kwargs
        texto_enviado = kwargs['mensagens'][-1]['conteudo']
        self.assertNotIn('Fulano', texto_enviado)
        self.assertNotIn('46991234567', texto_enviado)
        self.assertTrue(kwargs['formato_json'])
        self.assertEqual(kwargs['timeout_segundos'], analise_pedido.TIMEOUT_SEGUNDOS)

    @patch(GERAR)
    def test_analise_nao_conta_na_cota_do_cliente(self, gerar):
        gerar.return_value = resultado_json(ANALISE_VALIDA, entrada=90_000, saida=10_000)
        self._pedir()
        self.assertEqual(consumo_do_mes(self.user), 0)

    @patch(GERAR)
    def test_json_invalido_cria_reserva_sem_analise(self, gerar):
        gerar.return_value = resultado_json('isto não é JSON')
        with self.assertLogs('website.analise_pedido', level='WARNING'):
            self.assertRedirects(self._pedir(), reverse('minhas_reservas'))
        self.assertIsNone(Reserva.objects.get().analise_ia)

    @patch(GERAR)
    def test_json_fora_do_formato_cria_reserva_sem_analise(self, gerar):
        gerar.return_value = resultado_json({**ANALISE_VALIDA, 'nivel_atencao': 'crítico'})
        with self.assertLogs('website.analise_pedido', level='WARNING'):
            self._pedir()
        self.assertIsNone(Reserva.objects.get().analise_ia)

    @patch(GERAR)
    def test_falha_do_provedor_cria_reserva_sem_analise_e_audita(self, gerar):
        gerar.side_effect = ErroProvedorIA('Timeout de leitura')
        with self.assertLogs('ia.services', level='WARNING'):
            self.assertRedirects(self._pedir(), reverse('minhas_reservas'))
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.status, Reserva.STATUS_PENDENTE)
        self.assertIsNone(reserva.analise_ia)
        self.assertFalse(RequisicaoIA.objects.get().sucesso)

    @patch(GERAR)
    def test_sem_observacoes_nao_chama_a_api(self, gerar):
        self._pedir(observacoes='')
        self.assertEqual(Reserva.objects.get().analise_ia['resumo'], 'Cliente não descreveu o evento.')
        gerar.assert_not_called()

    @patch(GERAR)
    def test_edicao_do_pedido_refaz_a_analise(self, gerar):
        gerar.return_value = resultado_json(ANALISE_VALIDA)
        self._pedir()
        reserva = Reserva.objects.get()
        gerar.return_value = resultado_json({**ANALISE_VALIDA, 'tipo_evento': 'descanso em família',
                                             'nivel_atencao': 'baixo'})
        self.navegador.post(reverse('minha_reserva_update', args=[reserva.pk]), {
            'data_inicio': reserva.data_inicio.isoformat(),
            'data_fim': reserva.data_fim.isoformat(),
            'observacoes': 'Mudou: só a família, 6 pessoas.',
        })
        reserva.refresh_from_db()
        self.assertEqual(reserva.analise_ia['nivel_atencao'], 'baixo')

    def test_validar_analise(self):
        validar = analise_pedido.validar_analise
        self.assertEqual(validar({**ANALISE_VALIDA, 'nivel_atencao': 'Medio'})['nivel_atencao'], 'médio')
        self.assertEqual(validar({**ANALISE_VALIDA, 'tipo_evento': 'formatura'})['tipo_evento'], 'outro')
        self.assertIsNone(validar({**ANALISE_VALIDA, 'convidados_estimados': 'trinta'}))
        self.assertIsNone(validar({**ANALISE_VALIDA, 'pontos_de_atencao': 'som alto'}))
        self.assertIsNone(validar(['não', 'é', 'dict']))


class AnalisePedidoSemChaveTest(TestCase):
    """Nos testes a GEMINI_API_KEY é vazia (settings): a IA fica indisponível."""

    @patch(GERAR)
    def test_criar_pedido_funciona_sem_chave(self, gerar):
        Cliente.objects.create(nome='João', telefone='11999990000', usuario=make_user())
        c = Client()
        c.login(username='clienteuser', password='testpass123')
        inicio = date.today() + timedelta(days=30)
        response = c.post(reverse('reserva_create'), {
            'data_inicio': inicio.isoformat(),
            'data_fim': (inicio + timedelta(days=2)).isoformat(),
            'observacoes': 'Aniversário com 20 pessoas.',
        })
        self.assertRedirects(response, reverse('minhas_reservas'))
        self.assertIsNone(Reserva.objects.get().analise_ia)
        gerar.assert_not_called()
        self.assertFalse(RequisicaoIA.objects.exists())  # nada foi enviado


class AnalisePedidoTelasTest(TestCase):
    def setUp(self):
        chacara = Chacara.objects.order_by('pk').first() or make_chacara()
        self.cliente = Cliente.objects.create(nome='João', telefone='11999990000', usuario=make_user())
        make_admin_user()
        inicio = date.today() + timedelta(days=10)
        self.reserva = Reserva.objects.create(
            cliente=self.cliente, chacara=chacara, data_inicio=inicio,
            data_fim=inicio + timedelta(days=2), observacoes='Festa', analise_ia=ANALISE_VALIDA,
        )
        self.admin = Client()
        self.admin.login(username='adminuser', password='testpass123')
        self.cli = Client()
        self.cli.login(username='clienteuser', password='testpass123')

    def test_cliente_nao_reanalisa(self):
        response = self.cli.post(reverse('reserva_reanalisar', args=[self.reserva.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('reserva_detail', args=[self.reserva.pk]))

    def test_card_da_analise_so_para_admin(self):
        response = self.cli.get(reverse('minha_reserva_detail', args=[self.reserva.pk]))
        self.assertNotContains(response, 'Análise da IA')
        self.assertNotContains(response, ANALISE_VALIDA['resumo'])
        response = self.admin.get(reverse('reserva_detail', args=[self.reserva.pk]))
        self.assertContains(response, 'Análise da IA')
        self.assertContains(response, 'Muitas pessoas para 3 quartos')
        self.assertContains(response, 'Atenção alta')

    def test_pendentes_mostram_analise_para_admin(self):
        self.assertContains(self.admin.get(reverse('pedidos_pendentes')), ANALISE_VALIDA['resumo'])

    def test_texto_da_ia_e_escapado(self):
        self.reserva.analise_ia = {**ANALISE_VALIDA, 'resumo': '<script>alert(1)</script>'}
        self.reserva.save()
        response = self.admin.get(reverse('reserva_detail', args=[self.reserva.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_sem_chave_reanalisar_avisa(self):
        response = self.admin.post(reverse('reserva_reanalisar', args=[self.reserva.pk]), follow=True)
        self.assertContains(response, 'A IA está desativada ou sem chave configurada')

    @override_settings(GEMINI_API_KEY=CHAVE_TESTE)
    @patch(GERAR)
    def test_admin_reanalisa(self, gerar):
        gerar.return_value = resultado_json({**ANALISE_VALIDA, 'nivel_atencao': 'baixo'})
        self.assertEqual(self.admin.get(reverse('reserva_reanalisar', args=[self.reserva.pk])).status_code, 405)
        response = self.admin.post(reverse('reserva_reanalisar', args=[self.reserva.pk]))
        self.assertRedirects(response, reverse('reserva_detail', args=[self.reserva.pk]))
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.analise_ia['nivel_atencao'], 'baixo')
