---
name: deploy-app-engine
description: Use ao preparar, revisar ou documentar um deploy do Sítio de Lurdes no Google App Engine Standard com Postgres no Neon — checklist de variáveis, DEBUG=False, collectstatic, migrate, gcloud app deploy, webhook do Telegram e smoke test.
---

> Agentes **não executam** nada contra produção (migrate no Neon,
> `gcloud app deploy`, `setWebhook`). Prepare os comandos e entregue à pessoa
> responsável. O passo a passo detalhado está em `docs/deploy.md`.

## Checklist

### 1. Antes de tudo (local)

- [ ] Branch atualizada, `python manage.py test` verde.
- [ ] `python manage.py makemigrations --check` sem mudanças pendentes.
- [ ] `requirements.txt` com todas as dependências fixadas (`pacote==versão`).
- [ ] Nenhum segredo no diff: `git diff master...HEAD` sem chaves/tokens/URLs de banco.
- [ ] `$env:DEBUG='False'; python manage.py check --deploy` sem avisos relevantes.

### 2. `app.yaml` (fora do Git — só a pessoa responsável edita)

`env_variables` precisa ter (os valores ficam só no arquivo):

`SECRET_KEY`, `DEBUG` (`False`), `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`DATABASE_URL`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_BOT_USERNAME`.

- `ALLOWED_HOSTS` com o domínio `*.appspot.com` do projeto.
- `CSRF_TRUSTED_ORIGINS` com `https://` + o mesmo domínio.
- `handlers` servindo `/static` a partir de `static_gcloud/`, com `secure: always`.

### 3. Estáticos

```powershell
python manage.py collectstatic --noinput   # gera static_gcloud/
```

O `.gcloudignore` **não** pode ignorar `static_gcloud/` nem `app.yaml`.

### 4. Banco (Neon)

Rodado da máquina local, apontando para o Neon só nesta sessão do terminal:

```powershell
$env:DATABASE_URL = Read-Host -Prompt 'Cole a DATABASE_URL do Neon' -MaskInput
python manage.py migrate
python manage.py showmigrations ia assistente telegram_bot website
Remove-Item Env:DATABASE_URL
```

### 5. Deploy

```powershell
gcloud app deploy
gcloud app logs tail -s default     # acompanhe erros na primeira subida
```

### 6. Telegram

```powershell
$env:TELEGRAM_BOT_TOKEN = Read-Host -Prompt 'Token do bot' -MaskInput
$env:TELEGRAM_WEBHOOK_SECRET = Read-Host -Prompt 'Segredo do webhook' -MaskInput
python manage.py configurar_webhook --url https://<projeto>.appspot.com/telegram/webhook/
python manage.py info_webhook       # confira url, pending_update_count e last_error_message
Remove-Item Env:TELEGRAM_BOT_TOKEN, Env:TELEGRAM_WEBHOOK_SECRET
```

### 7. Smoke test (no navegador, em produção)

- [ ] `/` , `/chacara/`, `/disponibilidade/`, `/sobre/` abrem sem erro e com CSS.
- [ ] Login de cliente → `/reservas/minhas/`, `/avaliacoes/`, `/assistente/`.
- [ ] Login de admin → Pedidos Pendentes, Todas as Reservas, IA → Configuração
      (chave configurada = Sim) → **Testar conexão**.
- [ ] Bot: `/ajuda` responde; `/chacara` mostra a diária atual.
- [ ] `/admin/` abre com CSS.
- [ ] Nenhum erro novo em `gcloud app logs tail`.

### Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| 400 Bad Request | domínio fora do `ALLOWED_HOSTS` |
| 403 CSRF ao enviar formulário | `CSRF_TRUSTED_ORIGINS` sem o `https://` do domínio |
| Página sem CSS | `collectstatic` não rodou ou `static_gcloud/` ignorado no deploy |
| Webhook com `last_error_message` 403 | `TELEGRAM_WEBHOOK_SECRET` diferente entre `app.yaml` e o `configurar_webhook` |
| 500 em tela nova | migration não aplicada no Neon |
