#!/bin/bash
# Fecha o acesso publico aos arquivos sensiveis de media/.
#
# Biometria e atestado medico sao dados pessoais sensiveis (LGPD Art.
# 11), e estavam servidos em aberto: bastava a URL, que aparece no HTML
# de quem tem acesso, para baixar de qualquer lugar sem sessao.
#
# O Nginx continua entregando os bytes, mas pergunta antes ao Django se
# quem pediu pode. Nenhuma pagina precisa mudar: as URLs sao as mesmas.
set -e

ARQ=/etc/nginx/sites-available/kronus
cp "$ARQ" "$ARQ.bak.$(date +%s)"

python3 - "$ARQ" <<'PY'
import sys

caminho = sys.argv[1]
with open(caminho, encoding="utf-8") as f:
    t = f.read()

if "_interno/permissao-midia" in t:
    print("ja configurado")
    raise SystemExit(0)

antigo = """    location /media/ {
        alias /opt/kronus/app/media/;"""

novo = """    # Subrequisicao de permissao. `internal` impede que alguem a chame
    # de fora para descobrir se esta autenticado.
    location = /_permissao_midia {
        internal;
        proxy_pass http://kronus_app/_interno/permissao-midia;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        include /etc/nginx/proxy_kronus.conf;
    }

    # Pastas sensiveis: biometria, atestado medico, comprovantes.
    # Entregues so a quem tem sessao com papel compativel.
    location ~ ^/media/(faces|atestados|justificativas|afastamentos)/ {
        auth_request /_permissao_midia;
        # `root`, e nao `alias`: com regex o alias exige remontar o
        # caminho na mao, e um erro ali serve o arquivo errado.
        root /opt/kronus/app;
        expires off;
        add_header Cache-Control "private, no-store" always;
        access_log off;
        add_header Content-Disposition "attachment";
        add_header X-Content-Type-Options "nosniff";
    }

    location /media/ {
        alias /opt/kronus/app/media/;"""

assert antigo in t, "bloco /media/ nao encontrado"
t = t.replace(antigo, novo, 1)

with open(caminho, "w", encoding="utf-8") as f:
    f.write(t)
print("configurado")
PY

nginx -t
