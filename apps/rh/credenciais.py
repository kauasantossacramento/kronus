"""
Kronus — entrega das credenciais ao colaborador.

A senha provisória existe uma vez só: `garantir_usuario` a devolve e não
guarda em lugar nenhum — guardar senha em texto para poder reexibir é
exatamente o que não se faz. O efeito colateral é que, se ninguém
entregar na hora, ela se perde e o acesso precisa ser refeito.

Era o que acontecia: a senha aparecia numa mensagem na tela, e a
mensagem some na primeira navegação. Quem cadastrou dez pessoas seguidas
entregava zero senhas.

O e-mail resolve isso sem guardar nada: o texto vai direto para quem vai
usar, e o sistema continua sem saber a senha depois de mandada.

**A tela continua mostrando também.** Só por e-mail deixaria quem
cadastrou sem nada nas mãos quando o envio falha — e falha de e-mail é
silenciosa por natureza.
"""
import logging

logger = logging.getLogger("kronus.rh")


def enviar_credenciais(colaborador, senha: str) -> bool:
    """
    Manda o acesso para o e-mail do colaborador.

    Devolve `True` quando saiu. `False` — sem e-mail cadastrado, ou
    falha no envio — não é erro: significa que a entrega ficou com quem
    cadastrou, e a tela avisa isso.

    Nunca levanta. Um servidor de e-mail fora do ar não pode impedir a
    criação de um acesso que já foi criada.
    """
    endereco = (getattr(colaborador, "email", "") or "").strip()
    if not endereco:
        return False

    try:
        from django.conf import settings
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string
        from django.urls import reverse

        empresa = colaborador.empresa
        base = (getattr(settings, "KRONUS", {}) or {}).get("APP_URL", "")
        url_entrada = f"{base.rstrip('/')}{reverse('accounts:login')}" if base else ""

        contexto = {
            "colaborador": colaborador,
            "empresa": empresa,
            "usuario": colaborador.user.username if colaborador.user else endereco,
            "senha": senha,
            "url_entrada": url_entrada,
            "KRONUS": settings.KRONUS,
        }
        html = render_to_string("rh/email/credenciais.html", contexto)
        texto = (
            f"Olá, {colaborador.nome_exibicao}.\n\n"
            f"Seu acesso ao Kronus, da {empresa.nome_exibicao}, foi criado.\n\n"
            f"Usuário: {contexto['usuario']}\n"
            f"Senha provisória: {senha}\n\n"
            "A senha será trocada no primeiro acesso.\n"
            + (f"\nEntre em: {url_entrada}\n" if url_entrada else "")
        )

        mensagem = EmailMultiAlternatives(
            subject=f"Seu acesso ao Kronus — {empresa.nome_exibicao}",
            body=texto,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[endereco],
        )
        mensagem.attach_alternative(html, "text/html")
        mensagem.send(fail_silently=False)
        logger.info("Credenciais enviadas para o colaborador %s.", colaborador.pk)
        return True
    except Exception:
        # Falha aqui nao desfaz o acesso, que ja existe. A tela avisa
        # que a entrega ficou com quem cadastrou.
        logger.exception(
            "Falha ao enviar credenciais do colaborador %s.", colaborador.pk
        )
        return False
