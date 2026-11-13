"""Gera entrega/submissao.txt com o código do projeto e o ``git log --oneline``.

O pacote junta, com um cabeçalho de caminho em cada arquivo, tudo o que a
avaliação precisa ver: .py, templates .html, .js e .css próprios, AGENTS.md,
CLAUDE.md, skills (.claude/skills/*/SKILL.md), app.yaml.example,
requirements.txt, .env.example, arquivos de ignore e docs/. No fim vai a
saída de ``git log --oneline``.

Segurança:
- a lista de arquivos vem do ``git ls-files`` (só o que está versionado), então
  .env, app.yaml, db.sqlite3, .venv/ e static_gcloud/ nunca entram; mesmo
  assim há uma lista de bloqueio explícita, por garantia;
- antes de gravar, o conteúdo é varrido atrás de segredos (URL de banco com
  senha, chaves do Google, token do Telegram...). Se achar algo, o script para
  sem gerar o arquivo e diz só ONDE está, nunca o valor.

Uso (na raiz do projeto, só biblioteca padrão — não precisa da venv):

    python scripts/gerar_entrega.py                 # sem migrations automáticas
    python scripts/gerar_entrega.py --com-migrations
    python scripts/gerar_entrega.py --saida outra/pasta/submissao.txt

Migrations: por padrão entram só as escritas à mão (com RunPython/RunSQL,
ex.: ia/migrations/0002_copiar_uso_ia.py); as geradas pelo makemigrations
ficam de fora, a não ser com --com-migrations.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / 'entrega' / 'submissao.txt'

EXTENSOES = {'.py', '.html', '.js', '.css', '.md', '.txt', '.example'}
NOMES_EXTRAS = {'.gitignore', '.gcloudignore'}

# Nunca entram, mesmo que um dia sejam versionados por engano.
BLOQUEADOS_NOMES = {'.env', 'app.yaml', 'db.sqlite3'}
BLOQUEADOS_PASTAS = {'.venv', 'venv', 'static_gcloud', 'staticfiles', 'entrega',
                     '__pycache__', 'node_modules', '.git'}

# Ordem no pacote: primeiro o que explica o projeto, depois o código por pasta.
PRIMEIROS = [
    'AGENTS.md', 'CLAUDE.md', 'README.md', 'requirements.txt', 'app.yaml.example',
    '.env.example', '.gitignore', '.gcloudignore', '.github/copilot-instructions.md',
]

PADROES_SEGREDO = {
    'URL de banco com senha': re.compile(r'postgres(?:ql)?://[^\s<>@"\'/:]+:[^\s<>@"\']+@'),
    'chave de API do Google': re.compile(r'AIza[0-9A-Za-z_\-]{30,}'),
    'token de bot do Telegram': re.compile(r'\b\d{8,10}:AA[0-9A-Za-z_\-]{30,}'),
    'senha do Neon': re.compile(r'\bnpg_[A-Za-z0-9]{8,}'),
    'SECRET_KEY do Django': re.compile(r'django-insecure-[^\s\'"]{10,}'),
    'chave privada': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
}
# Placeholder de desenvolvimento do settings: o próprio settings recusa usá-lo
# com DEBUG=False, então não é um segredo.
PERMITIDOS = {'django-insecure-dev-only-key-change-in-production'}

# Itens que a avaliação cobrou: (descrição, teste sobre a lista de caminhos).
OBRIGATORIOS = [
    ('templates HTML', lambda c: any('/templates/' in p and p.endswith('.html') for p in c)),
    ('modelo base website/templates/website/modelo.html',
     lambda c: 'website/templates/website/modelo.html' in c),
    ('JavaScript em static/js/', lambda c: any(p.startswith('static/js/') and p.endswith('.js') for p in c)),
    ('AGENTS.md', lambda c: 'AGENTS.md' in c),
    ('skills (.claude/skills/*/SKILL.md)',
     lambda c: any(p.startswith('.claude/skills/') and p.endswith('/SKILL.md') for p in c)),
    ('app.yaml.example', lambda c: 'app.yaml.example' in c),
    ('requirements.txt', lambda c: 'requirements.txt' in c),
    ('docs/', lambda c: any(p.startswith('docs/') for p in c)),
]

SEPARADOR = '=' * 80


def git(*args):
    resultado = subprocess.run(['git', *args], cwd=RAIZ, capture_output=True, check=True)
    return resultado.stdout.decode('utf-8')


def bloqueado(caminho):
    partes = PurePosixPath(caminho).parts
    return partes[-1] in BLOQUEADOS_NOMES or any(p in BLOQUEADOS_PASTAS for p in partes[:-1])


def eh_migration_automatica(caminho, texto):
    partes = PurePosixPath(caminho).parts
    if 'migrations' not in partes or partes[-1] == '__init__.py':
        return False
    return 'RunPython' not in texto and 'RunSQL' not in texto


def selecionar(com_migrations):
    """Lista (caminho, texto) dos arquivos versionados que entram no pacote."""
    selecionados = []
    for caminho in git('ls-files', '-z').split('\0'):
        if not caminho or bloqueado(caminho):
            continue
        nome = PurePosixPath(caminho).name
        if PurePosixPath(caminho).suffix not in EXTENSOES and nome not in NOMES_EXTRAS:
            continue
        arquivo = RAIZ / caminho
        if not arquivo.is_file():  # apagado na cópia de trabalho
            continue
        try:
            texto = arquivo.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue  # binário
        if not com_migrations and eh_migration_automatica(caminho, texto):
            continue
        selecionados.append((caminho, texto.replace('\r\n', '\n')))

    def ordem(item):
        caminho = item[0]
        if caminho in PRIMEIROS:
            return (0, PRIMEIROS.index(caminho), caminho)
        return (1, 0, caminho)

    return sorted(selecionados, key=ordem)


def procurar_segredos(arquivos):
    """Devolve 'caminho:linha (tipo)' de cada suspeita — nunca o valor."""
    achados = []
    for caminho, texto in arquivos:
        for numero, linha in enumerate(texto.splitlines(), start=1):
            for tipo, padrao in PADROES_SEGREDO.items():
                for achado in padrao.finditer(linha):
                    if achado.group(0) not in PERMITIDOS:
                        achados.append(f'{caminho}:{numero} ({tipo})')
    return achados


def montar(arquivos, log):
    caminhos = [c for c, _ in arquivos]
    partes = [
        SEPARADOR,
        'SÍTIO DE LURDES (projeto naes2026) — PACOTE DE ENTREGA',
        'Gerado por scripts/gerar_entrega.py a partir dos arquivos versionados no Git.',
        'Fora do pacote: .env, app.yaml real (ver app.yaml.example), db.sqlite3, .venv/,',
        'static_gcloud/, imagens e migrations geradas automaticamente.',
        SEPARADOR,
        '',
        'CONFERÊNCIA DOS ITENS OBRIGATÓRIOS',
    ]
    for descricao, teste in OBRIGATORIOS:
        partes.append(f'  [{"x" if teste(caminhos) else " "}] {descricao}')
    partes.append(f'  [{"x" if log.strip() else " "}] git log --oneline (no fim do arquivo)')
    partes += ['', f'ÍNDICE ({len(arquivos)} arquivos)']
    for caminho, texto in arquivos:
        partes.append(f'  {caminho}  ({len(texto.splitlines())} linhas)')
    partes.append('')

    for caminho, texto in arquivos:
        partes += [SEPARADOR, f'ARQUIVO: {caminho}', SEPARADOR, texto.rstrip('\n'), '']

    partes += [SEPARADOR, 'GIT LOG --ONELINE', SEPARADOR, log.rstrip('\n'), '']
    return '\n'.join(partes)


def main(argv=None):
    for fluxo in (sys.stdout, sys.stderr):  # acentos certos no console do Windows
        if hasattr(fluxo, 'reconfigure'):
            fluxo.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--com-migrations', action='store_true',
                        help='inclui também as migrations geradas pelo makemigrations')
    parser.add_argument('--saida', type=Path, default=SAIDA_PADRAO,
                        help=f'arquivo de saída (padrão: {SAIDA_PADRAO.relative_to(RAIZ)})')
    args = parser.parse_args(argv)

    arquivos = selecionar(args.com_migrations)
    log = git('log', '--oneline')
    caminhos = [c for c, _ in arquivos]

    faltando = [d for d, teste in OBRIGATORIOS if not teste(caminhos)]
    if not log.strip():
        faltando.append('git log --oneline')
    if faltando:
        print('ERRO: itens obrigatórios ausentes: ' + ', '.join(faltando), file=sys.stderr)
        return 1

    suspeitas = procurar_segredos(arquivos)
    if suspeitas:
        print('ERRO: possível segredo — nada foi gerado. Confira:', file=sys.stderr)
        for suspeita in suspeitas:
            print(f'  {suspeita}', file=sys.stderr)
        return 1

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    conteudo = montar(arquivos, log)
    args.saida.write_text(conteudo, encoding='utf-8', newline='\n')

    por_tipo = {}
    for caminho in caminhos:
        sufixo = PurePosixPath(caminho).suffix or PurePosixPath(caminho).name
        por_tipo[sufixo] = por_tipo.get(sufixo, 0) + 1
    resumo = ', '.join(f'{qtd} {tipo}' for tipo, qtd in sorted(por_tipo.items()))
    commits = len(log.strip().splitlines())
    print(f'Gerado: {args.saida} ({len(arquivos)} arquivos: {resumo}; {commits} commits no log; '
          f'{len(conteudo.encode("utf-8")) // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
