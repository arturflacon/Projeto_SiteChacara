# Deploy — Google App Engine + Neon

Passo a passo para publicar esta versão em
<https://naes2026-500619.rj.r.appspot.com>. Todos os comandos são para
**PowerShell**, na raiz do projeto, com a venv ativada
(`.\.venv\Scripts\Activate.ps1`). Siga na ordem.

> Os valores secretos (chaves, tokens, senhas, URL do banco) **nunca** entram
> em arquivo versionado, commit, print ou chat. Eles ficam só no `app.yaml`
> (fora do Git) e, quando um comando local precisa deles, são digitados com
> `Read-Host -MaskInput` e apagados da sessão logo depois.

## 0. Antes de começar

- `gcloud auth login` feito e projeto selecionado (`gcloud config get-value project`).
- **Troque as credenciais que já estiveram no Git.** O histórico do
  `requirements.txt` teve comentários com credenciais (removidas no PR #1, mas
  ainda visíveis nos commits antigos). Gere uma **nova senha no Neon** (e use a
  nova `DATABASE_URL`) e uma **nova `SECRET_KEY`**:

  ```powershell
  python -c "import secrets; print(secrets.token_urlsafe(50))"
  ```

  Trocar a `SECRET_KEY` desconecta quem estiver logado; é só entrar de novo.

## 1. Bot do Telegram (uma vez)

1. No Telegram, fale com o **@BotFather** → `/newbot` → anote o **token** e o
   **nome do bot** (sem o `@`).
2. Gere o segredo do webhook (só letras, números, `_` e `-`):

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

## 2. `app.yaml` → `env_variables`

Acrescente/ajuste estas variáveis (os valores reais só no arquivo):

```yaml
env_variables:
  SECRET_KEY: "<nova chave>"
  DEBUG: "False"
  ALLOWED_HOSTS: "naes2026-500619.rj.r.appspot.com"
  CSRF_TRUSTED_ORIGINS: "https://naes2026-500619.rj.r.appspot.com"
  DATABASE_URL: "<URL do Neon com a senha nova>"
  GEMINI_API_KEY: "<chave do Google AI Studio>"
  TELEGRAM_BOT_TOKEN: "<token do BotFather>"
  TELEGRAM_WEBHOOK_SECRET: "<segredo gerado no passo 1>"
  TELEGRAM_BOT_USERNAME: "<nome do bot sem @>"
```

- Confira que os `handlers` usam `secure: always` e servem `/static` a partir
  de `static_gcloud/`.
- `GEMINI_MODEL` não é mais lido: o modelo agora fica em **Admin → IA →
  Configuração** (padrão `gemini-3.5-flash-lite`). Pode remover a variável.
- Se a produção usa o Gemini pela identidade do App Engine (Vertex AI), mantenha
  `GEMINI_USAR_VERTEX: "True"`, `GOOGLE_CLOUD_PROJECT` e `GOOGLE_CLOUD_LOCATION`
  em vez da `GEMINI_API_KEY`.
- Opcional: `SECURE_HSTS_SECONDS` (padrão 3600 = 1 hora). Depois de alguns dias
  sem problemas com HTTPS, dá para subir para `31536000` (1 ano).

## 3. Dependências e conferência local

```powershell
pip install -r requirements.txt
python manage.py test
python manage.py makemigrations --check
$env:DEBUG = 'False'; python manage.py check --deploy; Remove-Item Env:DEBUG
```

Os três devem terminar sem erro (o `check --deploy` mostra "2 silenced": são
os avisos de HSTS `includeSubDomains`/`preload`, desligados de propósito).

## 4. Banco (Neon)

1. **Backup**: no painel do Neon, crie um *branch* do banco de produção
   (ex.: `antes-3-trimestre`). Se algo der errado, dá para voltar a ele.
2. Rode as migrations apontando para o Neon só nesta sessão do terminal:

   ```powershell
   $env:DATABASE_URL = Read-Host -Prompt 'Cole a DATABASE_URL do Neon' -MaskInput
   python manage.py migrate
   python manage.py showmigrations website ia assistente telegram_bot
   Remove-Item Env:DATABASE_URL
   ```

   Serão aplicadas: `website.0008_avaliacao`, `ia.0001_initial`,
   `ia.0002_copiar_uso_ia` (copia os registros do antigo **Uso da IA** para
   **Requisições da IA**), `website.0009_remove_usoia` (apaga a tabela antiga),
   `assistente.0001_initial` e `telegram_bot.0001_initial`.

## 5. Arquivos estáticos

```powershell
python manage.py collectstatic --noinput
```

Gera `static_gcloud/` (fora do Git, mas enviado no deploy — o `.gcloudignore`
não o ignora).

## 6. Deploy

```powershell
gcloud app deploy
gcloud app logs tail -s default   # acompanhe a primeira subida; Ctrl+C para sair
```

## 7. Webhook do Telegram

Com o site já no ar, registre o webhook. O comando precisa do token e do
segredo (os mesmos do `app.yaml`) só nesta sessão:

```powershell
$env:TELEGRAM_BOT_TOKEN = Read-Host -Prompt 'Token do bot' -MaskInput
$env:TELEGRAM_WEBHOOK_SECRET = Read-Host -Prompt 'Segredo do webhook' -MaskInput
python manage.py configurar_webhook --url https://naes2026-500619.rj.r.appspot.com/telegram/webhook/
python manage.py info_webhook
Remove-Item Env:TELEGRAM_BOT_TOKEN, Env:TELEGRAM_WEBHOOK_SECRET
```

O `info_webhook` deve mostrar a URL acima, os tipos `message, callback_query`
e "Nenhum erro de entrega registrado" (depois que alguém mandar uma mensagem).
Se aparecer `403 Forbidden`, o segredo do `app.yaml` e o usado aqui são diferentes.

## 8. Depois do deploy

1. Entre como admin → **Admin → Configuração da IA**: "Chave configurada:
   **Sim**" → **Testar conexão** deve mostrar "Conexão OK". Ajuste o modelo e a
   cota padrão se quiser.
2. **Admin → IA por Usuário**: confira os consumos; bloqueie ou dê cota própria
   a quem precisar.
3. Teste o bot: no Telegram, `/ajuda`, `/chacara`. No site, menu do usuário →
   **Conectar Telegram** → **Gerar código** → **Abrir no Telegram**; depois
   `/minhasreservas`. Com o admin vinculado, `/pendentes`.

### Smoke test

- [ ] `/`, `/chacara/`, `/disponibilidade/`, `/sobre/` abrem com o visual certo.
- [ ] Cadastro: o telefone recebe a máscara `(00) 00000-0000`.
- [ ] Cliente: Fazer pedido → aparece em **Minhas Reservas** com mensagem verde.
- [ ] Admin: **Pedidos Pendentes** → Aprovar abre a confirmação (Bootbox) → aprova.
- [ ] Cliente: **Assistente** responde; **Meu consumo de IA** mostra os tokens.
- [ ] Admin: **Requisições da IA** lista as chamadas; **IA por Usuário** com busca (DataTables).
- [ ] `/admin/` abre com CSS.
- [ ] `gcloud app logs tail -s default` sem erros novos.

## Se algo der errado

| Sintoma | Causa provável |
| --- | --- |
| 400 Bad Request | domínio fora do `ALLOWED_HOSTS` |
| 403 ao enviar formulário (CSRF) | `CSRF_TRUSTED_ORIGINS` sem `https://` + domínio |
| Página sem CSS | `collectstatic` não rodou antes do deploy |
| 500 em tela nova (IA, Avaliações, Telegram) | migrations não aplicadas no Neon (passo 4) |
| Laço de redirecionamento | o cabeçalho `X-Forwarded-Proto` não está chegando ao Django; confira o `secure: always` dos handlers |
| Assistente "indisponível" | `GEMINI_API_KEY` ausente ou IA desativada em Configuração |
| Bot não responde | `info_webhook` mostra o erro; confira token, segredo e a URL |

Voltar para a versão anterior sem novo deploy:

```powershell
gcloud app versions list
gcloud app services set-traffic default --splits <versão-anterior>=1
```

(As migrations já aplicadas continuam no banco; se precisar desfazê-las, use o
*branch* de backup do Neon criado no passo 4.)
