---
name: mensagens-commit
description: Use sempre que for escrever uma mensagem de commit neste projeto — o padrão é Conventional Commits em português do Brasil, com tipos e escopos fixos, resumo no imperativo de até 72 caracteres e nenhum segredo.
---

## Formato

```
<tipo>(<escopo>): <resumo no imperativo>

<corpo opcional: o PORQUÊ da mudança, quebrado em ~72 colunas>

<rodapé opcional: BREAKING CHANGE: ..., Refs #12, Co-Authored-By: ...>
```

### Regras do assunto (primeira linha)

1. Até **72 caracteres** no total, contando tipo e escopo.
2. Resumo no **imperativo**, em português: "adiciona", "corrige", "remove",
   "extrai" — como quem completa a frase "este commit…". Nunca no passado
   ("adicionado", "corrigi") nem no gerúndio ("adicionando").
3. Começa com letra minúscula e **não termina com ponto**.
4. Diz **o que muda para quem usa ou mantém o sistema**, não o nome do arquivo.

### Tipos

| Tipo | Quando |
| --- | --- |
| `feat` | funcionalidade nova para o usuário (tela, comando do bot, campo) |
| `fix` | correção de bug ou de comportamento errado |
| `refactor` | muda a estrutura sem mudar o comportamento |
| `docs` | só documentação (README, AGENTS.md, docs/, docstrings) |
| `test` | só testes |
| `style` | formatação/visual sem mudar regra (CSS, indentação, títulos) |
| `perf` | desempenho (queries, `select_related`, cache) |
| `build` | dependências e empacotamento (`requirements.txt`) |
| `chore` | manutenção que não entra em nenhum outro (`.gitignore`, limpeza) |

### Escopos

`website`, `ia`, `assistente`, `bot`, `deploy`, `docs`, `agentes`.
O escopo é opcional quando a mudança é transversal (ex.: `chore: ...`).

### Corpo e rodapé

- O corpo é opcional. Use quando o porquê não é óbvio: qual problema existia,
  por que esta solução e não outra, efeitos colaterais.
- Uma linha em branco separa assunto, corpo e rodapé.
- Mudança que quebra compatibilidade (URL removida, campo renomeado, comando
  com outro nome) leva `BREAKING CHANGE: <o que quebrou e como migrar>` no rodapé.

## Regras de conteúdo

1. **Um assunto lógico por commit.** Se o resumo precisa de "e" ligando duas
   coisas sem relação, são dois commits (`git add -p` ajuda a separar).
2. Migration vai no mesmo commit do model que a gerou.
3. Testes da funcionalidade podem ir no mesmo commit dela (`feat`); commits só
   de teste usam `test`.
4. **Nunca** coloque segredos na mensagem nem no diff: chaves, tokens, senhas,
   URLs de banco, conteúdo de `.env` ou `app.yaml`. Antes de commitar:
   `git diff --cached` e procure por `KEY`, `TOKEN`, `SECRET`, `postgres://`.
5. Não commite `db.sqlite3`, `__pycache__/`, `.env`, `app.yaml` nem `static_gcloud/`.

## Exemplos deste projeto

Bons:

```
feat(website): adiciona avaliação de reservas concluídas
fix(website): bloqueia aprovação de pedido que conflita com confirmada
refactor(website): move aprovação e recusa para services.py
perf(website): evita N+1 na lista de todas as reservas
feat(bot): aprova e recusa pedidos por botões inline
feat(ia): registra auditoria de toda chamada ao Gemini
test(website): usa datas relativas nos testes de valor limite
docs(agentes): cria AGENTS.md e skills do projeto
build: fixa nh3 e markdown no requirements.txt
```

Com corpo e rodapé:

```
refactor(ia): substitui UsoIA por RequisicaoIA

A auditoria agora guarda prompt, resposta, duração e erro de toda chamada,
e não só os tokens. A migration copia os registros antigos.

BREAKING CHANGE: a tela /ia/uso/ foi substituída por /ia/requisicoes/.
```

Ruins (e por quê):

| Mensagem | Problema |
| --- | --- |
| `feaT: 3 trimestre` | tipo com maiúscula, resumo não diz o que mudou |
| `feat: implementações todas commitadas para o 2 trimenste` | vários assuntos num commit, sem escopo, erro de digitação |
| `fix: corrigido bug` | particípio, não diz qual bug |
| `feat(website): Adiciona filtros.` | maiúscula no início e ponto final |
| `update views.py` | sem tipo, fala do arquivo e não da mudança |
| `feat(bot): adiciona token 123456:ABC... no settings` | segredo na mensagem (e provavelmente no código) |
| `feat(website): adiciona avaliações, corrige paginação e atualiza o README` | três assuntos: separe em `feat`, `fix` e `docs` |

## Passo a passo

1. `git status` e `git diff` — entenda tudo o que vai entrar.
2. Separe por assunto (`git add <arquivos>` ou `git add -p`).
3. `git diff --cached` — confira que não há segredo nem arquivo proibido.
4. Escolha tipo e escopo pelas tabelas acima.
5. Escreva o resumo no imperativo, conte os caracteres (≤ 72).
6. Se o porquê não for óbvio, escreva o corpo.
7. Commite. **Não faça `push`** sem pedido explícito.
