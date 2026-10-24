"""Testes do app ia. O provedor é sempre mockado (ia.provedores.gemini.gerar):
nenhum teste acessa a internet nem precisa de chave real."""
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from website.models import Administrador, Cliente

from . import services
from .excecoes import CotaExcedida, ErroProvedorIA, IADesativada
from .models import ConfiguracaoIA, PerfilIAUsuario, RequisicaoIA
from .provedores.base import ResultadoProvedor

CHAVE_TESTE = 'chave-de-teste-123'
GERAR = 'ia.provedores.gemini.gerar'
Origem = RequisicaoIA.Origem


def pergunta(texto='Quanto custa a diária?'):
    return [{'papel': 'usuario', 'conteudo': texto}]


def ok(texto='A diária custa R$ 500,00.', entrada=120, saida=30):
    return ResultadoProvedor(texto=texto, tokens_entrada=entrada, tokens_saida=saida)


def criar_usuario(username, cliente=True, admin=False):
    user = User.objects.create_user(username=username, password='testpass123')
    if cliente:
        Cliente.objects.create(nome=username.title(), telefone='11999990000', usuario=user)
    if admin:
        Administrador.objects.create(nome=f'Admin {username}', usuario=user)
    return user


def requisicao(usuario, tokens, origem=Origem.ASSISTENTE, criado_em=None, sucesso=True, prompt='Pergunta'):
    return RequisicaoIA.objects.create(
        usuario=usuario, origem=origem, modelo='gemini-teste', prompt=prompt,
        tokens_entrada=tokens, tokens_total=tokens, sucesso=sucesso,
        criado_em=criado_em or timezone.now())


class SdkIsoladoTest(TestCase):
    """O SDK do Gemini só pode ser importado em ia/provedores/gemini.py."""

    PADRAO = re.compile(r'^\s*(?:from\s+google\s+import\s+genai\b|from\s+google\.genai\b|import\s+google\.genai\b)',
                        re.MULTILINE)
    PERMITIDO = Path('ia/provedores/gemini.py')
    IGNORAR = {'.venv', 'venv', 'node_modules', 'static_gcloud', '__pycache__', '.git'}

    def test_sdk_so_em_ia_provedores_gemini(self):
        raiz = Path(settings.BASE_DIR)
        encontrados = []
        for arquivo in raiz.rglob('*.py'):
            relativo = arquivo.relative_to(raiz)
            if self.IGNORAR.intersection(relativo.parts):
                continue
            if self.PADRAO.search(arquivo.read_text(encoding='utf-8', errors='ignore')):
                encontrados.append(relativo)
        self.assertEqual(encontrados, [self.PERMITIDO])


@override_settings(GEMINI_API_KEY=CHAVE_TESTE)
class ChamarIATest(TestCase):
    def setUp(self):
        self.user = criar_usuario('joao')
        self.config = ConfiguracaoIA.obter()

    @patch(GERAR)
    def test_sucesso_audita_e_envia_a_configuracao(self, gerar):
        gerar.return_value = ok()
        self.config.modelo = 'gemini-modelo-x'
        self.config.temperatura = Decimal('0.30')
        self.config.max_tokens_resposta = 300
        self.config.timeout_segundos = 12
        self.config.save()

        resposta = services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE, 'Seja breve.')

        self.assertTrue(resposta.sucesso)
        self.assertEqual((resposta.texto, resposta.tokens_entrada, resposta.tokens_saida, resposta.erro),
                         ('A diária custa R$ 500,00.', 120, 30, ''))
        gerar.assert_called_once_with(
            modelo='gemini-modelo-x', mensagens=pergunta(), instrucoes_sistema='Seja breve.',
            temperatura=Decimal('0.30'), max_tokens=300, timeout_segundos=12, formato_json=False)
        r = RequisicaoIA.objects.get(pk=resposta.requisicao_id)
        self.assertEqual(
            (r.usuario, r.origem, r.modelo, r.tokens_entrada, r.tokens_saida, r.tokens_total, r.sucesso, r.erro),
            (self.user, Origem.ASSISTENTE, 'gemini-modelo-x', 120, 30, 150, True, ''))
        self.assertEqual(r.prompt, 'Usuário: Quanto custa a diária?')
        self.assertEqual(r.resposta, 'A diária custa R$ 500,00.')

    @patch(GERAR)
    def test_erro_do_provedor_e_auditado_e_nao_sobe(self, gerar):
        gerar.side_effect = ErroProvedorIA('Gemini HTTP 503 UNAVAILABLE: overloaded', 'Tente de novo.')
        with self.assertLogs('ia.services', level='WARNING'):
            resposta = services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)
        self.assertFalse(resposta.sucesso)
        self.assertEqual((resposta.texto, resposta.erro), ('', 'Tente de novo.'))
        r = RequisicaoIA.objects.get()
        self.assertFalse(r.sucesso)
        self.assertEqual(r.erro, 'Gemini HTTP 503 UNAVAILABLE: overloaded')
        self.assertEqual(r.prompt, 'Usuário: Quanto custa a diária?')

    @patch(GERAR)
    def test_excecao_inesperada_tambem_e_auditada(self, gerar):
        gerar.side_effect = RuntimeError('bug')
        with self.assertLogs('ia.services', level='ERROR'):
            resposta = services.chamar_ia(self.user, pergunta(), Origem.BOT)
        self.assertFalse(resposta.sucesso)
        self.assertIn('RuntimeError: bug', RequisicaoIA.objects.get().erro)

    @patch(GERAR)
    def test_resposta_vazia_conta_tokens_mas_falha(self, gerar):
        gerar.return_value = ok(texto='', entrada=50, saida=0)
        with self.assertLogs('ia.services', level='WARNING'):
            resposta = services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)
        self.assertFalse(resposta.sucesso)
        self.assertEqual(RequisicaoIA.objects.get().tokens_total, 50)

    @patch(GERAR)
    def test_chave_nunca_vai_para_a_auditoria(self, gerar):
        gerar.side_effect = ErroProvedorIA(f'falhou com a chave {CHAVE_TESTE} na mensagem')
        with self.assertLogs('ia.services', level='WARNING'):
            services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)
        erro = RequisicaoIA.objects.get().erro
        self.assertNotIn(CHAVE_TESTE, erro)
        self.assertIn('***', erro)

    @patch(GERAR)
    def test_prompt_truncado(self, gerar):
        gerar.return_value = ok()
        services.chamar_ia(self.user, pergunta('x' * 10_000), Origem.ASSISTENTE)
        self.assertEqual(len(RequisicaoIA.objects.get().prompt), RequisicaoIA.LIMITE_PROMPT)

    @patch(GERAR)
    def test_ia_desativada_bloqueia_sem_chamar_nem_auditar(self, gerar):
        self.config.ativo = False
        self.config.save()
        for origem in (Origem.ASSISTENTE, Origem.BOT, Origem.ANALISE):
            with self.subTest(origem), self.assertRaisesMessage(IADesativada, 'desativado'):
                services.chamar_ia(self.user, pergunta(), origem)
        gerar.assert_not_called()
        self.assertFalse(RequisicaoIA.objects.exists())

    @override_settings(GEMINI_API_KEY='')
    @patch(GERAR)
    def test_sem_chave_bloqueia(self, gerar):
        with self.assertRaisesMessage(IADesativada, 'falta a chave'):
            services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)
        gerar.assert_not_called()

    @patch(GERAR)
    def test_usuario_desabilitado_bloqueia_assistente_e_bot(self, gerar):
        gerar.return_value = ok()
        PerfilIAUsuario.objects.create(usuario=self.user, habilitado=False)
        for origem in (Origem.ASSISTENTE, Origem.BOT):
            with self.subTest(origem), self.assertRaisesMessage(IADesativada, 'desabilitado para a sua conta'):
                services.chamar_ia(self.user, pergunta(), origem)
        gerar.assert_not_called()
        # A análise de pedido é do sistema: não depende da habilitação do cliente.
        self.assertTrue(services.chamar_ia(self.user, pergunta(), Origem.ANALISE).sucesso)

    @patch(GERAR)
    def test_cota_excedida_bloqueia(self, gerar):
        gerar.return_value = ok()
        self.config.cota_mensal_padrao_tokens = 1000
        self.config.save()
        requisicao(self.user, 999)
        services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)  # ainda tinha 1 token
        with self.assertRaisesMessage(CotaExcedida, '1.000 tokens'):
            services.chamar_ia(self.user, pergunta(), Origem.BOT)
        self.assertEqual(gerar.call_count, 1)
        # Análise e teste não respeitam a cota do usuário.
        self.assertTrue(services.chamar_ia(self.user, pergunta(), Origem.ANALISE).sucesso)

    @patch(GERAR)
    def test_cota_propria_substitui_a_padrao(self, gerar):
        gerar.return_value = ok()
        requisicao(self.user, 5000)
        PerfilIAUsuario.objects.create(usuario=self.user, cota_mensal_tokens=10_000)
        self.assertEqual(services.cota_do_usuario(self.user), 10_000)
        self.assertTrue(services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE).sucesso)
        PerfilIAUsuario.objects.filter(usuario=self.user).update(cota_mensal_tokens=100)
        with self.assertRaises(CotaExcedida):
            services.chamar_ia(self.user, pergunta(), Origem.ASSISTENTE)

    def test_consumo_do_mes(self):
        outro = criar_usuario('maria')
        inicio = services.inicio_do_mes()
        requisicao(self.user, 100)
        requisicao(self.user, 200, Origem.BOT)
        requisicao(self.user, 4000, Origem.ANALISE)                  # não conta
        requisicao(self.user, 8000, criado_em=inicio - timedelta(seconds=1))  # mês passado
        requisicao(outro, 300)                                       # outro usuário
        self.assertEqual(services.consumo_do_mes(self.user), 300)
        self.assertEqual(services.consumo_do_mes(outro), 300)

    @patch(GERAR)
    def test_teste_de_conexao_ignora_ativo_e_cota(self, gerar):
        gerar.return_value = ok('OK', entrada=10, saida=1)
        self.config.ativo = False
        self.config.cota_mensal_padrao_tokens = 0
        self.config.save()
        resposta = services.testar_conexao(self.user)
        self.assertTrue(resposta.sucesso)
        self.assertEqual(RequisicaoIA.objects.get().origem, Origem.TESTE)

    @patch(GERAR)
    def test_ultima_mensagem_deve_ser_do_usuario(self, gerar):
        with self.assertRaises(ValueError):
            services.chamar_ia(self.user, [{'papel': 'assistente', 'conteudo': 'Oi'}], Origem.ASSISTENTE)
        with self.assertRaises(ValueError):
            services.chamar_ia(self.user, [], Origem.ASSISTENTE)

    @patch(GERAR)
    def test_formato_json_e_timeout_proprio(self, gerar):
        gerar.return_value = ok('{"a": 1}')
        services.chamar_ia(None, pergunta(), Origem.ANALISE, formato_json=True, timeout_segundos=8)
        self.assertTrue(gerar.call_args.kwargs['formato_json'])
        self.assertEqual(gerar.call_args.kwargs['timeout_segundos'], 8)
        self.assertIsNone(RequisicaoIA.objects.get().usuario)


class ModelosIATest(TestCase):
    def test_configuracao_e_singleton(self):
        config = ConfiguracaoIA.obter()
        self.assertEqual(config.pk, 1)
        outra = ConfiguracaoIA(modelo='outro')
        outra.save()
        self.assertEqual(ConfiguracaoIA.objects.count(), 1)
        self.assertEqual(ConfiguracaoIA.obter().modelo, 'outro')
        ConfiguracaoIA.obter().delete()
        self.assertTrue(ConfiguracaoIA.objects.exists())

    def test_custo_estimado(self):
        # 3.548 de entrada × US$ 0,30/1M + 100 de saída × US$ 2,50/1M = US$ 0,0013144
        r = RequisicaoIA(origem=Origem.ASSISTENTE, tokens_entrada=3548, tokens_saida=100)
        self.assertEqual(r.custo_usd, Decimal('0.00131440'))
        self.assertEqual(round(r.custo_brl, 6), Decimal('0.007229'))


class TelasIATest(TestCase):
    def setUp(self):
        self.admin_user = criar_usuario('ana', cliente=False, admin=True)
        self.cliente_user = criar_usuario('joao')
        self.outro_user = criar_usuario('maria')
        self.admin = Client()
        self.admin.force_login(self.admin_user)
        self.cli = Client()
        self.cli.force_login(self.cliente_user)

    def test_telas_admin_negam_cliente_e_visitante(self):
        r = requisicao(self.cliente_user, 10)
        urls = [reverse('ia:requisicoes'), reverse('ia:requisicao_detail', args=[r.pk]),
                reverse('ia:configuracao'), reverse('ia:usuarios'),
                reverse('ia:perfil_update', args=[self.cliente_user.pk])]
        for navegador in (self.cli, Client()):
            for url in urls:
                with self.subTest(url=url):
                    response = navegador.get(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse('login')))
            self.assertEqual(navegador.post(reverse('ia:testar_conexao')).status_code, 302)
        self.assertFalse(PerfilIAUsuario.objects.exists())  # nada foi criado pelo cliente

    def test_requisicoes_filtra_e_pagina_mantendo_filtros(self):
        for i in range(25):
            requisicao(self.cliente_user, 10, Origem.BOT, prompt=f'bot {i}')
        requisicao(self.outro_user, 10, Origem.ASSISTENTE, sucesso=False)
        url = reverse('ia:requisicoes')
        response = self.admin.get(url, {'origem': 'BOT', 'usuario': 'joa'})
        self.assertEqual(response.context['totais']['chamadas'], 25)
        self.assertEqual(len(response.context['requisicoes']), 20)
        self.assertContains(response, 'href="?origem=BOT&amp;usuario=joa&amp;page=2" rel="next">Próxima</a>')
        response = self.admin.get(url, {'sucesso': 'false'})
        self.assertEqual([r.usuario for r in response.context['requisicoes']], [self.outro_user])
        hoje = timezone.localdate().isoformat()
        response = self.admin.get(url, {'criado_em__gte': hoje, 'criado_em__lte': hoje})
        self.assertEqual(response.context['totais']['chamadas'], 26)

    def test_requisicoes_sem_n_mais_1(self):
        def medir():
            with CaptureQueriesContext(connection) as ctx:
                self.admin.get(reverse('ia:requisicoes'))
            return len(ctx)
        for i in range(3):
            requisicao(criar_usuario(f'u{i}'), 5)
        poucas = medir()
        for i in range(3, 15):
            requisicao(criar_usuario(f'u{i}'), 5)
        with self.assertNumQueries(poucas):  # sessão, usuário, contagem, totais, página (com usuário no JOIN)
            self.admin.get(reverse('ia:requisicoes'))

    def test_detalhe_da_requisicao(self):
        r = requisicao(self.cliente_user, 10, prompt='Usuário: tem piscina?')
        response = self.admin.get(reverse('ia:requisicao_detail', args=[r.pk]))
        self.assertContains(response, 'tem piscina?')

    @override_settings(GEMINI_API_KEY=CHAVE_TESTE)
    def test_configuracao_mostra_so_se_a_chave_existe(self):
        response = self.admin.get(reverse('ia:configuracao'))
        self.assertContains(response, '<span class="badge bg-success" id="chave-configurada">Sim</span>', html=True)
        self.assertNotContains(response, CHAVE_TESTE)
        with override_settings(GEMINI_API_KEY=''):
            response = self.admin.get(reverse('ia:configuracao'))
        self.assertContains(response, '<span class="badge bg-danger" id="chave-configurada">Não</span>', html=True)

    def test_configuracao_salva_e_registra_quem_alterou(self):
        response = self.admin.post(reverse('ia:configuracao'), {
            'ativo': 'on', 'provedor': 'GEMINI', 'modelo': 'gemini-3.6-flash', 'temperatura': '0.5',
            'max_tokens_resposta': 800, 'timeout_segundos': 15, 'cota_mensal_padrao_tokens': 20000})
        self.assertRedirects(response, reverse('ia:configuracao'))
        config = ConfiguracaoIA.obter()
        self.assertEqual((config.modelo, config.atualizado_por), ('gemini-3.6-flash', self.admin_user))
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ['Configuração da IA salva (modelo gemini-3.6-flash).'])

    def test_configuracao_valida_limites(self):
        response = self.admin.post(reverse('ia:configuracao'), {
            'provedor': 'GEMINI', 'modelo': 'x', 'temperatura': '3', 'max_tokens_resposta': 800,
            'timeout_segundos': 500, 'cota_mensal_padrao_tokens': 1})
        self.assertEqual(set(response.context['form'].errors), {'temperatura', 'timeout_segundos'})

    @override_settings(GEMINI_API_KEY=CHAVE_TESTE)
    @patch(GERAR)
    def test_testar_conexao(self, gerar):
        gerar.return_value = ok('OK', entrada=12, saida=1)
        response = self.admin.post(reverse('ia:testar_conexao'))
        self.assertRedirects(response, reverse('ia:configuracao'))
        mensagem = [m for m in get_messages(response.wsgi_request)][-1]
        self.assertEqual(mensagem.level_tag, 'success')
        self.assertIn('Conexão OK', str(mensagem))
        self.assertIn('13 tokens', str(mensagem))

        gerar.side_effect = ErroProvedorIA('HTTP 400 API key not valid')
        with self.assertLogs('ia.services', level='WARNING'):
            response = self.admin.post(reverse('ia:testar_conexao'))
        mensagem = [m for m in get_messages(response.wsgi_request)][-1]
        self.assertEqual(mensagem.level_tag, 'danger')
        self.assertIn('Falha na conexão', str(mensagem))

    def test_testar_conexao_sem_chave(self):
        response = self.admin.post(reverse('ia:testar_conexao'))
        mensagem = [m for m in get_messages(response.wsgi_request)][-1]
        self.assertEqual(mensagem.level_tag, 'danger')
        self.assertIn('falta a chave', str(mensagem))
        self.assertEqual(self.admin.get(reverse('ia:testar_conexao')).status_code, 405)

    def test_ia_por_usuario_com_annotate_e_datatables(self):
        config = ConfiguracaoIA.obter()
        config.cota_mensal_padrao_tokens = 1000
        config.save()
        requisicao(self.cliente_user, 250)
        requisicao(self.cliente_user, 50, Origem.BOT)
        requisicao(self.cliente_user, 9000, Origem.ANALISE)  # não conta
        requisicao(self.cliente_user, 9000, criado_em=services.inicio_do_mes() - timedelta(days=1))
        PerfilIAUsuario.objects.create(usuario=self.outro_user, habilitado=False, cota_mensal_tokens=40)

        response = self.admin.get(reverse('ia:usuarios'))
        self.assertContains(response, 'table-datatable')
        self.assertFalse(response.context.get('is_paginated'))
        por_nome = {u.username: u for u in response.context['usuarios']}
        joao, maria = por_nome['joao'], por_nome['maria']
        self.assertEqual((joao.consumo_mes, joao.cota_efetiva, joao.ia_habilitada), (300, 1000, True))
        self.assertEqual((maria.consumo_mes, maria.cota_efetiva, maria.ia_habilitada), (0, 40, False))

    def test_ia_por_usuario_numero_de_consultas_nao_cresce(self):
        ConfiguracaoIA.obter()
        for i in range(12):
            u = criar_usuario(f'cliente{i}')
            requisicao(u, 10)
            PerfilIAUsuario.objects.create(usuario=u, cota_mensal_tokens=100)
        # sessão + usuário (com perfis) + configuração + lista com annotate (consumo, habilitada, cota)
        with self.assertNumQueries(4):
            self.admin.get(reverse('ia:usuarios'))

    def test_editar_perfil_cria_na_primeira_vez(self):
        url = reverse('ia:perfil_update', args=[self.cliente_user.pk])
        self.assertEqual(self.admin.get(url).status_code, 200)
        self.assertTrue(PerfilIAUsuario.objects.filter(usuario=self.cliente_user).exists())
        response = self.admin.post(url, {'cota_mensal_tokens': 500})  # "habilitado" desmarcado
        self.assertRedirects(response, reverse('ia:usuarios'))
        perfil = PerfilIAUsuario.objects.get(usuario=self.cliente_user)
        self.assertEqual((perfil.habilitado, perfil.cota_mensal_tokens), (False, 500))
        self.assertEqual([str(m) for m in get_messages(response.wsgi_request)],
                         ['Uso da IA de joao atualizado.'])
        self.assertEqual(self.admin.get(reverse('ia:perfil_update', args=[99999])).status_code, 404)

    def test_meu_consumo_so_mostra_dados_proprios(self):
        config = ConfiguracaoIA.obter()
        config.cota_mensal_padrao_tokens = 1000
        config.save()
        requisicao(self.cliente_user, 250, prompt='Usuário: minha pergunta sobre piscina')
        requisicao(self.cliente_user, 500, Origem.ANALISE, prompt='Análise do pedido #1')
        requisicao(self.outro_user, 400, prompt='Usuário: pergunta secreta da Maria')

        response = self.cli.get(reverse('ia:meu_consumo'))
        self.assertEqual((response.context['consumo'], response.context['cota'], response.context['percentual']),
                         (250, 1000, 25))
        self.assertEqual([r.usuario for r in response.context['ultimas']], [self.cliente_user])
        self.assertContains(response, 'minha pergunta sobre piscina')
        self.assertNotContains(response, 'pergunta secreta da Maria')
        self.assertNotContains(response, 'Análise do pedido')
        self.assertRedirects(Client().get(reverse('ia:meu_consumo')),
                             f"{reverse('login')}?next={reverse('ia:meu_consumo')}")

    def test_menus(self):
        response = self.admin.get(reverse('index'))
        for nome in ('ia:requisicoes', 'ia:usuarios', 'ia:configuracao', 'ia:meu_consumo'):
            self.assertContains(response, reverse(nome))
        response = self.cli.get(reverse('index'))
        self.assertContains(response, reverse('ia:meu_consumo'))
        self.assertNotContains(response, reverse('ia:requisicoes'))


class ConsultasMeuConsumoTest(TestCase):
    @override_settings(GEMINI_API_KEY=CHAVE_TESTE)
    def test_meu_consumo_numero_fixo_de_consultas(self):
        ConfiguracaoIA.obter()
        user = criar_usuario('joao')
        for _ in range(15):
            requisicao(user, 10)
        c = Client()
        c.force_login(user)
        # sessão + usuário + grupos (navbar) + configuração + perfil + consumo do mês + últimas 10
        with self.assertNumQueries(7):
            c.get(reverse('ia:meu_consumo'))
