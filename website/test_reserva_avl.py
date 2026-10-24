"""
Testes funcionais de caixa-preta — Pedido de Reserva (Sítio de Lurdes).

Escopo: apenas a funcionalidade "Fazer Pedido de Reserva".
Técnica: Análise do Valor Limite (AVL), conforme o Plano de Testes
registrado no Testiny (projeto NAES, plano TP-1).

Caixa-preta: cada caso envia dados pelo formulário da aplicação e verifica
somente aquilo que a aplicação devolve ao usuário (página, mensagem de erro,
lista "Minhas Reservas"). Nenhum teste inspeciona a implementação interna
das views, do form ou do model.

Rastreabilidade com o Testiny:

    CT01  TC-1  CT01SaidaAnteriorAChegada            limite 1 (-1 dia)
    CT02  TC-2  CT02SaidaIgualAChegada               limite 1 ( 0 dias)
    CT03  TC-3  CT03UmaDiaria                        limite 1 (+1 dia)
    CT04  TC-4  CT04SaidaAntesDoInicioDaConfirmada   limite 2 (abaixo)
    CT05  TC-5  CT05SaidaNoInicioDaConfirmada        limite 2 (no limite)
    CT06  TC-6  CT06SaidaDepoisDoInicioDaConfirmada  limite 2 (acima)

Execução:
    python manage.py test website.test_reserva_avl -v 2
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import Chacara, Cliente, Reserva

# ---------------------------------------------------------------------------
# Dados de teste definidos na seção 6 do Plano de Testes
#
# As datas do plano original (out/nov de 2026) eram fixas e passaram a cair
# no passado, onde o formulário recusa qualquer pedido. Agora elas são
# relativas a hoje, mantendo exatamente as mesmas distâncias entre si — os
# limites testados (0 dia de duração e início da confirmada) não mudam.
# ---------------------------------------------------------------------------

PRECO_DIARIA = Decimal('500.00')          # P

REFERENCIA = date.today() + timedelta(days=30)

# Limite 1 — duração da reserva igual a 0 dias (chegada fixa)
CHEGADA_L1 = REFERENCIA + timedelta(days=27)
SAIDA_MENOS_1 = CHEGADA_L1 - timedelta(days=1)   # imediatamente abaixo do limite
SAIDA_LIMITE_0 = CHEGADA_L1                      # no limite
SAIDA_MAIS_1 = CHEGADA_L1 + timedelta(days=1)    # imediatamente acima do limite

# Limite 2 — início da reserva confirmada de referência (chegada fixa)
CONFIRMADA_INICIO = REFERENCIA + timedelta(days=5)
CONFIRMADA_FIM = REFERENCIA + timedelta(days=10)
CHEGADA_L2 = REFERENCIA
SAIDA_ABAIXO = CONFIRMADA_INICIO - timedelta(days=1)   # imediatamente abaixo do limite
SAIDA_NO_LIMITE = CONFIRMADA_INICIO                    # no limite
SAIDA_ACIMA = CONFIRMADA_INICIO + timedelta(days=1)    # imediatamente acima do limite


class BaseReservaAVL(TestCase):
    """Pré-condições comuns a todos os casos do plano."""

    def setUp(self):
        # Preparação do ambiente (equivale à etapa 4 do cronograma).
        #
        # O sistema opera com uma única chácara, criada pela migration
        # 0003_chacara_inicial. O formulário de pedido sempre usa essa
        # chácara, então os testes trabalham sobre ela e apenas fixam o
        # preço da diária no valor P definido no Plano de Testes.
        self.chacara = Chacara.objects.first()
        if self.chacara is None:
            self.chacara = Chacara.objects.create(
                nome='Sítio de Lurdes',
                descricao='Chácara para eventos.',
                preco_diaria=PRECO_DIARIA,
                num_quartos=3,
                num_banheiros=2,
            )
        else:
            self.chacara.preco_diaria = PRECO_DIARIA
            self.chacara.save()

        self.usuario = User.objects.create_user(
            username='cliente_a', password='SenhaTeste123'
        )
        self.cliente = Cliente.objects.create(
            nome='Cliente A', telefone='44999990000', usuario=self.usuario
        )
        self.navegador = Client()
        self.navegador.login(username='cliente_a', password='SenhaTeste123')

    # -- ações do usuário --------------------------------------------------

    def abrir_formulario(self):
        """Step 1 — Acessar o menu "Reservar"."""
        return self.navegador.get(reverse('reserva_create'))

    def enviar_pedido(self, data_inicio, data_fim):
        """Steps 2 a 4 — informar as datas e clicar em "Enviar Pedido"."""
        return self.navegador.post(
            reverse('reserva_create'),
            {
                'data_inicio': data_inicio.isoformat(),
                'data_fim': data_fim.isoformat(),
                'observacoes': '',
            },
        )

    def abrir_minhas_reservas(self):
        return self.navegador.get(reverse('minhas_reservas'))

    def criar_reserva_confirmada_de_referencia(self):
        """Pré-condição dos casos CT04 a CT06 (preparação de dados)."""
        Reserva.objects.create(
            cliente=self.cliente,
            chacara=self.chacara,
            data_inicio=CONFIRMADA_INICIO,
            data_fim=CONFIRMADA_FIM,
            status=Reserva.STATUS_CONFIRMADA,
        )

    # -- verificações sobre a saída da aplicação ---------------------------

    def assertFormularioExibido(self, response):
        """Expected result do Step 1."""
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Data de Início')
        self.assertContains(response, 'Data de Fim')

    def assertPedidoRecusado(self, response, data_inicio, data_fim, mensagem=None):
        """O pedido não é criado e o formulário permanece na tela."""
        self.assertEqual(
            response.status_code, 200,
            'O pedido foi aceito pela aplicação, mas deveria ter sido recusado.',
        )
        if mensagem:
            self.assertContains(response, mensagem)
        self.assertNaoExisteNaLista(data_inicio, data_fim)

    def assertPedidoAceito(self, response, data_inicio, data_fim, dias):
        """O pedido é criado como Pendente, com o valor total calculado."""
        self.assertRedirects(response, reverse('minhas_reservas'))

        pagina = self.abrir_minhas_reservas()
        self.assertContains(pagina, data_inicio.strftime('%d/%m/%Y'))
        self.assertContains(pagina, data_fim.strftime('%d/%m/%Y'))

        pedido = self.buscar_na_lista(pagina, data_inicio, data_fim)
        self.assertIsNotNone(pedido, 'O pedido não apareceu em "Minhas Reservas".')
        self.assertEqual(pedido.status, Reserva.STATUS_PENDENTE)
        self.assertEqual(pedido.valor_total, PRECO_DIARIA * dias)

    def assertNaoExisteNaLista(self, data_inicio, data_fim):
        pagina = self.abrir_minhas_reservas()
        self.assertIsNone(
            self.buscar_na_lista(pagina, data_inicio, data_fim),
            'Surgiu um pedido novo em "Minhas Reservas" após um envio recusado.',
        )

    @staticmethod
    def buscar_na_lista(pagina, data_inicio, data_fim):
        for reserva in pagina.context['reservas']:
            if reserva.data_inicio == data_inicio and reserva.data_fim == data_fim:
                return reserva
        return None


# ---------------------------------------------------------------------------
# Limite 1 — duração da reserva igual a 0 dias
# ---------------------------------------------------------------------------

class CT01SaidaAnteriorAChegada(BaseReservaAVL):
    """CT01 — saída 1 dia antes da chegada (-1 dia).

    Resultado esperado: pedido recusado, com a mensagem indicando que a data
    de saída não pode ser anterior à data de chegada.
    """

    def test_pedido_recusado(self):
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L1, SAIDA_MENOS_1)
        self.assertPedidoRecusado(
            response, CHEGADA_L1, SAIDA_MENOS_1,
            mensagem='A data de saída não pode ser anterior à data de chegada.',
        )


class CT02SaidaIgualAChegada(BaseReservaAVL):
    """CT02 — saída no mesmo dia da chegada (0 dias).

    Resultado esperado: pedido recusado, pois a reserva deve ter no mínimo
    uma diária.
    """

    def test_pedido_recusado(self):
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L1, SAIDA_LIMITE_0)
        self.assertPedidoRecusado(response, CHEGADA_L1, SAIDA_LIMITE_0)


class CT03UmaDiaria(BaseReservaAVL):
    """CT03 — saída 1 dia depois da chegada (+1 dia).

    Resultado esperado: pedido aceito, status Pendente, valor P x 1.
    """

    def test_pedido_aceito(self):
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L1, SAIDA_MAIS_1)
        self.assertPedidoAceito(response, CHEGADA_L1, SAIDA_MAIS_1, dias=1)


# ---------------------------------------------------------------------------
# Limite 2 — início da reserva confirmada de referência
# ---------------------------------------------------------------------------

class CT04SaidaAntesDoInicioDaConfirmada(BaseReservaAVL):
    """CT04 — saída 1 dia antes do início da confirmada (imediatamente abaixo do limite).

    Resultado esperado: pedido aceito, status Pendente, valor P x 4.
    """

    def test_pedido_aceito(self):
        self.criar_reserva_confirmada_de_referencia()
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L2, SAIDA_ABAIXO)
        self.assertPedidoAceito(response, CHEGADA_L2, SAIDA_ABAIXO, dias=4)


class CT05SaidaNoInicioDaConfirmada(BaseReservaAVL):
    """CT05 — saída no dia de início da confirmada (no limite).

    Resultado esperado: pedido aceito, status Pendente, valor P x 5.
    O dia de saída pode coincidir com o dia de chegada da reserva confirmada.
    """

    def test_pedido_aceito(self):
        self.criar_reserva_confirmada_de_referencia()
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L2, SAIDA_NO_LIMITE)
        self.assertPedidoAceito(response, CHEGADA_L2, SAIDA_NO_LIMITE, dias=5)


class CT06SaidaDepoisDoInicioDaConfirmada(BaseReservaAVL):
    """CT06 — saída 1 dia depois do início da confirmada (imediatamente acima do limite).

    Resultado esperado: pedido recusado por conflito com reserva confirmada.
    """

    def test_pedido_recusado(self):
        self.criar_reserva_confirmada_de_referencia()
        self.assertFormularioExibido(self.abrir_formulario())
        response = self.enviar_pedido(CHEGADA_L2, SAIDA_ACIMA)
        self.assertPedidoRecusado(
            response, CHEGADA_L2, SAIDA_ACIMA,
            mensagem='Já existe uma reserva confirmada nesse período',
        )