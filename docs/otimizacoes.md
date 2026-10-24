# Otimização de consultas (Debug Toolbar + `select_related`)

## Como foi medido

- **Debug Toolbar**: com `DEBUG=True`, `python manage.py runserver` e o painel
  **SQL** aberto em cada tela (o toolbar só carrega com `DEBUG=True` e fora
  dos testes — ver `naes2026/settings.py`).
- **Números da tabela**: as mesmas consultas que o painel SQL lista, contadas
  com `django.test.utils.CaptureQueriesContext` num banco de verificação com
  dados fictícios, com **5 e com 15 registros** por lista. Se a contagem
  muda com o volume, é N+1.
- **Trava**: `website.tests.NumeroDeConsultasTest` (e os testes de número de
  consultas dos apps `ia` e `assistente`) usam `assertNumQueries` com mais
  registros do que uma página — se alguém remover um `select_related`, o teste quebra.

Base de toda página com usuário logado: **sessão (1) + usuário (1)**. Antes,
a navbar ainda fazia +1 consulta para `user.cliente`, +1 para
`user.administrador` e +1 para os grupos (às vezes repetida pela view).

## Resultado

| Tela | Queries antes | Queries depois | O que foi feito |
| --- | :-: | :-: | --- |
| Início (visitante) | 1 | 1 | — (só a chácara) |
| A Chácara (visitante) | 2 | 2 | média e quantidade de avaliações num único `aggregate` |
| Disponibilidade (visitante) | 3 | 3 | `select_related('cliente')` na lista e nos eventos (para o admin ver o nome sem 1 query por linha) |
| Disponibilidade (admin) | 7 | 5 | perfil carregado junto com o usuário + `usuario_eh_admin` em cache por requisição (antes a view e a navbar perguntavam de novo) |
| Minhas Reservas | 7 | 5 | `select_related('chacara', 'avaliacao')` (link "Avaliar"/"Ver avaliação" sem 1 query por linha) + perfil junto com o usuário |
| Detalhe da reserva (cliente) | 8 | 6 | `select_related('cliente', 'chacara')` + `prefetch_related('historico__alterado_por')` + perfil |
| Minhas Avaliações | 8 | 6 | `select_related('reserva__chacara')` + perfil |
| Detalhe da avaliação | 6 | 4 | `select_related('reserva__chacara')` + perfil |
| Pedidos Pendentes | 6 | 4 | `select_related('cliente', 'chacara')` + perfil |
| Todas as Reservas | 6 | 4 | `select_related('cliente', 'chacara')` + perfil |
| Detalhe da reserva (admin) | 6 | 4 | `select_related` + `prefetch_related` do histórico + perfil (com histórico: +2 fixas, não por linha) |
| Editar reserva (admin) | 6 | 4 | `get_queryset` com `select_related('cliente', 'chacara')` (a mensagem de sucesso usa o nome do cliente) + perfil |
| Excluir reserva (admin) | 5 | 3 | `select_related('cliente', 'chacara')` + perfil |
| Aprovar pedido (confirmação) | 5 | 3 | `select_related('cliente', 'chacara')` + perfil |

### Telas dos apps `ia` e `assistente` (Fases 9 e 10)

Para as telas novas, a coluna "antes" é a implementação direta — chamando
`consumo_do_mes()`, `cota_do_usuario()` etc. por linha, sem `select_related` —
medida com os mesmos dados.

| Tela | Queries antes | Queries depois | O que foi feito |
| --- | :-: | :-: | --- |
| Requisições da IA (20 por página) | 25 (5 + 1 por linha) | 5 | `select_related('usuario')` na lista; totais do filtro num único `aggregate` |
| IA por usuário (18 usuários) | 94 (4 + 5 por usuário) | 4 | uma consulta com `annotate`: consumo do mês (`Sum` com `filter=`), habilitada e cota efetiva (`Coalesce` com o perfil e a cota padrão) + `select_related('cliente', 'administrador')`; configuração lida uma vez (`cached_property`) |
| Meu consumo de IA | 9 | 7 | perfil e configuração lidos uma vez e repassados para `cota_do_usuario`/`usuario_habilitado`/`ia_disponivel` |
| Assistente (histórico com 60 mensagens) | 5 | 5 | as 50 últimas mensagens numa consulta (`order_by` invertido + fatia); a janela enviada à IA é outra consulta com `[:4]` — nada por mensagem (`assistente.tests.ConsultasAssistenteTest`) |

Nenhuma tela do `website` crescia com o volume no momento da medição (as listas
já tinham `select_related` desde o 2º trimestre); o ganho desta fase foi o
custo fixo de **2 consultas a menos em toda página logada**.

## O que foi feito, em detalhe

1. **`website/backends.py` — `BackendComPerfil`**: o usuário da sessão é
   carregado com `select_related('cliente', 'administrador')`. A navbar usa
   `user.cliente` e a regra de admin usa `user.administrador`; agora os dois
   vêm no mesmo SELECT. O `ModelBackend` continua em `AUTHENTICATION_BACKENDS`
   para não derrubar sessões abertas antes da mudança.
2. **`services.usuario_eh_admin` em cache no objeto `user`**: o
   `AdminRequiredMixin`, a view (ex.: Disponibilidade) e a navbar perguntam
   "é admin?" — só a primeira pergunta consulta os grupos.
3. **Context processor `perfil`**: os templates usam `{% if eh_admin %}` em vez
   de repetir `user.is_superuser or user.administrador or user|pertence:...`
   (o filtro `pertence` foi removido).
4. **`select_related` / `prefetch_related`** em todas as listas e detalhes —
   ver a coluna "O que foi feito". Cada `get_queryset` tem um comentário
   dizendo qual consulta por linha ele evita.
