"""Kronus — configuracao do Celery (jobs assincronos e agendados)."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("kronus")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# A inferencia facial vai para uma fila propria, atendida por um worker
# dedicado. Sem isso, uma tarefa de 217 ms com 1,1 GB de modelo
# dividiria o mesmo processo das tarefas leves (webhooks, consolidacao),
# e todas passariam a carregar o custo de memoria do TensorFlow.
app.conf.task_routes = {
    "apps.facial.tasks.gerar_embedding_remoto": {"queue": "facial"},
}
# O worker facial nao deve puxar mais de uma tarefa por vez: com 1 vCPU,
# duas inferencias concorrentes so disputam o mesmo nucleo.
app.conf.worker_prefetch_multiplier = 1


# ==============================================================
# Agenda (Celery Beat)
# ==============================================================
app.conf.beat_schedule = {
    # Demonstracoes vencidas: o corte tambem e checado no acesso, mas sem
    # esta varredura o painel do Master mostraria como "ativa" uma
    # demonstracao que ja acabou.
    "expirar-demonstracoes": {
        "task": "apps.comercial.tasks.expirar_demonstracoes",
        "schedule": crontab(minute=7),
    },
    # Secao 8.4 — calculo automatico diario do banco de horas as 23:59
    "fechamento-diario-banco-horas": {
        "task": "apps.ponto.tasks.fechar_banco_horas_do_dia",
        "schedule": crontab(hour=23, minute=59),
    },
    # Secao 8.7 — notificacao de esquecimento de ponto
    "notificar-esquecimento-ponto": {
        "task": "apps.notificacoes.tasks.notificar_esquecimento_ponto",
        "schedule": crontab(hour=20, minute=0),
    },
    # Secao 8.7 — totem offline ha mais de 10 minutos
    "monitorar-totens-offline": {
        "task": "apps.totem.tasks.monitorar_totens_offline",
        "schedule": crontab(minute="*/5"),
    },
    # Secao 14, regra 5 — expurgo de dados biometricos apos desligamento
    "expurgar-dados-faciais": {
        "task": "apps.facial.tasks.expurgar_embeddings_desligados",
        "schedule": crontab(hour=3, minute=30),
    },
    # Secao 8.8 — rede de seguranca dos webhooks: recupera entregas que
    # o broker perdeu e executa as retentativas vencidas.
    "reprocessar-entregas-de-webhook": {
        "task": "apps.notificacoes.tasks.reprocessar_entregas_pendentes",
        "schedule": crontab(minute="*/10"),
    },
    # Portaria 671 — auditoria da cadeia de hashes (domingos, 4h)
    "verificar-integridade-das-cadeias": {
        "task": "apps.ponto.tasks.verificar_integridade_das_cadeias",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover
    print(f"Request: {self.request!r}")
