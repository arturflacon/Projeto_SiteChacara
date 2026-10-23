from django import forms

from .models import ConfiguracaoIA, PerfilIAUsuario


class ConfiguracaoIAForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoIA
        fields = [
            'ativo', 'provedor', 'modelo', 'temperatura',
            'max_tokens_resposta', 'timeout_segundos', 'cota_mensal_padrao_tokens',
        ]
        widgets = {
            'temperatura': forms.NumberInput(attrs={'step': '0.05', 'min': '0', 'max': '2'}),
        }


class PerfilIAUsuarioForm(forms.ModelForm):
    class Meta:
        model = PerfilIAUsuario
        fields = ['habilitado', 'cota_mensal_tokens']
