---
name: django-filter-listagens
description: Use sempre que for criar, editar ou revisar filtros de busca em uma listagem deste projeto Django — quando pedirem filtro, busca, pesquisa ou "procurar por" em uma ListView, FilterView ou template de lista — para que toda lista filtrável use o django-filter do mesmo jeito: FilterSet em filters.py, FilterView com ordering, formulário GET reaproveitado com {% include %} e paginação que não perde a busca.
---

## Antes de mexer em qualquer listagem

Confira a base. Se faltar algo, instale primeiro, uma única vez:

1. `django-filter` está no ambiente virtual e no `requirements.txt`, e
   `'django_filters'` (underline, plural) está no `INSTALLED_APPS`.
2. O Crispy Forms com Bootstrap 5 está configurado (`crispy_forms`,
   `crispy_bootstrap5`, `CRISPY_ALLOWED_TEMPLATE_PACKS` e `CRISPY_TEMPLATE_PACK`
   iguais a `'bootstrap5'`) e o template base carrega o Bootstrap Icons 1.11.3.
3. Existe UM `form-filter.html` no app que guarda o template base
   (`<app>/templates/<app>/form-filter.html`) com exatamente este conteúdo:

   ```html
   {% load crispy_forms_tags %}
   <style>
   /* Deixa os campos do filtro lado a lado, em vez de um embaixo do outro */
   form.row div[id*="div_id"] {
       flex: 0 0 auto;
       width: auto;
   }
   </style>
   <h5>Filtros</h5>
   <form class="row gy-2 gx-3 align-items-end pb-3" action="" method="get">
       {{ filter.form|crispy }}
       <div class="col-auto">
           <button type="submit" class="btn btn-outline-primary">
               <i class="bi bi-search"></i> Filtrar
           </button>
           <a href="{{ request.path }}" class="btn btn-outline-secondary">
               <i class="bi bi-x-lg"></i> Limpar
           </a>
       </div>
   </form>
   ```

4. A skill `django-paginacao` está no projeto e o `paginacao.html` existe.
   A paginação das listas segue as regras dela.

## O filtro (filters.py)

1. Os filtros de cada app ficam em `<app>/filters.py`, um `FilterSet` por model,
   chamado `<Model>Filter` (ex.: `ProdutoFilter`).
2. Campos simples vão em `Meta.fields` como DICIONÁRIO, nunca lista simples
   (lista simples usa `exact` e o usuário não acha nada digitando parte do texto):
   - texto (`CharField`, `TextField`, `EmailField`): `['icontains']`
   - número e moeda (`IntegerField`, `DecimalField`...): `['gte', 'lte']`
   - `BooleanField` e campos com `choices`: `['exact']`
3. Chave estrangeira com poucas opções: `django_filters.ModelChoiceFilter` com
   `queryset` e `label`. Com muitas opções (cidades, clientes), prefira buscar
   pelo texto: `django_filters.CharFilter(field_name='<relacao>__nome',
   lookup_expr='icontains', label='... contém')`.
4. Se os registros da relação pertencem a um usuário, o `queryset` do
   `ModelChoiceFilter` é uma função que recebe o `request`
   (`queryset=lambda request: Modelo.objects.filter(usuario=request.user)`),
   para a lista suspensa não mostrar dados de outros usuários.
5. Datas (`DateField` e `DateTimeField`): `django_filters.DateFromToRangeFilter`
   com `widget=django_filters.widgets.RangeWidget(attrs={'type': 'date'})`.
   Se precisar de dois `DateFilter` separados em um `DateTimeField`, use
   `lookup_expr='date__gte'` e `'date__lte'`, nunca `gte`/`lte` puros
   (o `lte` compara com meia-noite e perde os registros do último dia).
6. Todo filtro declarado tem `label` em português, com o nome que o usuário
   entende ("Cadastrado entre", não "cadastrado_em").
7. Filtre só os campos que fazem sentido para quem busca. Não crie filtro para
   `id`, senha, campos de usuário dono do registro nem campos técnicos.

## A view

1. A listagem herda de `django_filters.views.FilterView` no lugar de `ListView`,
   mantendo os mixins de acesso que já existiam (`LoginRequiredMixin`,
   `GroupRequiredMixin`...) ANTES da `FilterView`, na mesma ordem.
2. Atributos obrigatórios: `model`, `template_name` e `filterset_class`, mais
   o `paginate_by` e o `ordering` exigidos pela skill `django-paginacao`.
3. Se a view já tinha `get_queryset` (filtro por usuário, `select_related`),
   ele continua, sempre partindo de `super().get_queryset()`. O filtro do
   django-filter é aplicado por cima do resultado, então quem só vê os próprios
   registros continua só vendo os próprios registros.
4. Se a tabela mostra atributos de relações (`obj.categoria.nome`), use
   `select_related` (ou `prefetch_related` para listas) no `get_queryset`.

## O template da lista

1. Logo abaixo do título da página: `{% include '<app>/form-filter.html' %}`.
2. Logo depois da `</table>`: `{% include '<app>/paginacao.html' %}`, como
   manda a skill `django-paginacao`.
3. Nunca copie o formulário de filtros para dentro de um template de lista.
   Toda mudança nele é feita no `form-filter.html`.
4. A tabela continua percorrendo `object_list`, como em qualquer ListView.
5. Se o projeto também usa a skill `datatables-listagens`, as regras da tabela
   (classes, `data-sort`, lista vazia) são as dela. Esta skill cuida só do
   formulário de filtros, da view e da paginação.

## Conferência antes de terminar

1. Abrir a lista sem parâmetros mostra todos os registros (do usuário, se for o caso).
2. Buscar parte de um texto encontra o registro; buscar por faixa de datas
   inclui os registros do último dia.
3. Com mais registros do que o `paginate_by`, ir para a página 2 mantém os
   parâmetros da busca na URL (é o `paginacao.html` que garante isso).
4. O botão "Limpar" volta para a lista sem nenhum parâmetro.
