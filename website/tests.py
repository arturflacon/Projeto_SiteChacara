import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import ia
from .forms import ClienteForm, ReservaClienteForm
from .models import Administrador, Chacara, Cliente, Reserva, UsoIA
from .templatetags.sitio_tags import telefone


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
        self.assertContains(response, 'href="?cliente=silva&page=2">Próxima</a>')
        self.assertNotContains(response, '>Anterior</a>')

        response = c.get(url, {'cliente': 'silva', 'page': 2})
        self.assertContains(response, 'href="?cliente=silva&page=1">Anterior</a>')
        self.assertNotContains(response, '>Próxima</a>')
        self.assertEqual([r.cliente for r in response.context['reservas']], [self.cliente])

    def test_limpar_volta_para_a_lista_sem_parametros(self):
        url = reverse('minhas_reservas')
        response = self._navegador('clienteuser').get(url, {'status': Reserva.STATUS_PENDENTE})
        self.assertContains(response, f'<a href="{url}" class="btn btn-outline-secondary">')

    def test_disponibilidade_publica_nao_filtra_por_cliente(self):
        response = Client().get(reverse('calendario_reservas'))
        self.assertIn('data_inicio', response.context['filter'].form.fields)
        self.assertNotIn('cliente', response.context['filter'].form.fields)


class DataTablesListagensTest(TestCase):
    """As tabelas de listagem seguem a skill datatables-listagens."""

    TABELA = 'class="table table-striped table-hover align-middle table-datatable"'

    def setUp(self):
        self.chacara = make_chacara()
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=make_user())
        make_admin_user()

    def _reserva(self, status=Reserva.STATUS_PENDENTE):
        # 3 diárias × R$ 500,00 = R$ 1.500,00
        return Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=date(2026, 12, 3),
            data_fim=date(2026, 12, 6),
            status=status,
        )

    def test_moeda_e_data_ordenam_pelo_data_sort(self):
        self._reserva()
        for username, url_name in [('clienteuser', 'minhas_reservas'), ('adminuser', 'pedidos_pendentes')]:
            with self.subTest(url_name):
                c = Client()
                c.login(username=username, password='testpass123')
                response = c.get(reverse(url_name))
                self.assertContains(response, self.TABELA)
                self.assertContains(response, '<td data-sort="2026-12-03">03/12/2026</td>')
                self.assertContains(response, 'data-sort="1500.00"')
                self.assertContains(response, 'R$ 1.500,00')
                self.assertContains(
                    response,
                    '<th class="text-end" data-orderable="false" data-searchable="false">Ações</th>',
                )

    def test_disponibilidade_ordena_datas_pelo_data_sort(self):
        self._reserva(status=Reserva.STATUS_CONFIRMADA)
        response = Client().get(reverse('calendario_reservas'))
        self.assertContains(response, self.TABELA)
        self.assertContains(response, '<td data-sort="2026-12-06">06/12/2026</td>')


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
        self.assertContains(response, 'text-bg-danger')  # MESSAGE_TAGS: error -> danger

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
        self.assertContains(response, 'href="?cliente__nome=silva&status=PENDENTE&page=2">Próxima</a>')

        response = c.get(url, {**filtros, 'page': 2})
        self.assertContains(response, 'href="?cliente__nome=silva&status=PENDENTE&page=1">Anterior</a>')
        self.assertEqual(len(response.context['reservas']), 1)


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
# IA generativa (Gemini) — website.ia.get_client sempre mockado:
# nenhum teste faz requisição real nem precisa da chave.
# ---------------------------------------------------------------------------

CHAVE_TESTE = 'chave-de-teste'


def resposta_falsa(texto, entrada=120, saida=30):
    """Imita a resposta do SDK: .text e .usage_metadata com os tokens."""
    return SimpleNamespace(
        text=texto,
        usage_metadata=SimpleNamespace(prompt_token_count=entrada, candidates_token_count=saida),
    )


def cliente_gemini_falso(texto_chat='Olá! A diária custa R$ 500,00.', texto_json=None, erro=None):
    cliente = MagicMock()
    cliente.chats.create.return_value.send_message.return_value = resposta_falsa(texto_chat)
    if erro is not None:
        cliente.models.generate_content.side_effect = erro
    else:
        cliente.models.generate_content.return_value = resposta_falsa(texto_json, entrada=300, saida=60)
    return cliente


ANALISE_VALIDA = {
    'tipo_evento': 'aniversário',
    'convidados_estimados': 30,
    'resumo': 'Aniversário de 30 pessoas com som.',
    'pontos_de_atencao': ['Muitas pessoas para 3 quartos', 'Som alto'],
    'nivel_atencao': 'alto',
}


@override_settings(GEMINI_API_KEY=CHAVE_TESTE)
class ChatbotTest(TestCase):
    url = reverse('chatbot_mensagem')

    @patch('website.ia.get_client')
    def test_responde_grava_historico_e_uso(self, get_client):
        get_client.return_value = cliente_gemini_falso()
        response = self.client.post(self.url, {'mensagem': 'Quanto custa a diária?'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'resposta': 'Olá! A diária custa R$ 500,00.'})
        self.assertEqual(self.client.session['chat_ia'], [
            {'role': 'user', 'text': 'Quanto custa a diária?'},
            {'role': 'model', 'text': 'Olá! A diária custa R$ 500,00.'},
        ])
        uso = UsoIA.objects.get()
        self.assertEqual((uso.tipo, uso.tokens_entrada, uso.tokens_saida), (UsoIA.CHAT, 120, 30))
        self.assertIsNone(uso.usuario)  # visitante

    @patch('website.ia.get_client')
    def test_aceita_json_no_corpo(self, get_client):
        get_client.return_value = cliente_gemini_falso()
        response = self.client.post(
            self.url, json.dumps({'mensagem': 'Oi'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)

    @patch('website.ia.get_client')
    def test_historico_truncado_nas_ultimas_10_trocas(self, get_client):
        cliente = cliente_gemini_falso()
        get_client.return_value = cliente
        sessao = self.client.session
        sessao['chat_ia'] = [
            {'role': 'user' if i % 2 == 0 else 'model', 'text': f'msg {i}'} for i in range(30)
        ]
        sessao.save()

        self.client.post(self.url, {'mensagem': 'Nova pergunta'})

        enviado = cliente.chats.create.call_args.kwargs['history']
        self.assertEqual(len(enviado), 20)
        self.assertEqual(enviado[0].parts[0].text, 'msg 10')
        guardado = self.client.session['chat_ia']
        self.assertEqual(len(guardado), 20)
        self.assertEqual(guardado[-2]['text'], 'Nova pergunta')

    @patch('website.ia.get_client')
    def test_rate_limit_16a_mensagem_retorna_429(self, get_client):
        cliente = cliente_gemini_falso()
        get_client.return_value = cliente
        for _ in range(15):
            self.assertEqual(self.client.post(self.url, {'mensagem': 'Oi'}).status_code, 200)
        response = self.client.post(self.url, {'mensagem': 'Oi'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('limite', response.json()['erro'])
        self.assertEqual(cliente.chats.create.call_count, 15)

    @patch('website.ia.get_client')
    def test_mensagem_longa_400_e_get_405(self, get_client):
        self.assertEqual(self.client.post(self.url, {'mensagem': 'x' * 501}).status_code, 400)
        self.assertEqual(self.client.post(self.url, {'mensagem': '   '}).status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        get_client.assert_not_called()

    @patch('website.ia.get_client')
    def test_falha_do_sdk_nao_vira_500(self, get_client):
        cliente = cliente_gemini_falso()
        cliente.chats.create.return_value.send_message.side_effect = RuntimeError('quota')
        get_client.return_value = cliente
        with self.assertLogs('website.ia', level='ERROR'):
            response = self.client.post(self.url, {'mensagem': 'Oi'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('chat_ia', self.client.session)

    def test_csrf_obrigatorio(self):
        response = Client(enforce_csrf_checks=True).post(self.url, {'mensagem': 'Oi'})
        self.assertEqual(response.status_code, 403)

    @patch('website.ia.get_client')
    def test_nova_conversa_limpa_historico(self, get_client):
        get_client.return_value = cliente_gemini_falso()
        self.client.post(self.url, {'mensagem': 'Oi'})
        self.client.post(reverse('chatbot_limpar'))
        self.assertNotIn('chat_ia', self.client.session)

    def test_instrucao_nao_contem_dados_de_clientes(self):
        chacara = Chacara.objects.first() or make_chacara()
        cliente = Cliente.objects.create(
            nome='Fulano Secreto da Silva', telefone='46991234567', usuario=make_user())
        inicio = date.today() + timedelta(days=7)
        Reserva.objects.create(
            cliente=cliente, chacara=chacara, status=Reserva.STATUS_CONFIRMADA,
            data_inicio=inicio, data_fim=inicio + timedelta(days=2), observacoes='Festa do Fulano')

        instrucao = ia.montar_instrucao_chat()

        self.assertIn(inicio.strftime('%d/%m/%Y'), instrucao)  # a data ocupada vai
        for dado in ('Fulano', 'Secreto', '46991234567', '99123-4567', 'Festa'):
            self.assertNotIn(dado, instrucao)
        self.assertIn('Nunca confirme', instrucao)


class ChatbotSemChaveTest(TestCase):
    """Nos testes a GEMINI_API_KEY é vazia (settings): a IA fica desligada."""

    @patch('website.ia.get_client')
    def test_chat_responde_indisponivel_sem_500(self, get_client):
        response = self.client.post(reverse('chatbot_mensagem'), {'mensagem': 'Oi'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['erro'], 'Assistente indisponível no momento.')
        get_client.assert_not_called()

    def test_widget_mostra_indisponivel(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, 'Assistente indisponível no momento')
        self.assertContains(response, 'id="chat-historico"')

    @patch('website.ia.get_client')
    def test_criar_pedido_funciona_sem_chave(self, get_client):
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
        get_client.assert_not_called()


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

    @patch('website.ia.get_client')
    def test_json_valido_salva_analise_e_uso(self, get_client):
        cliente = cliente_gemini_falso(texto_json=json.dumps({**ANALISE_VALIDA, 'extra': 'descartar'}))
        get_client.return_value = cliente

        self.assertRedirects(self._pedir(), reverse('minhas_reservas'))

        reserva = Reserva.objects.get()
        self.assertEqual(reserva.analise_ia, ANALISE_VALIDA)  # chave extra descartada
        self.assertIsNotNone(reserva.analise_ia_em)
        uso = UsoIA.objects.get()
        self.assertEqual((uso.tipo, uso.reserva, uso.usuario), (UsoIA.ANALISE, reserva, self.user))
        # Nome e telefone do cliente não vão para o modelo; o JSON é exigido.
        kwargs = cliente.models.generate_content.call_args.kwargs
        self.assertNotIn('Fulano', kwargs['contents'])
        self.assertNotIn('46991234567', kwargs['contents'])
        self.assertEqual(kwargs['config'].response_mime_type, 'application/json')

    @patch('website.ia.get_client')
    def test_json_invalido_cria_reserva_sem_analise(self, get_client):
        get_client.return_value = cliente_gemini_falso(texto_json='isto não é JSON')
        with self.assertLogs('website.ia', level='ERROR'):
            self.assertRedirects(self._pedir(), reverse('minhas_reservas'))
        self.assertIsNone(Reserva.objects.get().analise_ia)

    @patch('website.ia.get_client')
    def test_json_fora_do_formato_cria_reserva_sem_analise(self, get_client):
        fora = {**ANALISE_VALIDA, 'nivel_atencao': 'crítico'}
        get_client.return_value = cliente_gemini_falso(texto_json=json.dumps(fora))
        with self.assertLogs('website.ia', level='WARNING'):
            self._pedir()
        self.assertIsNone(Reserva.objects.get().analise_ia)

    @patch('website.ia.get_client')
    def test_excecao_do_sdk_cria_reserva_sem_analise(self, get_client):
        get_client.return_value = cliente_gemini_falso(erro=TimeoutError('timeout'))
        with self.assertLogs('website.ia', level='ERROR'):
            self.assertRedirects(self._pedir(), reverse('minhas_reservas'))
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.status, Reserva.STATUS_PENDENTE)
        self.assertIsNone(reserva.analise_ia)

    @patch('website.ia.get_client')
    def test_sem_observacoes_nao_chama_a_api(self, get_client):
        self._pedir(observacoes='')
        self.assertEqual(Reserva.objects.get().analise_ia['resumo'], 'Cliente não descreveu o evento.')
        get_client.assert_not_called()

    @patch('website.ia.get_client')
    def test_edicao_do_pedido_refaz_a_analise(self, get_client):
        get_client.return_value = cliente_gemini_falso(texto_json=json.dumps(ANALISE_VALIDA))
        self._pedir()
        reserva = Reserva.objects.get()
        novo = {**ANALISE_VALIDA, 'tipo_evento': 'descanso em família', 'nivel_atencao': 'baixo'}
        get_client.return_value = cliente_gemini_falso(texto_json=json.dumps(novo))
        self.navegador.post(reverse('minha_reserva_update', args=[reserva.pk]), {
            'data_inicio': reserva.data_inicio.isoformat(),
            'data_fim': reserva.data_fim.isoformat(),
            'observacoes': 'Mudou: só a família, 6 pessoas.',
        })
        reserva.refresh_from_db()
        self.assertEqual(reserva.analise_ia['nivel_atencao'], 'baixo')

    def test_validar_analise(self):
        self.assertEqual(ia.validar_analise({**ANALISE_VALIDA, 'nivel_atencao': 'Medio'})['nivel_atencao'], 'médio')
        self.assertEqual(ia.validar_analise({**ANALISE_VALIDA, 'tipo_evento': 'formatura'})['tipo_evento'], 'outro')
        self.assertIsNone(ia.validar_analise({**ANALISE_VALIDA, 'convidados_estimados': 'trinta'}))
        self.assertIsNone(ia.validar_analise({**ANALISE_VALIDA, 'pontos_de_atencao': 'som alto'}))
        self.assertIsNone(ia.validar_analise(['não', 'é', 'dict']))


class UsoIATest(TestCase):
    def test_custo_igual_ao_da_apostila(self):
        # 3.548 de entrada × US$ 0,30/1M + 100 de saída × US$ 2,50/1M = US$ 0,0013144
        uso = UsoIA.objects.create(tipo=UsoIA.CHAT, tokens_entrada=3548, tokens_saida=100)
        self.assertEqual(uso.custo_usd, Decimal('0.00131440'))
        self.assertEqual(round(uso.custo_brl, 6), Decimal('0.007229'))

    def test_registrar_uso_trata_none_como_zero(self):
        resposta = SimpleNamespace(usage_metadata=SimpleNamespace(
            prompt_token_count=None, candidates_token_count=None))
        uso = ia.registrar_uso(UsoIA.CHAT, resposta)
        self.assertEqual((uso.tokens_entrada, uso.tokens_saida, uso.custo_usd), (0, 0, Decimal('0')))


class IAAcessoAdminTest(TestCase):
    def setUp(self):
        chacara = Chacara.objects.first() or make_chacara()
        self.cliente = Cliente.objects.create(nome='João', telefone='11999990000', usuario=make_user())
        make_admin_user()
        inicio = date.today() + timedelta(days=10)
        self.reserva = Reserva.objects.create(
            cliente=self.cliente, chacara=chacara, data_inicio=inicio,
            data_fim=inicio + timedelta(days=2), observacoes='Festa', analise_ia=ANALISE_VALIDA,
        )
        UsoIA.objects.create(tipo=UsoIA.CHAT, tokens_entrada=3548, tokens_saida=100)
        UsoIA.objects.create(tipo=UsoIA.ANALISE, tokens_entrada=300, tokens_saida=60, reserva=self.reserva)
        self.admin = Client()
        self.admin.login(username='adminuser', password='testpass123')
        self.cli = Client()
        self.cli.login(username='clienteuser', password='testpass123')

    def test_cliente_nao_acessa_uso_ia_nem_reanalisar(self):
        self.assertEqual(self.cli.get(reverse('uso_ia')).status_code, 302)
        response = self.cli.post(reverse('reserva_reanalisar', args=[self.reserva.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('reserva_detail', args=[self.reserva.pk]))

    def test_admin_ve_metricas(self):
        response = self.admin.get(reverse('uso_ia'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totais']['chamadas'], 2)
        self.assertEqual(response.context['totais']['entrada'], 3848)
        self.assertEqual(response.context['media_chat']['chamadas'], 1)
        response = self.admin.get(reverse('uso_ia'), {'tipo': UsoIA.ANALISE})
        self.assertEqual([u.tipo for u in response.context['usos']], [UsoIA.ANALISE])

    def test_card_da_analise_so_para_admin(self):
        response = self.cli.get(reverse('minha_reserva_detail', args=[self.reserva.pk]))
        self.assertNotContains(response, 'Análise da IA')
        self.assertNotContains(response, ANALISE_VALIDA['resumo'])
        response = self.admin.get(reverse('reserva_detail', args=[self.reserva.pk]))
        self.assertContains(response, 'Análise da IA')
        self.assertContains(response, 'Muitas pessoas para 3 quartos')
        self.assertContains(response, 'Atenção alta')

    def test_pendentes_mostram_analise_para_admin(self):
        response = self.admin.get(reverse('pedidos_pendentes'))
        self.assertContains(response, ANALISE_VALIDA['resumo'])

    def test_texto_da_ia_e_escapado(self):
        self.reserva.analise_ia = {**ANALISE_VALIDA, 'resumo': '<script>alert(1)</script>'}
        self.reserva.save()
        response = self.admin.get(reverse('reserva_detail', args=[self.reserva.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    @override_settings(GEMINI_API_KEY=CHAVE_TESTE)
    @patch('website.ia.get_client')
    def test_admin_reanalisa(self, get_client):
        novo = {**ANALISE_VALIDA, 'nivel_atencao': 'baixo'}
        get_client.return_value = cliente_gemini_falso(texto_json=json.dumps(novo))
        self.assertEqual(self.admin.get(reverse('reserva_reanalisar', args=[self.reserva.pk])).status_code, 405)
        response = self.admin.post(reverse('reserva_reanalisar', args=[self.reserva.pk]))
        self.assertRedirects(response, reverse('reserva_detail', args=[self.reserva.pk]))
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.analise_ia['nivel_atencao'], 'baixo')
