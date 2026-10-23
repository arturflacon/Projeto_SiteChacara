# AGENTS.md — Sítio de Lurdes (projeto `naes2026`)

Guia para agentes de código (Claude Code, Copilot, Codex…) e para pessoas que
chegam ao projeto. Leia inteiro antes de alterar qualquer coisa.

## 1. O sistema

Site de aluguel de **uma única chácara**, o Sítio de Lurdes.

Fluxo de uma reserva:

1. O visitante cria uma conta (perfil `Cliente`) em **Cadastrar-se**.
2. O cliente envia um **pedido de reserva** com data de chegada e de saída →
   status `PENDENTE`.
3. A administradora **aprova** (`CONFIRMADA`) ou **recusa** (`RECUSADA`).
   Ao aprovar, os outros pedidos pendentes que se sobrepõem ao período são
   recusados automaticamente.
4. Enquanto está `PENDENTE`, o cliente pode editar ou **cancelar** o pedido
   (`CANCELADA` — o registro não é apagado).
5. Só reservas `CONFIRMADA` aparecem na página pública de **Disponibilidade**,
   sem nome de cliente para visitantes.

Regras de negócio que não podem ser quebradas:

- Mínimo de 1 diária: `data_fim > data_inicio`. O cliente não pede datas no passado.
- O dia de saída fica livre para uma nova entrada (intervalos semiabertos:
  conflito quando `inicio_a < fim_b` e `fim_a > inicio_b`).
- Nunca há duas reservas `CONFIRMADA` sobrepostas: a aprovação revalida o
  conflito dentro de `transaction.atomic()` com `select_for_update`.
- `valor_total = preco_diaria × número de diárias` (calculado no `save()`).
- Toda mudança de status gera um `HistoricoReserva`.
- **Avaliação**: só da própria reserva `CONFIRMADA` cuja estadia já terminou
  (`data_fim <= hoje`), uma por reserva. A página da chácara mostra apenas a
  média e a quantidade.
- Dados pessoais de um cliente (nome, telefone, observações) nunca aparecem
  para outro cliente, para visitantes, para a IA ou no bot.

Perfis:

| Perfil | Como é identificado | O que faz |
| --- | --- | --- |
| Visitante | não logado | vê a chácara, a disponibilidade e o Sobre |
| Cliente | `user.cliente` existe | faz pedidos, vê/edita/cancela os seus, avalia, usa o assistente e o bot |
| Admin | superuser, perfil `Administrador` ou grupo `Administradores` (`website.services.usuario_eh_admin`) | decide pedidos, edita reservas e a chácara, gerencia a IA |

## 2. Mapa do projeto

```
naes2026/              settings, urls raiz, wsgi
website/               domínio principal: Chácara, Cliente, Reserva, Avaliação
  services.py          REGRAS DE NEGÓCIO (usadas pelas views e pelo bot)
  analise_pedido.py    análise do pedido pela IA (apoio à administradora)
  filters.py           FilterSets (django-filter)
  templatetags/        url_params (paginação com filtros), sitio_tags (telefone, estrelas)
  templates/website/   modelo.html (base), _paginacao.html, form-filter.html…
ia/                    ÚNICA porta de entrada para a IA
  services.py          chamar_ia, consumo_do_mes, cota_do_usuario, testar_conexao
  provedores/gemini.py único arquivo que importa o SDK google-genai
  models.py            ConfiguracaoIA (singleton), PerfilIAUsuario, RequisicaoIA (auditoria)
assistente/            assistente virtual (/assistente/): histórico, contexto, instruções
  contexto_projeto.md  descrição do site enviada à IA (+ dados atuais em contexto.py)
  instrucoes.py        instruções de sistema (limites do assistente)
  services.py          janela de histórico (JANELA_HISTORICO = 5) e perguntar()
  formatacao.py        Markdown -> HTML sanitizado (nh3); filtro {{ texto|markdown_seguro }}
telegram_bot/          bot do Telegram via webhook (/telegram/webhook/)
  api.py               chamadas HTTP à API do Telegram (requests + timeout)
static/                css/estilo.css (paleta petróleo), js/site.js, js/assistente.js
docs/                  requisitos.md, otimizacoes.md, deploy.md
.claude/skills/        skills dos agentes (ver seção 10)
```

## 3. Comandos (Windows + PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env        # depois preencha os valores no .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver          # http://127.0.0.1:8000 (Debug Toolbar ativo com DEBUG=True)

python manage.py check
python manage.py makemigrations --check
python manage.py test               # suíte completa, sem internet
python manage.py test website.tests.ServicesTest   # uma classe só

python manage.py collectstatic --noinput   # gera static_gcloud/ (deploy)
```

Sem a venv ativada, use `.\.venv\Scripts\python.exe manage.py ...`.

## 4. Convenções

- **Idioma:** código, nomes, mensagens, docstrings e commits em português do Brasil.
- **Views:** somente class-based views. Nada de function-based views.
- **Modelos:** todo campo com `verbose_name` e `help_text`; `Meta` com
  `verbose_name`/`verbose_name_plural`; `__str__` sempre.
- **Templates:** estendem `website/modelo.html`; Bootstrap 5.3 + variáveis de
  `static/css/estilo.css`; formulários com `{{ form|crispy }}`; título
  `{% block title %}<Página> — Sítio de Lurdes{% endblock %}`.
- **Mensagens:** toda Create/Update/Delete usa `SuccessMessageMixin` com texto
  específico; ações (aprovar, recusar, testar conexão) usam `messages.success`
  / `messages.error`. O `modelo.html` mostra tudo como alert abaixo da navbar.
- **Listas:** `FilterView` + `paginate_by` + `ordering`, formulário
  `website/form-filter.html` e paginação `website/_paginacao.html`.
- **jQuery:** plugins carregados no `modelo.html` (cdnjs, versões fixas) e
  inicializados em `static/js/site.js` (máscara, Bootbox, DataTables).
- **Commits:** seguir a skill `mensagens-commit`.

## 5. Arquitetura — onde cada coisa mora

- **Lógica de negócio fica em `website/services.py`.** Views e bot chamam as
  funções de serviço; nenhuma view muda status de reserva diretamente.
  Violação de regra → `ErroRegraNegocio` com mensagem amigável.
- **Toda chamada de IA passa por `ia.services.chamar_ia`.** O SDK
  (`google.genai`) só pode ser importado em `ia/provedores/gemini.py` — um
  teste varre o código e falha se aparecer em outro lugar.
- **Segurança de acesso:** a fronteira é o `get_queryset()` filtrado pelo
  usuário logado (`LoginRequiredMixin`); registro de outro usuário dá **404**.
  Área admin usa `AdminRequiredMixin` (`website/views.py`).
- **Consultas:** listas e detalhes usam `select_related` / `prefetch_related`
  / `annotate`; testes com `assertNumQueries` travam a quantidade de queries
  (ver `docs/otimizacoes.md`).

## 6. Variáveis de ambiente (só nomes)

| Variável | Para quê |
| --- | --- |
| `SECRET_KEY` | chave do Django |
| `DEBUG` | `True` local, `False` em produção |
| `ALLOWED_HOSTS` | hosts aceitos, separados por vírgula |
| `CSRF_TRUSTED_ORIGINS` | origens HTTPS confiáveis, separadas por vírgula |
| `DATABASE_URL` | Postgres (Neon) em produção; vazio = SQLite local |
| `GEMINI_API_KEY` | chave da API do Gemini |
| `TELEGRAM_BOT_TOKEN` | token do bot (BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | segredo conferido no cabeçalho do webhook |
| `TELEGRAM_BOT_USERNAME` | nome do bot sem `@` (link de vinculação) |

Local: arquivo `.env` (carregado pelo `python-dotenv`). Produção:
`env_variables` do `app.yaml`. Modelo: `.env.example`.

## 7. Política de segredos

- **Nunca** escreva chaves, tokens, senhas ou URLs de banco em código,
  templates, testes, documentação, logs ou commits. Tudo vem de `os.environ`.
- Não leia nem imprima o conteúdo de `.env` ou `app.yaml`.
- `.env`, `app.yaml`, `db.sqlite3` e `static_gcloud/` ficam fora do Git.
- Telas mostram apenas se uma chave **está configurada** (sim/não), nunca o valor.
- Exceções do `requests` trazem a URL com o token do Telegram: use
  `telegram_bot.api.sanitizar` antes de logar.
- Antes de commitar, confira `git diff --cached` procurando segredos.

## 8. Testes

- Ficam em `<app>/tests.py` (ou `<app>/tests/`). Toda funcionalidade nova ganha teste.
- **Nenhum teste acessa a internet.** IA: mock de `ia.provedores.gemini.gerar`.
  Telegram: mock de `telegram_bot.api._post` (ou das funções de `api.py`).
- Nos testes a `GEMINI_API_KEY` é zerada pelo settings; use
  `@override_settings(GEMINI_API_KEY='chave-de-teste')` quando precisar da IA "ligada".
- Acesso por dono: sempre teste que outro usuário recebe 404.
- Rode `python manage.py check`, `makemigrations --check` e `test` antes de commitar.

## 9. Deploy (resumo)

Google App Engine Standard + Postgres no Neon. Passo a passo completo em
`docs/deploy.md` e na skill `deploy-app-engine`. Em resumo: variáveis no
`env_variables` do `app.yaml` (`DEBUG=False`), `collectstatic`, `migrate`
apontando para o Neon, `gcloud app deploy`, `configurar_webhook` do Telegram
e smoke test. **Agentes não executam nada contra produção** — só deixam os
comandos prontos.

## 10. Skills disponíveis (`.claude/skills/`)

| Skill | Quando usar |
| --- | --- |
| `mensagens-commit` | ao escrever qualquer mensagem de commit |
| `django-crud-dono` | ao criar CRUD de registros que pertencem ao usuário logado |
| `django-filter-listagens` | ao criar/editar filtros de uma listagem |
| `django-paginacao` | ao criar/editar qualquer listagem paginada |
| `datatables-listagens` | ao criar uma tabela **sem** paginação no servidor |
| `integracao-ia` | ao usar IA em qualquer parte do sistema |
| `deploy-app-engine` | ao preparar ou revisar um deploy |
