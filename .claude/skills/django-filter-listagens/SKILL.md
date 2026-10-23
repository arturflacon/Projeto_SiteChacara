---
name: django-filter-listagens
description: Use sempre que for criar, editar ou revisar filtros de busca em uma listagem deste projeto Django — quando pedirem filtro, busca, pesquisa ou "procurar por" em uma ListView, FilterView ou template de lista — para que toda lista filtrável use o django-filter do mesmo jeito: FilterSet em filters.py, FilterView com ordering, formulário GET reaproveitado com {% include %} e paginação que não perde a busca.
---

## A base (já existe — confira, não recrie)

1. `django-filter` no `requirements.txt` e `'django_filters'` no `INSTALLED_APPS`.
2. Crispy Forms com Bootstrap 5 (`CRISPY_TEMPLATE_PACK = 'bootstrap5'`) e
   Bootstrap Icons no `website/modelo.html`.
3. `website/templates/website/form-filter.html`: o ÚNICO formulário de
   filtros (método GET, `{{ filter.form|crispy }}`, botões **Filtrar** e
   **Limpar** — o Limpar volta para `{{ request.path }}` sem parâmetros).
4. Paginação: skill `django-paginacao` (`_paginacao.html` + `url_com_parametros`).

## O filtro (`<app>/filters.py`)

1. Um `FilterSet` por lista, chamado `<Coisa>Filter`
   (ex.: `MinhasReservasFilter`, `ReservaAdminFilter`, `RequisicaoIAFilter`).
2. Todo filtro declarado tem `label` em português ("Chegada a partir de",
   não "data_inicio__gte").
3. Lookups:
   - texto: `CharFilter(lookup_expr='icontains')`
   - campos com `choices` e booleanos: `ChoiceFilter`/`BooleanFilter` com
     `lookup_expr='exact'` e `empty_label='Todos'`
   - números: `gte` / `lte`
   - `DateField`: dois `DateFilter` (`gte`/`lte`) ou `DateFromToRangeFilter`,
     com `widget=forms.DateInput(attrs={'type': 'date'})` /
     `RangeWidget(attrs={'type': 'date'})`
   - `DateTimeField`: `lookup_expr='date__gte'` e `'date__lte'` — nunca
     `gte`/`lte` puros (o `lte` compara com meia-noite e perde o último dia).
4. FK com poucas opções: `ModelChoiceFilter(queryset=..., label=...)`. Com
   muitas (clientes), busque pelo texto:
   `CharFilter(field_name='cliente__nome', lookup_expr='icontains')`.
5. Se a relação pertence ao usuário, o `queryset` é uma função do request:
   `queryset=lambda request: Modelo.objects.filter(usuario=request.user)`.
6. Página pública **nunca** filtra por dado pessoal (ex.: Disponibilidade não
   tem filtro por cliente). Não crie filtro para `id`, senha, dono do
   registro ou campos técnicos.

## A view

1. Herda de `django_filters.views.FilterView`, com os mixins de acesso
   (`LoginRequiredMixin`, `AdminRequiredMixin`) ANTES, na mesma ordem de sempre.
2. Atributos: `model`, `template_name`, `filterset_class`, `paginate_by`, `ordering`.
3. O `get_queryset` parte de `super().get_queryset()` e restringe ao dono
   quando for o caso — o django-filter aplica o filtro POR CIMA, então quem
   só vê os próprios registros continua só vendo os próprios.
4. `select_related`/`prefetch_related` para o que a tabela mostra.

## O template

1. Logo abaixo do título: `{% include 'website/form-filter.html' %}`
   (pode ficar dentro de um `card`).
2. Depois da tabela: `{% include 'website/_paginacao.html' %}`.
3. Sem resultados: diferencie "nenhum registro" de "nenhum resultado com
   esses filtros" com `{% elif filter.is_bound %}`.
4. Nunca copie o formulário de filtros para dentro do template da lista.

## Testes mínimos

- Abrir sem parâmetros mostra todos (do usuário, se for o caso).
- Cada filtro realmente filtra (`icontains` acha parte do texto; faixa de
  datas inclui os dois limites).
- O cliente filtrando nunca vê registro de outro cliente.
- A página 2 mantém os parâmetros da busca (skill `django-paginacao`).
- O Limpar volta para a lista sem parâmetros.
