"""Testes do bot do Telegram. A API do Telegram é sempre mockada
(telegram_bot.api._post ou requests.post): nenhum teste acessa a internet."""
import itertools
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ia.models import PerfilIAUsuario, RequisicaoIA
from ia.provedores.base import ResultadoProvedor
from website.models import Administrador, Chacara, Cliente, Reserva

from . import api
from .models import CodigoVinculacao, MensagemTelegram, TentativaVinculoInvalida, VinculoTelegram

TOKEN = '123456:TOKEN-DE-TESTE'
SEGREDO = 'segredo-do-webhook-de-teste'
CONFIG = dict(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_WEBHOOK_SECRET=SEGREDO, TELEGRAM_BOT_USERNAME='SitioDeLurdesBot')
POST = 'telegram_bot.api._post'

_update_ids = itertools.count(1000)


def update_mensagem(texto, chat_id=111, user_id=111, tipo_chat='private', username='joao_tg'):
    return {'update_id': next(_update_ids), 'message': {
        'message_id': 1, 'text': texto, 'chat': {'id': chat_id, 'type': tipo_chat},
        'from': {'id': user_id, 'username': username, 'first_name': 'João'}}}


def update_callback(dado, chat_id=111, user_id=111, message_id=77):
    return {'update_id': next(_update_ids), 'callback_query': {
        'id': f'cb{next(_update_ids)}', 'data': dado, 'from': {'id': user_id},
        'message': {'message_id': message_id, 'chat': {'id': chat_id, 'type': 'private'}}}}


def chamadas(mock_post, metodo):
    return [c.args[1] for c in mock_post.call_args_list if c.args[0] == metodo]


def textos_enviados(mock_post):
    return [d['text'] for d in chamadas(mock_post, 'sendMessage')]


@override_settings(**CONFIG)
class BaseBotTest(TestCase):
    def setUp(self):
        self.chacara = Chacara.objects.order_by('pk').first()
        self.cliente_user = User.objects.create_user('joao', password='testpass123')
        self.cliente = Cliente.objects.create(nome='João Silva', telefone='11999990000', usuario=self.cliente_user)
        self.admin_user = User.objects.create_user('ana', password='testpass123')
        Administrador.objects.create(nome='Ana Admin', usuario=self.admin_user)
        self.web = Client()
        patcher = patch(POST, return_value={'message_id': 99})
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def webhook(self, update, segredo=SEGREDO):
        cabecalhos = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': segredo} if segredo is not None else {}
        return self.web.post(reverse('telegram_bot:webhook'), json.dumps(update),
                             content_type='application/json', **cabecalhos)

    def vincular(self, usuario, chat_id=111, user_id=None):
        return VinculoTelegram.objects.create(usuario=usuario, chat_id=chat_id, telegram_user_id=user_id or chat_id)

    def reserva(self, cliente=None, inicio=10, fim=13, status=Reserva.STATUS_PENDENTE):
        hoje = timezone.localdate()
        return Reserva.objects.create(cliente=cliente or self.cliente, chacara=self.chacara, status=status,
                                      data_inicio=hoje + timedelta(days=inicio), data_fim=hoje + timedelta(days=fim))


class WebhookSegurancaTest(BaseBotTest):
    def test_segredo_errado_ou_ausente_403(self):
        self.assertEqual(self.webhook(update_mensagem('/ajuda'), segredo='errado').status_code, 403)
        self.assertEqual(self.webhook(update_mensagem('/ajuda'), segredo=None).status_code, 403)
        self.post.assert_not_called()
        self.assertFalse(MensagemTelegram.objects.exists())

    def test_segredo_certo_200_sem_csrf(self):
        self.web = Client(enforce_csrf_checks=True)  # o Telegram não manda CSRF
        response = self.webhook(update_mensagem('/ajuda'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('/chacara', textos_enviados(self.post)[0])

    @override_settings(TELEGRAM_WEBHOOK_SECRET='')
    def test_sem_configuracao_503(self):
        self.assertEqual(self.webhook(update_mensagem('/ajuda'), segredo='').status_code, 503)

    def test_so_post(self):
        self.assertEqual(self.web.get(reverse('telegram_bot:webhook')).status_code, 405)

    def test_update_repetido_e_ignorado(self):
        update = update_mensagem('/ajuda')
        self.webhook(update)
        self.webhook(update)  # o Telegram reenviou
        self.assertEqual(len(textos_enviados(self.post)), 1)
        self.assertEqual(MensagemTelegram.objects.filter(direcao=MensagemTelegram.ENTRADA).count(), 1)

    def test_erro_interno_responde_200(self):
        with patch('telegram_bot.bot.processar_update', side_effect=RuntimeError('bug')), \
                self.assertLogs('telegram_bot.views', level='ERROR'):
            self.assertEqual(self.webhook(update_mensagem('/ajuda')).status_code, 200)
        with self.assertLogs('telegram_bot.views', level='ERROR'):
            response = self.web.post(reverse('telegram_bot:webhook'), 'não é json', content_type='application/json',
                                     HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SEGREDO)
        self.assertEqual(response.status_code, 200)

    def test_chat_em_grupo_e_recusado(self):
        self.vincular(self.cliente_user)
        self.webhook(update_mensagem('/minhasreservas', chat_id=-500, tipo_chat='group'))
        self.assertIn('chat privado', textos_enviados(self.post)[0])

    def test_log_de_entrada_e_saida(self):
        self.vincular(self.cliente_user)
        self.webhook(update_mensagem('/chacara'))
        entrada = MensagemTelegram.objects.get(direcao=MensagemTelegram.ENTRADA)
        saida = MensagemTelegram.objects.get(direcao=MensagemTelegram.SAIDA)
        self.assertEqual((entrada.tipo, entrada.texto, entrada.usuario, entrada.telegram_user_id),
                         (MensagemTelegram.COMANDO, '/chacara', self.cliente_user, 111))
        self.assertEqual(saida.usuario, self.cliente_user)
        self.assertIn('Diária', saida.texto)


class VinculoTest(BaseBotTest):
    def _codigo(self, usuario=None, **campos):
        codigo = CodigoVinculacao.gerar_para(usuario or self.cliente_user)
        if campos:
            CodigoVinculacao.objects.filter(pk=codigo.pk).update(**campos)
        return codigo.codigo

    def test_codigo_valido_pelo_deep_link_start(self):
        codigo = self._codigo()
        self.webhook(update_mensagem(f'/start {codigo}', chat_id=555, user_id=555, username='joaotg'))
        vinculo = VinculoTelegram.objects.get(usuario=self.cliente_user)
        self.assertEqual((vinculo.chat_id, vinculo.telegram_user_id, vinculo.username), (555, 555, 'joaotg'))
        self.assertIsNotNone(CodigoVinculacao.objects.get(codigo=codigo).usado_em)
        self.assertIn('foi vinculada', textos_enviados(self.post)[-1])

    def test_codigo_reutilizado_e_recusado(self):
        codigo = self._codigo()
        self.webhook(update_mensagem(f'/vincular {codigo}', chat_id=555, user_id=555))
        self.webhook(update_mensagem(f'/vincular {codigo}', chat_id=666, user_id=666))
        self.assertEqual(VinculoTelegram.objects.get(usuario=self.cliente_user).chat_id, 555)
        self.assertIn('inválido, expirado ou já usado', textos_enviados(self.post)[-1])

    def test_codigo_expirado_e_recusado(self):
        codigo = self._codigo(expira_em=timezone.now() - timedelta(seconds=1))
        self.webhook(update_mensagem(f'/vincular {codigo}'))
        self.assertFalse(VinculoTelegram.objects.exists())
        self.assertIn('inválido, expirado ou já usado', textos_enviados(self.post)[-1])

    def test_gerar_novo_invalida_o_anterior(self):
        antigo = self._codigo()
        self._codigo()
        self.webhook(update_mensagem(f'/vincular {antigo}'))
        self.assertFalse(VinculoTelegram.objects.exists())

    @override_settings(TELEGRAM_TENTATIVAS_VINCULO_POR_HORA=5)
    def test_limite_de_tentativas_invalidas_por_remetente(self):
        for _ in range(5):
            self.webhook(update_mensagem('/vincular codigo-errado-123'))
        self.assertEqual(TentativaVinculoInvalida.objects.filter(telegram_user_id=111).count(), 5)
        valido = self._codigo()
        self.webhook(update_mensagem(f'/vincular {valido}'))  # bloqueado, mesmo com código bom
        self.assertFalse(VinculoTelegram.objects.exists())
        self.assertIn('Muitas tentativas', textos_enviados(self.post)[-1])
        self.webhook(update_mensagem(f'/vincular {valido}', chat_id=222, user_id=222))  # outro remetente
        self.assertTrue(VinculoTelegram.objects.filter(chat_id=222).exists())

    def test_desvincular(self):
        self.vincular(self.cliente_user)
        self.webhook(update_mensagem('/desvincular'))
        self.assertFalse(VinculoTelegram.objects.exists())

    def test_tela_conectar_gera_codigo_e_link(self):
        self.web.force_login(self.cliente_user)
        self.assertEqual(self.web.get(reverse('telegram_bot:gerar_codigo')).status_code, 405)
        response = self.web.post(reverse('telegram_bot:gerar_codigo'), follow=True)
        codigo = CodigoVinculacao.objects.get(usuario=self.cliente_user).codigo
        self.assertContains(response, f'https://t.me/SitioDeLurdesBot?start={codigo}')
        self.assertContains(response, f'/vincular {codigo}')
        self.assertNotContains(response, TOKEN)
        self.assertNotContains(response, SEGREDO)
        outro = Client()
        outro.force_login(self.admin_user)
        self.assertNotContains(outro.get(reverse('telegram_bot:conectar')), codigo)

    def test_tela_conectar_desvincula(self):
        self.vincular(self.cliente_user)
        self.web.force_login(self.cliente_user)
        response = self.web.get(reverse('telegram_bot:conectar'))
        self.assertContains(response, 'Vinculado')
        self.assertContains(response, 'data-confirmar="Desvincular')
        self.web.post(reverse('telegram_bot:desvincular'))
        self.assertFalse(VinculoTelegram.objects.exists())

    def test_tela_conectar_exige_login(self):
        url = reverse('telegram_bot:conectar')
        self.assertRedirects(Client().get(url), f"{reverse('login')}?next={url}")


class LimiteTest(BaseBotTest):
    @override_settings(TELEGRAM_LIMITE_POR_MINUTO=3)
    def test_limite_por_minuto_avisa_uma_vez_e_ignora(self):
        for _ in range(6):
            self.webhook(update_mensagem('/ajuda'))
        textos = textos_enviados(self.post)
        self.assertEqual(len(textos), 4)  # 3 respostas + 1 aviso; o resto é ignorado
        self.assertEqual(textos[-1], 'Muitas mensagens, aguarde um pouco.')
        self.assertEqual(MensagemTelegram.objects.filter(direcao='ENTRADA').count(), 6)  # tudo registrado
        self.assertEqual(MensagemTelegram.objects.filter(aviso_limite=True).count(), 1)

    @override_settings(TELEGRAM_LIMITE_POR_DIA=2)
    def test_limite_por_dia(self):
        for _ in range(4):
            self.webhook(update_mensagem('/ajuda'))
        self.assertEqual(textos_enviados(self.post)[-1], 'Muitas mensagens, aguarde um pouco.')
        self.assertEqual(len(textos_enviados(self.post)), 3)

    @override_settings(TELEGRAM_LIMITE_POR_MINUTO=1)
    def test_limite_e_por_remetente(self):
        self.webhook(update_mensagem('/ajuda', chat_id=1, user_id=1))
        self.webhook(update_mensagem('/ajuda', chat_id=2, user_id=2))
        self.assertNotIn('Muitas mensagens, aguarde um pouco.', textos_enviados(self.post))


class ComandosTest(BaseBotTest):
    def test_chacara_e_disponibilidade_sem_nomes(self):
        confirmada = self.reserva(status=Reserva.STATUS_CONFIRMADA)
        self.webhook(update_mensagem('/chacara'))
        self.webhook(update_mensagem('/disponibilidade'))
        chacara, disponibilidade = textos_enviados(self.post)
        self.assertIn(self.chacara.nome, chacara)
        self.assertIn('Diária: R$', chacara)
        self.assertIn(f'{confirmada.data_inicio:%d/%m/%Y}', disponibilidade)
        self.assertNotIn('João', disponibilidade)

    def test_minhasreservas_exige_vinculo(self):
        self.webhook(update_mensagem('/minhasreservas'))
        self.assertIn('vincule sua conta', textos_enviados(self.post)[0])

    def test_minhasreservas_com_botao_cancelar_so_nas_pendentes(self):
        self.vincular(self.cliente_user)
        pendente = self.reserva()
        self.reserva(inicio=30, fim=32, status=Reserva.STATUS_CONFIRMADA)
        self.reserva(cliente=Cliente.objects.create(nome='Outro', telefone='1', usuario=User.objects.create_user('o')),
                     inicio=50, fim=52)
        self.webhook(update_mensagem('/minhasreservas'))
        envios = chamadas(self.post, 'sendMessage')
        self.assertEqual(len(envios), 2)  # resumo + 1 pendente com botão
        self.assertNotIn('Outro', envios[0]['text'])
        self.assertEqual(envios[1]['reply_markup'],
                         {'inline_keyboard': [[{'text': 'Cancelar pedido', 'callback_data': f'can:{pendente.pk}'}]]})

    def test_pendentes_so_para_admin(self):
        self.vincular(self.cliente_user)
        self.reserva()
        self.webhook(update_mensagem('/pendentes'))
        self.assertIn('só para a administração', textos_enviados(self.post)[-1])

    def test_pendentes_do_admin_com_botoes(self):
        self.vincular(self.admin_user, chat_id=222)
        pedido = self.reserva()
        self.webhook(update_mensagem('/pendentes', chat_id=222, user_id=222))
        envios = chamadas(self.post, 'sendMessage')
        self.assertIn('1 pedido(s) pendente(s)', envios[0]['text'])
        self.assertIn('João Silva', envios[1]['text'])
        botoes = envios[1]['reply_markup']['inline_keyboard'][0]
        self.assertEqual([b['callback_data'] for b in botoes], [f'apr:{pedido.pk}', f'rec:{pedido.pk}'])

    def test_comando_desconhecido_e_texto_livre(self):
        self.webhook(update_mensagem('/xyz'))
        self.webhook(update_mensagem('oi'))
        self.assertIn('desconhecido', textos_enviados(self.post)[0])
        self.assertIn('/ajuda', textos_enviados(self.post)[1])

    @override_settings(GEMINI_API_KEY='chave-de-teste')
    @patch('ia.provedores.gemini.gerar')
    def test_perguntar_usa_a_ia_com_origem_bot(self, gerar):
        gerar.return_value = ResultadoProvedor(texto='Sim, tem piscina!', tokens_entrada=50, tokens_saida=5)
        self.vincular(self.cliente_user)
        self.webhook(update_mensagem('/perguntar Tem piscina?'))
        self.assertEqual(textos_enviados(self.post)[-1], 'Sim, tem piscina!')
        requisicao = RequisicaoIA.objects.get()
        self.assertEqual((requisicao.origem, requisicao.usuario), (RequisicaoIA.Origem.BOT, self.cliente_user))
        self.assertEqual(gerar.call_args.kwargs['mensagens'], [{'papel': 'usuario', 'conteudo': 'Tem piscina?'}])

    @override_settings(GEMINI_API_KEY='chave-de-teste')
    @patch('ia.provedores.gemini.gerar')
    def test_perguntar_respeita_cota_e_vinculo(self, gerar):
        self.webhook(update_mensagem('/perguntar Oi'))
        self.assertIn('vincule sua conta', textos_enviados(self.post)[-1])
        self.vincular(self.cliente_user)
        PerfilIAUsuario.objects.create(usuario=self.cliente_user, cota_mensal_tokens=0)
        self.webhook(update_mensagem('/perguntar Oi'))
        self.assertIn('cota mensal', textos_enviados(self.post)[-1])
        gerar.assert_not_called()

    def test_perguntar_sem_chave(self):
        self.vincular(self.cliente_user)
        self.webhook(update_mensagem('/perguntar Oi'))
        self.assertIn('não está configurada', textos_enviados(self.post)[-1])


class CallbackTest(BaseBotTest):
    def test_cliente_nao_aprova_pelo_botao(self):
        self.vincular(self.cliente_user)
        pedido = self.reserva()
        self.webhook(update_callback(f'apr:{pedido.pk}'))
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_PENDENTE)
        self.assertIn('Apenas a administração', chamadas(self.post, 'answerCallbackQuery')[0]['text'])
        self.assertEqual(chamadas(self.post, 'editMessageText'), [])

    def test_admin_aprova_e_a_mensagem_e_editada(self):
        self.vincular(self.admin_user, chat_id=222)
        pedido = self.reserva()
        self.webhook(update_callback(f'apr:{pedido.pk}', chat_id=222, user_id=222, message_id=8))
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_CONFIRMADA)
        self.assertEqual(pedido.historico.get().alterado_por, self.admin_user)
        self.assertEqual(chamadas(self.post, 'answerCallbackQuery')[0]['text'], 'Pedido aprovado.')
        edicao = chamadas(self.post, 'editMessageText')[0]
        self.assertEqual((edicao['chat_id'], edicao['message_id']), (222, 8))
        self.assertIn('APROVADO', edicao['text'])
        self.assertEqual(edicao['reply_markup'], {'inline_keyboard': []})  # botões somem

    def test_admin_recusa(self):
        self.vincular(self.admin_user, chat_id=222)
        pedido = self.reserva()
        self.webhook(update_callback(f'rec:{pedido.pk}', chat_id=222, user_id=222))
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_RECUSADA)

    def test_cliente_cancela_so_o_proprio(self):
        self.vincular(self.cliente_user)
        meu = self.reserva()
        alheio = self.reserva(cliente=Cliente.objects.create(
            nome='Maria', telefone='1', usuario=User.objects.create_user('maria')), inicio=40, fim=42)
        self.webhook(update_callback(f'can:{alheio.pk}'))
        self.webhook(update_callback(f'can:{meu.pk}'))
        meu.refresh_from_db()
        alheio.refresh_from_db()
        self.assertEqual((meu.status, alheio.status), (Reserva.STATUS_CANCELADA, Reserva.STATUS_PENDENTE))
        respostas = [d['text'] for d in chamadas(self.post, 'answerCallbackQuery')]
        self.assertEqual(respostas, ['Pedido não encontrado.', 'Pedido cancelado.'])

    def test_botao_de_conversa_nao_vinculada_ou_de_outra_conta(self):
        self.vincular(self.admin_user, chat_id=222, user_id=222)
        pedido = self.reserva()
        self.webhook(update_callback(f'apr:{pedido.pk}', chat_id=999, user_id=999))   # não vinculada
        self.webhook(update_callback(f'apr:{pedido.pk}', chat_id=222, user_id=333))   # conta diferente no mesmo chat
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Reserva.STATUS_PENDENTE)
        for resposta in chamadas(self.post, 'answerCallbackQuery'):
            self.assertIn('vincule sua conta', resposta['text'])

    def test_callback_invalido(self):
        self.vincular(self.admin_user, chat_id=222)
        self.webhook(update_callback('apagar:tudo', chat_id=222, user_id=222))
        self.assertEqual(chamadas(self.post, 'answerCallbackQuery')[0]['text'], 'Botão inválido.')

    def test_callback_registrado_no_log(self):
        self.vincular(self.admin_user, chat_id=222)
        pedido = self.reserva()
        self.webhook(update_callback(f'rec:{pedido.pk}', chat_id=222, user_id=222))
        entrada = MensagemTelegram.objects.get(direcao='ENTRADA')
        self.assertEqual((entrada.tipo, entrada.texto, entrada.usuario), ('CALLBACK', f'rec:{pedido.pk}', self.admin_user))
        self.assertEqual(MensagemTelegram.objects.filter(direcao='SAIDA').count(), 2)  # aviso + edição


@override_settings(**CONFIG)
class ApiTest(TestCase):
    def test_erro_do_requests_nao_vaza_o_token(self):
        erro = requests.ConnectionError(f'Max retries exceeded with url: /bot{TOKEN}/sendMessage')
        with patch('telegram_bot.api.requests.post', side_effect=erro) as post:
            with self.assertRaises(api.ErroTelegram) as contexto:
                api.enviar_mensagem(1, 'oi')
        self.assertNotIn(TOKEN, str(contexto.exception))
        self.assertIn('<TOKEN>', str(contexto.exception))
        self.assertIsNone(contexto.exception.__cause__)
        self.assertTrue(contexto.exception.__suppress_context__)
        self.assertEqual(post.call_args.kwargs['timeout'], 10)

    def test_resposta_nao_ok_vira_erro(self):
        class Resposta:
            def json(self):
                return {'ok': False, 'error_code': 400, 'description': 'Bad Request: chat not found'}
        with patch('telegram_bot.api.requests.post', return_value=Resposta()):
            with self.assertRaisesMessage(api.ErroTelegram, 'chat not found'):
                api.enviar_mensagem(1, 'oi')

    def test_texto_longo_e_cortado(self):
        with patch(POST) as post:
            api.enviar_mensagem(1, 'x' * 5000)
        self.assertEqual(len(post.call_args.args[1]['text']), api.LIMITE_TEXTO)

    @override_settings(TELEGRAM_BOT_TOKEN='')
    def test_sem_token(self):
        with self.assertRaisesMessage(api.ErroTelegram, 'não configurado'):
            api.enviar_mensagem(1, 'oi')


@override_settings(**CONFIG)
class ComandosDeGestaoTest(TestCase):
    def test_configurar_webhook(self):
        saida = StringIO()
        with patch(POST, return_value=True) as post:
            call_command('configurar_webhook', '--url', 'https://exemplo.appspot.com/telegram/webhook/', stdout=saida)
        metodo, dados = post.call_args.args
        self.assertEqual(metodo, 'setWebhook')
        self.assertEqual(dados, {'url': 'https://exemplo.appspot.com/telegram/webhook/', 'secret_token': SEGREDO,
                                 'allowed_updates': ['message', 'callback_query']})
        self.assertNotIn(SEGREDO, saida.getvalue())
        self.assertNotIn(TOKEN, saida.getvalue())

    def test_configurar_webhook_valida_url(self):
        with patch(POST) as post:
            with self.assertRaises(CommandError):
                call_command('configurar_webhook', '--url', 'http://exemplo.com/telegram/webhook/')
            with self.assertRaises(CommandError):
                call_command('configurar_webhook', '--url', 'https://exemplo.com/outra/')
        post.assert_not_called()

    def test_info_e_remover(self):
        saida = StringIO()
        info = {'url': 'https://exemplo/telegram/webhook/', 'pending_update_count': 2,
                'last_error_date': 1760000000, 'last_error_message': 'Wrong response from the webhook: 403 Forbidden',
                'allowed_updates': ['message', 'callback_query']}
        with patch(POST, return_value=info):
            call_command('info_webhook', stdout=saida)
        self.assertIn('Atualizações pendentes: 2', saida.getvalue())
        self.assertIn('403 Forbidden', saida.getvalue())
        with patch(POST, return_value=True) as post:
            call_command('remover_webhook', '--descartar-pendentes', stdout=StringIO())
        self.assertEqual(post.call_args.args, ('deleteWebhook', {'drop_pending_updates': True}))


class TelaMensagensTest(TestCase):
    def test_so_admin_e_sem_n_mais_1(self):
        admin = User.objects.create_user('ana', password='x')
        Administrador.objects.create(nome='Ana', usuario=admin)
        cliente = User.objects.create_user('joao', password='x')
        for i in range(40):
            MensagemTelegram.objects.create(direcao='ENTRADA', update_id=i, chat_id=1, telegram_user_id=1,
                                            usuario=cliente, tipo='COMANDO', texto=f'/ajuda {i}')
        c = Client()
        c.force_login(cliente)
        self.assertEqual(c.get(reverse('telegram_bot:mensagens')).status_code, 302)
        c.force_login(admin)
        with self.assertNumQueries(4):  # sessão + usuário + contagem + página (usuário no JOIN)
            response = c.get(reverse('telegram_bot:mensagens'), {'tipo': 'COMANDO'})
        self.assertEqual(len(response.context['mensagens_bot']), 30)
        self.assertContains(response, 'href="?tipo=COMANDO&amp;page=2" rel="next"')
