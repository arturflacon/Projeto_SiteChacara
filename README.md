# Sítio de Lurdes

Sistema web de aluguel de **uma única chácara**, feito em Django (projeto
`naes2026`). O cliente se cadastra e faz um **pedido de reserva**; a
administradora **aprova** ou **recusa**; só as reservas confirmadas aparecem
na página pública de disponibilidade. O site tem ainda avaliações das
estadias, um **assistente virtual com IA** (Google Gemini) e um **bot do
Telegram**.

**Em produção:** <https://naes2026-500619.rj.r.appspot.com>
(Google App Engine Standard + PostgreSQL no Neon)

## Funcionalidades

| Área | O que tem |
| --- | --- |
| Público | início, a chácara (com média das avaliações), disponibilidade (calendário + lista, sem nomes), sobre, cadastro e login |
| Cliente | fazer pedido; Minhas Reservas com filtros e paginação; editar/cancelar pedido pendente; avaliar estadias concluídas (Minhas Avaliações); Meus dados; assistente virtual; Meu consumo de IA; Conectar Telegram |
| Administração | Pedidos Pendentes (aprovar/recusar com confirmação); Todas as Reservas com filtros; editar/excluir reserva; histórico de status; análise do pedido pela IA; editar a chácara; cadastrar administrador |
| IA (admin) | Requisições (auditoria de toda chamada, com filtros); Configuração (modelo, temperatura, limites, cota padrão, ativar/desativar e **Testar conexão**); IA por usuário (habilitar e definir cota) |
| Telegram | vínculo da conta por código de uso único; `/chacara`, `/disponibilidade`, `/minhasreservas` (cancelar pelo botão), `/perguntar`, `/pendentes` (admin aprova/recusa pelo botão); log de mensagens e limites por remetente |

Regras principais: mínimo de 1 diária, sem datas no passado, nunca duas
reservas confirmadas sobrepostas (a aprovação revalida com
`select_for_update`), o dia de saída fica livre para nova entrada, valor =
diária × diárias.

## Perfis de usuário

| Perfil | Como se obtém | Acesso |
| --- | --- | --- |
| Visitante | — | páginas públicas |
| Cliente | **Cadastrar-se** no site | tudo do visitante + área do cliente |
| Administrador | superusuário, perfil `Administrador` (menu Admin → Novo Administrador) ou grupo `Administradores` | tudo + menu **Admin** |

## Como rodar localmente (Windows + PowerShell)

Pré-requisito: Python 3.11+.

```powershell
git clone <url-do-repositório>
cd Projeto_SiteChacara
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env   # preencha os valores (veja a tabela abaixo)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver    # http://127.0.0.1:8000
```

Sem `DATABASE_URL` no `.env`, o projeto usa SQLite (`db.sqlite3`, fora do
Git). Com `DEBUG=True` o **Django Debug Toolbar** aparece na lateral das
páginas. Sem `GEMINI_API_KEY`, o site funciona normalmente e o assistente
fica "indisponível".

### Testes

```powershell
python manage.py test        # suíte completa (≈ 225 testes, poucos segundos)
python manage.py check
python manage.py makemigrations --check
```

Nenhum teste acessa a internet: a IA e a API do Telegram são sempre mockadas.

## Variáveis de ambiente

Local: arquivo `.env` (modelo em `.env.example`). Produção: `env_variables`
do `app.yaml`. **Nunca** coloque os valores no código ou no Git.

| Variável | Para quê |
| --- | --- |
| `SECRET_KEY` | chave do Django |
| `DEBUG` | `True` local, `False` em produção |
| `ALLOWED_HOSTS` | domínios aceitos, separados por vírgula |
| `CSRF_TRUSTED_ORIGINS` | origens HTTPS confiáveis (ex.: `https://<domínio>`) |
| `DATABASE_URL` | PostgreSQL (Neon); vazio = SQLite |
| `GEMINI_API_KEY` | chave da API do Gemini |
| `TELEGRAM_BOT_TOKEN` | token do bot (BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | segredo conferido em cada chamada do webhook |
| `TELEGRAM_BOT_USERNAME` | nome do bot sem `@` |

Opcionais: `SECURE_HSTS_SECONDS`, `GEMINI_USAR_VERTEX`,
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`.

## Estrutura

| Pasta | Conteúdo |
| --- | --- |
| `naes2026/` | settings e URLs do projeto |
| `website/` | chácara, clientes, reservas, avaliações; regras de negócio em `services.py` |
| `ia/` | porta única para a IA (`chamar_ia`), auditoria, cotas e telas de administração |
| `assistente/` | assistente virtual (histórico, contexto do site, instruções, Markdown sanitizado) |
| `telegram_bot/` | webhook, comandos, vínculo de conta e log do bot |
| `static/` | `css/estilo.css` (paleta petróleo), `js/site.js` (plugins jQuery), `js/assistente.js` |
| `docs/` | [requisitos](docs/requisitos.md), [otimizações](docs/otimizacoes.md) e [deploy](docs/deploy.md) |

Para quem vai mexer no código (pessoas ou agentes de IA): leia o
[AGENTS.md](AGENTS.md) e as skills em `.claude/skills/`.

## Tecnologias

Django 5.2 · Bootstrap 5.3 · django-crispy-forms · django-filter ·
django-debug-toolbar · jQuery (Mask Plugin, Bootbox.js, DataTables) ·
FullCalendar · Google Gemini (`google-genai`) · Markdown + nh3 · API de bots
do Telegram · PostgreSQL (Neon) · Google App Engine.
