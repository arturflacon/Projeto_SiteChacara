from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Administrador, Chacara, Cliente, Reserva


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
