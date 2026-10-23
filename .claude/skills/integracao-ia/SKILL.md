---
name: integracao-ia
description: Use sempre que for usar IA (Gemini) em qualquer parte do sistema — assistente, bot, análise de pedido ou recurso novo — para passar pela única porta de entrada ia.services.chamar_ia, com auditoria, cota por usuário e testes com o provedor mockado.
---

## Regra de ouro

**Toda chamada de IA passa por `ia.services.chamar_ia`.** Nenhuma view,
service, comando ou bot fala com o SDK. O SDK (`google.genai`) só pode ser
importado em `ia/provedores/gemini.py` — o teste
`ia.tests.SdkIsoladoTest` varre o código-fonte e falha se aparecer em outro arquivo.

## Assinatura

```python
from ia.models import RequisicaoIA
from ia.services import CotaExcedida, IADesativada, chamar_ia

resposta = chamar_ia(
    usuario=request.user,                 # User, ou None para chamada do sistema
    mensagens=[                           # conversa em ordem cronológica
        {'papel': 'usuario', 'conteudo': 'Quanto custa a diária?'},
    ],
    origem=RequisicaoIA.Origem.ASSISTENTE,
    instrucoes_sistema='Você é o assistente...',   # opcional
    formato_json=False,                   # True: pede application/json ao modelo
    timeout_segundos=None,                # None: usa o da ConfiguracaoIA
)
```

Devolve `RespostaIA(texto, tokens_entrada, tokens_saida, sucesso, erro, requisicao_id)`.

- `papel` é `'usuario'` ou `'assistente'`; a última mensagem é a do usuário.
- **Sem dados pessoais** de outros usuários nas mensagens ou nas instruções
  (nome, telefone, observações de clientes). Datas ocupadas, sim; quem
  reservou, não.

## Fluxo interno (o que `chamar_ia` garante)

1. Carrega `ConfiguracaoIA.obter()` (singleton editável em **IA → Configuração**).
2. `ativo` desligado ou `GEMINI_API_KEY` ausente → **`IADesativada`**.
3. Para origens com cota (`ASSISTENTE`, `BOT`) e usuário informado:
   `PerfilIAUsuario.habilitado == False` → `IADesativada`; consumo do mês
   ≥ cota → **`CotaExcedida`**.
4. Chama o provedor com o timeout da configuração.
5. **Sempre** grava uma `RequisicaoIA` (prompt e resposta truncados, tokens,
   duração, sucesso, erro) — com sucesso ou com erro.
6. Erro do provedor (`ErroProvedorIA`, inclusive timeout) **não** sobe como
   exceção: volta `RespostaIA(sucesso=False, erro='mensagem amigável')`.

| Origem | Conta na cota do usuário? | Respeita `ativo`? |
| --- | --- | --- |
| `ASSISTENTE` | sim | sim |
| `BOT` | sim | sim |
| `ANALISE` (análise de pedido) | não (é do sistema) | sim |
| `TESTE` (botão Testar conexão) | não | não — serve para testar antes de ligar |

## Uso típico numa view

```python
try:
    resposta = chamar_ia(request.user, mensagens, RequisicaoIA.Origem.ASSISTENTE, INSTRUCOES)
except CotaExcedida as erro:
    return JsonResponse({'erro': str(erro)}, status=429)
except IADesativada as erro:
    return JsonResponse({'erro': str(erro)}, status=503)
if not resposta.sucesso:
    return JsonResponse({'erro': resposta.erro}, status=502)
```

Outras funções: `consumo_do_mes(usuario)`, `cota_do_usuario(usuario)`,
`testar_conexao(usuario)`.

## Segredos

- A chave fica **só** em `GEMINI_API_KEY` no ambiente — nunca no banco, em
  template, log ou teste. A tela de configuração mostra apenas "configurada: sim/não".
- O modelo, a temperatura, o limite de tokens, o timeout e a cota padrão são
  editáveis na tela (ficam no banco); a chave não.

## Testes

- Mock do provedor, nunca da rede:

  ```python
  from unittest.mock import patch
  from ia.provedores.base import ResultadoProvedor

  @override_settings(GEMINI_API_KEY='chave-de-teste')
  @patch('ia.provedores.gemini.gerar')
  def test_algo(self, gerar):
      gerar.return_value = ResultadoProvedor(texto='Oi!', tokens_entrada=10, tokens_saida=5)
      ...
      args = gerar.call_args.kwargs      # confira o que foi enviado (mensagens, instruções)
  ```

- Falha do provedor: `gerar.side_effect = ErroProvedorIA('timeout')` e confira
  que a `RequisicaoIA` foi gravada com `sucesso=False`.
- Nos testes a `GEMINI_API_KEY` vem vazia do settings; sem o
  `override_settings` a IA fica desativada (útil para testar o caminho "indisponível").
- Nenhum teste importa o SDK nem acessa a internet.

## Checklist para um recurso novo com IA

- [ ] Nova origem em `RequisicaoIA.Origem` (com migration) se for um uso novo.
- [ ] Instruções de sistema numa constante/arquivo próprio, com limites claros.
- [ ] Trata `IADesativada`, `CotaExcedida` e `sucesso=False` com mensagem amigável.
- [ ] Saída da IA exibida com escape (ou `markdown_seguro`), nunca `|safe` cru.
- [ ] Testes com o provedor mockado conferindo o que foi enviado.
