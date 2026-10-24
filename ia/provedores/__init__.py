"""Provedores de IA. Cada provedor é um módulo com a função ``gerar``.

Importados sob demanda: o SDK só é carregado quando a IA é usada.
"""
import importlib

MODULOS = {
    'GEMINI': 'ia.provedores.gemini',
}


def obter_provedor(nome):
    return importlib.import_module(MODULOS[nome])
