"""
Kronus — dados de demonstracao.

Cria a estrutura minima para navegar o sistema em desenvolvimento:
planos comerciais, um cliente com duas empresas, usuarios de cada papel,
departamentos, cargos e colaboradores.

Uso:
    python manage.py shell -c "exec(open('scripts/seed_data.py', encoding='utf-8').read())"

Ou, apos configurar o DJANGO_SETTINGS_MODULE:
    python scripts/seed_data.py
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

if __name__ == "__main__" and "django" not in sys.modules:  # execucao direta
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    import django

    django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from apps.clientes.models import Cliente, Empresa  # noqa: E402
from apps.core.constants import TipoEscala, TipoUsuario  # noqa: E402
from apps.core.models import Feriado  # noqa: E402
from apps.master.models import Plano  # noqa: E402
from apps.ponto.models import EscalaTrabalho  # noqa: E402
from apps.rh.models import Cargo, Colaborador, Departamento  # noqa: E402
from apps.totem.models import Totem  # noqa: E402

User = get_user_model()

SENHA_PADRAO = "kronus2026"


def log(mensagem):
    print(f"  {mensagem}")


# ══════════════════════════════════════════════════════════════
# 1. Planos
# ══════════════════════════════════════════════════════════════
print("\n[1/7] Planos comerciais")
PLANOS = [
    {
        "nome": "Essencial",
        "slug": "essencial",
        "descricao": "Para equipes pequenas que precisam de ponto legal e simples.",
        "ordem": 1,
        "max_empresas": 1,
        "max_colaboradores": 25,
        "max_totems": 0,
        "preco_mensal": 149.90,
        "tem_banco_horas": True,
    },
    {
        "nome": "Profissional",
        "slug": "profissional",
        "descricao": "Reconhecimento facial em totem, geofencing e múltiplas empresas.",
        "ordem": 2,
        "destaque": True,
        "max_empresas": 3,
        "max_colaboradores": 150,
        "max_totems": 3,
        "preco_mensal": 449.90,
        "preco_por_colaborador": 2.50,
        "tem_totem": True,
        "tem_geofencing": True,
        "tem_offline": True,
        "tem_banco_horas": True,
    },
    {
        "nome": "Enterprise",
        "slug": "enterprise",
        "descricao": "Operações multi-filial com API, webhooks e portal do contador.",
        "ordem": 3,
        "max_empresas": 20,
        "max_colaboradores": 2000,
        "max_totems": 30,
        "preco_mensal": 1490.00,
        "preco_por_colaborador": 1.80,
        "tem_api": True,
        "tem_totem": True,
        "tem_geofencing": True,
        "tem_offline": True,
        "tem_banco_horas": True,
        "tem_webhook": True,
        "tem_portal_contador": True,
        "tem_esocial": True,
        "rate_limit_api_hora": 5000,
    },
]

for dados in PLANOS:
    plano, criado = Plano.objects.get_or_create(slug=dados["slug"], defaults=dados)
    log(f"{'criado' if criado else 'existente'}: {plano.nome}")

plano_pro = Plano.objects.get(slug="profissional")

# ══════════════════════════════════════════════════════════════
# 2. Usuario Master (KS TEC)
# ══════════════════════════════════════════════════════════════
print("\n[2/7] Usuário Master")
master = User.objects.filter(email="admin@kstec.online").first()
if master is None:
    master = User.objects.create_superuser(
        email="admin@kstec.online",
        password=SENHA_PADRAO,
        nome_completo="Administrador KS TEC",
    )
    log(f"criado: {master.email} / {SENHA_PADRAO}")
else:
    log(f"existente: {master.email}")

# ══════════════════════════════════════════════════════════════
# 3. Cliente e empresas
# ══════════════════════════════════════════════════════════════
print("\n[3/7] Cliente e empresas")
cliente, criado = Cliente.objects.get_or_create(
    cnpj="11222333000181",
    defaults={
        "razao_social": "Grupo Aurora Comércio e Serviços Ltda",
        "nome_fantasia": "Grupo Aurora",
        "plano": plano_pro,
        "email_contato": "rh@grupoaurora.com.br",
        "telefone": "(75) 3641-0000",
        "responsavel": "Marina Duarte",
        "cidade": "Valença",
        "uf": "BA",
        "data_inicio_contrato": date.today() - timedelta(days=90),
    },
)
log(f"{'criado' if criado else 'existente'}: {cliente}")

EMPRESAS = [
    {
        "cnpj": "11222333000262",
        "razao_social": "Aurora Supermercados Ltda",
        "nome_fantasia": "Aurora Supermercados",
        "cidade": "Valença",
        "uf": "BA",
    },
    {
        "cnpj": "11222333000343",
        "razao_social": "Aurora Logística e Transportes Ltda",
        "nome_fantasia": "Aurora Logística",
        "cidade": "Salvador",
        "uf": "BA",
    },
]

empresas = []
for dados in EMPRESAS:
    empresa, criado = Empresa.objects.get_or_create(
        cnpj=dados["cnpj"], defaults={**dados, "cliente": cliente}
    )
    empresas.append(empresa)
    log(f"{'criada' if criado else 'existente'}: {empresa.nome_exibicao}")

empresa_principal = empresas[0]

# ══════════════════════════════════════════════════════════════
# 4. Usuarios do cliente
# ══════════════════════════════════════════════════════════════
print("\n[4/7] Usuários do cliente")


def criar_usuario(email, nome, tipo, empresas_vinculadas=()):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email=email,
            password=SENHA_PADRAO,
            nome_completo=nome,
            tipo=tipo,
            cliente=cliente,
        )
        log(f"criado: {email} ({tipo}) / {SENHA_PADRAO}")
    else:
        log(f"existente: {email}")
    if empresas_vinculadas:
        user.empresas.set(empresas_vinculadas)
    return user


criar_usuario("marina@grupoaurora.com.br", "Marina Duarte", TipoUsuario.CLIENTE)
criar_usuario(
    "rh.supermercados@grupoaurora.com.br",
    "Ricardo Menezes",
    TipoUsuario.RH,
    [empresa_principal],
)

# ══════════════════════════════════════════════════════════════
# 5. Estrutura organizacional
# ══════════════════════════════════════════════════════════════
print("\n[5/7] Departamentos, cargos e escalas")
for nome in ["Administrativo", "Operação de Loja", "Açougue", "Estoque"]:
    departamento, criado = Departamento.objects.get_or_create(
        empresa=empresa_principal, nome=nome, deleted_at__isnull=True,
        defaults={"empresa": empresa_principal, "nome": nome},
    )
    log(f"departamento {'criado' if criado else 'existente'}: {nome}")

for nome, cbo, salario in [
    ("Operador de Caixa", "5211-30", 1650.00),
    ("Repositor", "5211-10", 1580.00),
    ("Açougueiro", "8485-05", 2100.00),
    ("Assistente Administrativo", "4110-05", 2400.00),
]:
    cargo, criado = Cargo.objects.get_or_create(
        empresa=empresa_principal, nome=nome, deleted_at__isnull=True,
        defaults={
            "empresa": empresa_principal,
            "nome": nome,
            "cbo": cbo,
            "salario_base": salario,
        },
    )
    log(f"cargo {'criado' if criado else 'existente'}: {nome}")

jornada_comercial = {
    "dias": {
        "0": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "1": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "2": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "3": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "4": {"entrada": "08:00", "intervalo_inicio": "12:00", "intervalo_fim": "13:00", "saida": "17:00"},
        "5": {"entrada": "08:00", "saida": "12:00"},
        "6": None,
    },
    "carga_semanal_min": 2640,
}

escala, criado = EscalaTrabalho.objects.get_or_create(
    empresa=empresa_principal,
    nome="Comercial 44h",
    deleted_at__isnull=True,
    defaults={
        "empresa": empresa_principal,
        "nome": "Comercial 44h",
        "tipo": TipoEscala.FIXA,
        "descricao": "Segunda a sexta 08h–17h com 1h de intervalo, sábado 08h–12h.",
        "jornada_config": jornada_comercial,
        "carga_diaria_min": 480,
        "carga_semanal_min": 2640,
    },
)
log(f"escala {'criada' if criado else 'existente'}: {escala.nome}")

escala_12x36, criado = EscalaTrabalho.objects.get_or_create(
    empresa=empresa_principal,
    nome="Plantão 12x36",
    deleted_at__isnull=True,
    defaults={
        "empresa": empresa_principal,
        "nome": "Plantão 12x36",
        "tipo": TipoEscala.ESCALA_12X36,
        "jornada_config": {"padrao_12x36": {"entrada": "07:00", "saida": "19:00"}},
        "carga_diaria_min": 720,
        "data_referencia": date.today(),
        "exige_intervalo": False,
    },
)
log(f"escala {'criada' if criado else 'existente'}: {escala_12x36.nome}")

# ══════════════════════════════════════════════════════════════
# 6. Colaboradores
# ══════════════════════════════════════════════════════════════
print("\n[6/7] Colaboradores")
COLABORADORES = [
    ("João da Silva Souza", "52998224725", date(1990, 3, 12), "Operador de Caixa", "Operação de Loja"),
    ("Maria Aparecida Lima", "15350946056", date(1985, 7, 4), "Repositor", "Estoque"),
    ("Carlos Eduardo Ramos", "71428793860", date(1978, 11, 23), "Açougueiro", "Açougue"),
    ("Fernanda Castro Alves", "40442820135", date(1995, 1, 30), "Assistente Administrativo", "Administrativo"),
]

for indice, (nome, cpf, nascimento, cargo, departamento) in enumerate(COLABORADORES, start=1):
    colaborador, criado = Colaborador.objects.get_or_create(
        empresa=empresa_principal,
        cpf=cpf,
        deleted_at__isnull=True,
        defaults={
            "empresa": empresa_principal,
            "cpf": cpf,
            "nome_completo": nome,
            "data_nascimento": nascimento,
            "cargo": cargo,
            "matricula": f"{indice:04d}",
            "data_admissao": date.today() - timedelta(days=200 + indice * 15),
            "departamento": Departamento.objects.filter(
                empresa=empresa_principal, nome=departamento
            ).first(),
            "cargo_ref": Cargo.objects.filter(
                empresa=empresa_principal, nome=cargo
            ).first(),
            "escala": escala,
            "email": f"{nome.split()[0].lower()}@grupoaurora.com.br",
        },
    )
    log(f"{'criado' if criado else 'existente'}: {colaborador.nome_completo}")

# ══════════════════════════════════════════════════════════════
# 7. Totem e feriados
# ══════════════════════════════════════════════════════════════
print("\n[7/7] Totem e feriados nacionais")
totem, criado = Totem.objects.get_or_create(
    identificador="TOTEM-AURORA-01",
    defaults={
        "empresa": empresa_principal,
        "apelido": "Recepção — Loja Centro",
        "local_instalacao": "Entrada de funcionários",
        "em_comodato": True,
        "data_instalacao": date.today() - timedelta(days=60),
        "serial_tablet": "PSTV7-000123456",
    },
)
log(f"totem {'criado' if criado else 'existente'}: {totem} (token: {totem.token_acesso[:12]}…)")

FERIADOS_NACIONAIS = [
    ("Confraternização Universal", date(date.today().year, 1, 1)),
    ("Tiradentes", date(date.today().year, 4, 21)),
    ("Dia do Trabalho", date(date.today().year, 5, 1)),
    ("Independência do Brasil", date(date.today().year, 9, 7)),
    ("Nossa Senhora Aparecida", date(date.today().year, 10, 12)),
    ("Finados", date(date.today().year, 11, 2)),
    ("Proclamação da República", date(date.today().year, 11, 15)),
    ("Natal", date(date.today().year, 12, 25)),
]
for nome, dia in FERIADOS_NACIONAIS:
    Feriado.objects.get_or_create(
        nome=nome, data=dia, empresa=None, defaults={"recorrente": True}
    )
log(f"{len(FERIADOS_NACIONAIS)} feriados nacionais garantidos")

print("\n" + "=" * 62)
print("  Seed concluído.")
print("=" * 62)
print(f"  Master ......... admin@kstec.online          / {SENHA_PADRAO}")
print(f"  Admin cliente .. marina@grupoaurora.com.br   / {SENHA_PADRAO}")
print(f"  Admin RH ....... rh.supermercados@grupoaurora.com.br / {SENHA_PADRAO}")
print(f"  Totem .......... /totem/{totem.token_acesso}/")
print("=" * 62 + "\n")
