import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Chacara, Cliente, Reserva


def limpar_telefone(valor):
    """Remove a máscara "(00) 00000-0000" e guarda só os dígitos (DDD + número)."""
    digitos = re.sub(r'\D', '', valor or '')
    if len(digitos) not in (10, 11):
        raise forms.ValidationError('Informe o telefone com DDD: 10 ou 11 dígitos.')
    return digitos


class TelefoneField(forms.CharField):
    """Campo de formulário com espaço para a máscara (o model guarda 11 dígitos)."""

    def __init__(self, **kwargs):
        kwargs.setdefault('max_length', 15)
        kwargs.setdefault('label', 'Telefone')
        kwargs.setdefault('help_text', 'Com DDD, ex: (46) 99999-8888.')
        super().__init__(**kwargs)

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        # A classe "mascara-telefone" é usada pelo jQuery Mask nos templates.
        attrs.update({'class': 'mascara-telefone', 'inputmode': 'tel', 'placeholder': '(00) 00000-0000'})
        return attrs


class SignupForm(UserCreationForm):
    nome = forms.CharField(
        max_length=255,
        label='Nome Completo',
        help_text='Seu nome completo.',
    )
    telefone = TelefoneField()
    email = forms.EmailField(
        required=True,
        label='E-mail',
        help_text='Informe um e-mail válido.',
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_telefone(self):
        return limpar_telefone(self.cleaned_data.get('telefone'))

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            Cliente.objects.create(
                usuario=user,
                nome=self.cleaned_data['nome'],
                telefone=self.cleaned_data['telefone'],
            )
        return user


class ClienteForm(forms.ModelForm):
    telefone = TelefoneField()

    class Meta:
        model = Cliente
        fields = ['nome', 'telefone']

    def clean_telefone(self):
        return limpar_telefone(self.cleaned_data.get('telefone'))


class ReservaClienteForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['data_inicio', 'data_fim', 'observacoes']
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'data_fim': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        inicio = cleaned.get('data_inicio')
        fim = cleaned.get('data_fim')

        if inicio and inicio < timezone.localdate():
            self.add_error('data_inicio', 'A data de chegada não pode estar no passado.')
            return cleaned

        if inicio and fim:
            if fim < inicio:
                raise forms.ValidationError(
                    {'data_fim': 'A data de saída não pode ser anterior à data de chegada.'}
                )
            if fim == inicio:
                raise forms.ValidationError(
                    {'data_fim': 'A data de saída deve ser posterior à data de chegada (mínimo de 1 diária).'}
                )

            chacara = Chacara.objects.first()
            if chacara:
                conflito = Reserva.objects.filter(
                    chacara=chacara,
                    status=Reserva.STATUS_CONFIRMADA,
                    data_inicio__lt=fim,
                    data_fim__gt=inicio,
                )
                if self.instance.pk:
                    conflito = conflito.exclude(pk=self.instance.pk)
                if conflito.exists():
                    raise forms.ValidationError(
                        'Já existe uma reserva confirmada nesse período. '
                        'Consulte a página de disponibilidade e escolha outras datas.'
                    )

        return cleaned


class ReservaAdminForm(forms.ModelForm):
    """Edição completa da reserva pelo administrador."""

    class Meta:
        model = Reserva
        fields = ['chacara', 'data_inicio', 'data_fim', 'observacoes', 'status']
        widgets = {
            # format ISO: o <input type="date"> só aceita AAAA-MM-DD como valor inicial.
            'data_inicio': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'data_fim': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


class DecisaoReservaForm(forms.Form):
    """Observação opcional registrada no histórico ao aprovar/recusar."""

    observacao = forms.CharField(
        required=False,
        label='Observação da decisão',
        help_text='Opcional. Fica registrada no histórico da reserva.',
        widget=forms.Textarea(attrs={'rows': 3}),
    )
