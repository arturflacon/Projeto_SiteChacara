---
name: django-crud-dono
description: Use ao criar ou revisar um CRUD de registros que pertencem ao usuário logado (lista, detalhe, criação, edição e exclusão só do dono) — receita com model com FK usuario, CBVs com get_queryset filtrado, SuccessMessageMixin, FilterSet com paginação e testes de 404 para outro usuário.
---

O exemplo de referência no projeto é `Avaliacao` (`website/models.py`,
`website/views.py`, URLs `/avaliacoes/...`).

## 1. Model

```python
class Avaliacao(models.Model):
    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='avaliacoes',
        verbose_name='Usuário', help_text='Quem cadastrou (preenchido automaticamente).',
    )
    # ... demais campos, todos com verbose_name e help_text
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name='Criado em', help_text='...')
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name='Atualizado em', help_text='...')

    class Meta:
        verbose_name = 'Avaliação'
        verbose_name_plural = 'Avaliações'
        ordering = ['-criado_em']

    def __str__(self):
        return f'...'
```

- O campo `usuario` **nunca** vai para o `fields` do formulário.
- Registre no admin com `list_select_related` para as FKs exibidas.
- Gere a migration no mesmo commit.

## 2. Views (todas CBV, todas com `LoginRequiredMixin`)

```python
class DonoMixin(LoginRequiredMixin):
    """Fronteira de segurança: só registros do usuário logado."""

    def get_queryset(self):
        return Avaliacao.objects.filter(usuario=self.request.user).select_related('reserva')


class MinhasAvaliacoesList(DonoMixin, ListView):
    paginate_by = 10
    ordering = ['-criado_em']          # ou FilterView + filterset_class


class AvaliacaoDetail(DonoMixin, DetailView): ...


class AvaliacaoCreate(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    success_message = 'Avaliação enviada. Obrigado!'

    def form_valid(self, form):
        form.instance.usuario = self.request.user   # ANTES do super()
        return super().form_valid(form)


class AvaliacaoUpdate(DonoMixin, SuccessMessageMixin, UpdateView):
    success_message = 'Avaliação atualizada.'


class AvaliacaoDelete(DonoMixin, SuccessMessageMixin, DeleteView):
    success_message = 'Avaliação excluída.'
```

Regras:

1. `get_queryset()` filtrado pelo dono em **detalhe, edição e exclusão** — é
   isso que faz o registro alheio responder **404** (e não 403, que confirmaria
   que o registro existe).
2. Nunca confie em `usuario` vindo do POST; atribua `self.request.user` no
   `form_valid`.
3. Se o formulário tem um `ModelChoiceField` para outro registro do usuário
   (ex.: a reserva avaliada), restrinja o `queryset` no `__init__` do form
   (receba `usuario` via `get_form_kwargs`) **e** valide de novo no `clean()`.
4. Toda Create/Update/Delete tem `SuccessMessageMixin` com mensagem específica.
5. Regras de negócio (quem pode avaliar o quê) ficam em `website/services.py`.

## 3. Lista com filtro e paginação

- `FilterSet` em `website/filters.py` (skill `django-filter-listagens`).
- `FilterView` com `paginate_by` e `ordering`; o `get_queryset` parte de
  `super().get_queryset()` e filtra pelo dono — o filtro roda **por cima** dele.
- Template: `{% include 'website/form-filter.html' %}` e
  `{% include 'website/_paginacao.html' %}` (skill `django-paginacao`).
- O `ModelChoiceFilter` de uma relação do usuário usa
  `queryset=lambda request: Modelo.objects.filter(usuario=request.user)`.

## 4. Templates

- Estendem `website/modelo.html`, título `"<Página> — Sítio de Lurdes"`.
- Formulário com `{{ form|crispy }}`.
- Exclusão: `<form method="post" data-confirmar="Deseja excluir ...?">` (Bootbox).
- Links de navegação para a lista no menu do usuário (`modelo.html`).

## 5. Testes obrigatórios

```python
def test_outro_usuario_recebe_404(self):
    for nome in ('avaliacao_detail', 'avaliacao_update', 'avaliacao_delete'):
        with self.subTest(nome):
            r = self.intruso.get(reverse(nome, args=[self.avaliacao.pk]))
            self.assertEqual(r.status_code, 404)

def test_post_de_outro_usuario_nao_altera(self):
    self.intruso.post(reverse('avaliacao_delete', args=[self.avaliacao.pk]))
    self.assertTrue(Avaliacao.objects.filter(pk=self.avaliacao.pk).exists())

def test_lista_mostra_so_as_do_dono(self): ...
def test_create_preenche_usuario_logado(self): ...
def test_nao_aceita_registro_relacionado_de_outro_usuario(self): ...
def test_anonimo_vai_para_o_login(self): ...
def test_mensagem_de_sucesso(self):  # get_messages(response.wsgi_request)
```
