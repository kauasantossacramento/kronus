"""
Kronus — sistema de ícones em SVG inline.

Substitui emojis por vetores: emojis mudam de desenho a cada sistema
operacional, não herdam a cor do texto e não escalam com o design
system. Aqui cada ícone é uma geometria de 24x24 em `stroke`
`currentColor`, o que faz o ícone assumir a cor do contexto e manter
peso visual uniforme com a tipografia (Seção 3 do plano).

Uso no template:

    {% load kronus_icons %}
    {% icone "usuarios" %}
    {% icone "relogio" classe="h-6 w-6 text-[var(--kronus-gold-500)]" %}
    {% icone "alerta" titulo="Atenção" %}

Todos os traçados foram desenhados para este projeto — nenhum depende
de biblioteca externa, o que mantém o totem funcionando offline.
"""
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

#: nome -> conteúdo interno do <svg> (grid 24x24, traçado em currentColor)
ICONES: dict[str, str] = {
    # ── Navegação e estrutura ─────────────────────────────────
    "dashboard": (
        '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/>'
        '<rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/>'
        '<rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/>'
        '<rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>'
    ),
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "fechar": '<path d="M6 6l12 12M18 6L6 18"/>',
    "seta_direita": '<path d="M5 12h13M13 6.5 18.5 12 13 17.5"/>',
    "seta_esquerda": '<path d="M19 12H6M11 6.5 5.5 12 11 17.5"/>',
    "chevron_baixo": '<path d="M6.5 9.5 12 15l5.5-5.5"/>',
    "mais": '<path d="M12 5v14M5 12h14"/>',
    "lupa": '<circle cx="11" cy="11" r="6.5"/><path d="M15.8 15.8 20.5 20.5"/>',
    "filtro": '<path d="M4 5.5h16l-6.2 7.3v5.4l-3.6 2v-7.4L4 5.5Z"/>',
    "download": '<path d="M12 4v11M8 11.5l4 4 4-4"/><path d="M5 19.5h14"/>',
    "editar": (
        '<path d="M4 20h4l10-10a2.5 2.5 0 0 0-3.5-3.5L4.5 16.5 4 20Z"/>'
        '<path d="M13.5 7.5 16.5 10.5"/>'
    ),

    # ── Pessoas ───────────────────────────────────────────────
    "usuario": (
        '<circle cx="12" cy="8" r="3.75"/>'
        '<path d="M4.5 20.5c0-3.6 3.36-6.5 7.5-6.5s7.5 2.9 7.5 6.5"/>'
    ),
    "usuarios": (
        '<circle cx="9" cy="8" r="3.25"/>'
        '<path d="M3.5 20c0-3.04 2.46-5.5 5.5-5.5s5.5 2.46 5.5 5.5"/>'
        '<path d="M16 5.2a3.25 3.25 0 0 1 0 5.6"/>'
        '<path d="M17.2 14.9c1.96.66 3.3 2.4 3.3 4.5"/>'
    ),
    "rosto": (
        '<path d="M4 8.5V6a2 2 0 0 1 2-2h2.5M15.5 4H18a2 2 0 0 1 2 2v2.5'
        'M20 15.5V18a2 2 0 0 1-2 2h-2.5M8.5 20H6a2 2 0 0 1-2-2v-2.5"/>'
        '<circle cx="9.5" cy="10.5" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="14.5" cy="10.5" r=".9" fill="currentColor" stroke="none"/>'
        '<path d="M9.5 14.6a3.6 3.6 0 0 0 5 0"/>'
    ),
    "medalha": (
        '<circle cx="12" cy="9.5" r="5.5"/>'
        '<path d="M8.5 14.2 7 21l5-2.5 5 2.5-1.5-6.8"/>'
    ),

    # ── Tempo e ponto ─────────────────────────────────────────
    "relogio": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.2 2"/>',
    "ampulheta": (
        '<path d="M7 3.5h10M7 20.5h10"/>'
        '<path d="M8.5 3.5v3c0 2.4 3.5 3.6 3.5 5.5 0 1.9-3.5 3.1-3.5 5.5v3"/>'
        '<path d="M15.5 3.5v3c0 2.4-3.5 3.6-3.5 5.5 0 1.9 3.5 3.1 3.5 5.5v3"/>'
    ),
    "calendario": (
        '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/>'
        '<path d="M3.5 9.5h17M8 3.5v3M16 3.5v3"/>'
        '<circle cx="8.5" cy="13.8" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="12" cy="13.8" r=".9" fill="currentColor" stroke="none"/>'
        '<circle cx="15.5" cy="13.8" r=".9" fill="currentColor" stroke="none"/>'
    ),
    "lua": '<path d="M20 14.6A8.5 8.5 0 0 1 9.4 4 8.5 8.5 0 1 0 20 14.6Z"/>',
    "sol": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4'
        'M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7"/>'
    ),
    "banco_horas": (
        '<path d="M3.5 9.5 12 4.5l8.5 5"/>'
        '<path d="M6 10v7.5M10 10v7.5M14 10v7.5M18 10v7.5"/>'
        '<path d="M3.5 20.5h17"/>'
    ),

    # ── Documentos ────────────────────────────────────────────
    "documento": (
        '<path d="M13.8 3.5H7.5A1.5 1.5 0 0 0 6 5v14a1.5 1.5 0 0 0 1.5 1.5h9'
        'A1.5 1.5 0 0 0 18 19V7.7L13.8 3.5Z"/>'
        '<path d="M13.8 3.5v3.7a.5.5 0 0 0 .5.5H18"/>'
        '<path d="M9 12.5h6M9 16h4"/>'
    ),
    "lista": '<path d="M4.5 6.5h15M4.5 12h15M4.5 17.5h9"/>',
    "saude": (
        '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/>'
        '<path d="M12 8.2v7.6M8.2 12h7.6"/>'
    ),
    "grafico": (
        '<path d="M4 4v16h16"/>'
        '<rect x="7.5" y="12" width="3" height="8" rx=".8"/>'
        '<rect x="12.2" y="8.5" width="3" height="11.5" rx=".8"/>'
        '<rect x="17" y="5.5" width="3" height="14.5" rx=".8"/>'
    ),

    # ── Empresa e comercial ───────────────────────────────────
    "predio": (
        '<path d="M4 20.5V5.5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v15"/>'
        '<path d="M14 10.5h4a2 2 0 0 1 2 2v8"/>'
        '<path d="M2.8 20.5h18.4"/>'
        '<path d="M7 7.5h3M7 11h3M7 14.5h3M16.8 14.5h.8"/>'
    ),
    "cartao": (
        '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/>'
        '<path d="M3 10h18M6.5 14.5h4"/>'
    ),
    "pasta": (
        '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.4a2 2 0 0 1 1.6.8l1 1.2h7'
        'a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-10Z"/>'
    ),

    # ── Equipamentos e integração ─────────────────────────────
    # O totem: tablet em pedestal. O retangulo e a tela, a linha
    # horizontal e a camera frontal, e a base fecha o desenho como
    # equipamento fixo — nao como um tablet de mao.
    "totem": (
        '<rect x="6.5" y="2.8" width="11" height="14" rx="1.8"/>'
        '<circle cx="12" cy="6.2" r="1.1"/>'
        '<path d="M9.4 10.2h5.2M9.4 13h3.4"/>'
        '<path d="M12 16.8v2.6M8.6 21.2h6.8"/>'
    ),
    # Webhook: o evento que sai de um sistema e entra em outro. Tres
    # nos ligados por um caminho, nao uma seta — a entrega e assincrona
    # e pode ser retentada.
    "webhook": (
        '<circle cx="6" cy="16.5" r="2.6"/>'
        '<circle cx="18" cy="16.5" r="2.6"/>'
        '<circle cx="12" cy="6" r="2.6"/>'
        '<path d="M10.6 8.3 7.4 14.1M13.4 8.3l3.2 5.8M8.6 16.5h6.8"/>'
    ),
    "antena": (
        '<path d="M6.4 7.4a7.5 7.5 0 0 0 0 9.2M17.6 7.4a7.5 7.5 0 0 1 0 9.2"/>'
        '<path d="M9.4 10.6a3.4 3.4 0 0 0 0 2.8M14.6 10.6a3.4 3.4 0 0 1 0 2.8"/>'
        '<circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>'
    ),
    "link": (
        '<path d="M10.2 13.8a4 4 0 0 0 5.66 0l2.83-2.83a4 4 0 1 0-5.66-5.66l-1.34 1.34"/>'
        '<path d="M13.8 10.2a4 4 0 0 0-5.66 0L5.3 13.03a4 4 0 1 0 5.66 5.66l1.34-1.34"/>'
    ),
    "api": '<path d="M9 7.5 4.5 12 9 16.5M15 7.5 19.5 12 15 16.5"/>',
    "chave": (
        '<circle cx="8" cy="12" r="3.6"/>'
        '<path d="M11.6 12H20M17 12v3M20 12v2.4"/>'
    ),
    "camera": (
        '<path d="M3.5 8.8a2 2 0 0 1 2-2h1.9l1.2-2h6.8l1.2 2h1.9a2 2 0 0 1 2 2v8.7'
        'a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V8.8Z"/>'
        '<circle cx="12" cy="13" r="3.4"/>'
    ),
    "local": (
        '<path d="M12 21s6.5-5.4 6.5-10.5a6.5 6.5 0 1 0-13 0C5.5 15.6 12 21 12 21Z"/>'
        '<circle cx="12" cy="10.5" r="2.5"/>'
    ),

    # ── Estado e feedback ─────────────────────────────────────
    "check": '<path d="M5 12.5 10 17.5 19 7"/>',
    "check_circulo": '<circle cx="12" cy="12" r="8.5"/><path d="M8.4 12.3 11 15l4.6-5.4"/>',
    "alerta": (
        '<path d="M12 4.4 21.2 19.6H2.8L12 4.4Z"/><path d="M12 10.2v4"/>'
        '<circle cx="12" cy="16.9" r=".9" fill="currentColor" stroke="none"/>'
    ),
    "erro": '<circle cx="12" cy="12" r="8.5"/><path d="M9.2 9.2 14.8 14.8M14.8 9.2 9.2 14.8"/>',
    "info": (
        '<circle cx="12" cy="12" r="8.5"/><path d="M12 11.2v5.3"/>'
        '<circle cx="12" cy="8" r=".9" fill="currentColor" stroke="none"/>'
    ),
    "pausa": '<circle cx="12" cy="12" r="8.5"/><path d="M10 9v6M14 9v6"/>',
    "sino": (
        '<path d="M6.5 10.2a5.5 5.5 0 0 1 11 0c0 3.9 1.5 5.3 1.5 5.3H5s1.5-1.4 1.5-5.3Z"/>'
        '<path d="M10 18.8a2 2 0 0 0 4 0"/>'
    ),
    "escudo": (
        '<path d="M12 3.4 5 5.9V12c0 4.4 3 7.6 7 8.6 4-1 7-4.2 7-8.6V5.9L12 3.4Z"/>'
        '<path d="M9.2 12.2 11.2 14.2 15 10.2"/>'
    ),
    "balanca": (
        '<path d="M12 4.5v15M7.5 19.5h9"/><path d="M12 7.2 5.2 9.4M12 7.2l6.8 2.2"/>'
        '<path d="M2.4 15a2.8 2.8 0 0 0 5.6 0L5.2 9.4 2.4 15Z"/>'
        '<path d="M16 15a2.8 2.8 0 0 0 5.6 0l-2.8-5.6L16 15Z"/>'
    ),
    "sair": (
        '<path d="M15 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-2"/>'
        '<path d="M10.5 12h9.5M17.2 8.6 20.5 12l-3.3 3.4"/>'
    ),
    "config": (
        '<path d="M4 7.5h9M17.2 7.5h2.8M4 16.5h2.8M11 16.5h9"/>'
        '<circle cx="15.1" cy="7.5" r="2.2"/><circle cx="8.9" cy="16.5" r="2.2"/>'
    ),
    "raio": '<path d="M13.2 3 5.4 13.8h5.9l-.9 7.2 7.8-10.8h-5.9l.9-7.2Z"/>',
    "estrela": (
        '<path d="m12 4.2 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4-3.9-3.8'
        ' 5.4-.8L12 4.2Z"/>'
    ),
    # Balao de conversa com o fone: a marca do WhatsApp e registrada, e
    # reproduzi-la num SVG proprio seria uso indevido. Este e o simbolo
    # generico de conversa telefonica, que comunica a mesma coisa.
    "whatsapp": (
        '<path d="M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3.5 20.5l1.6-4.8A8.5 8.5 0 1 1 21 11.5Z"/>'
        '<path d="M9 9.3c.2-.5.5-.5.8-.5h.6c.2 0 .4 0 .6.5l.7 1.6c.1.3 0 .5-.1.7l-.4.4'
        'c-.1.2-.2.3 0 .6a6 6 0 0 0 2.4 2.1c.3.2.4.1.6 0l.5-.6c.2-.2.4-.2.6-.1l1.6.8'
        'c.2.1.4.2.4.4v.5c0 .6-.5 1.2-1 1.4-.5.2-1.2.2-3.4-.8a9 9 0 0 1-3.8-3.8'
        'c-.8-1.7-.6-2.6-.5-3.2Z"/>'
    ),
}

#: Ícone usado quando o nome pedido não existe — falha visível, não silenciosa.
FALLBACK = '<circle cx="12" cy="12" r="8.5" stroke-dasharray="3 3"/>'


@register.simple_tag(name="icone")
def icone(nome, classe="h-5 w-5", stroke=1.6, titulo=""):
    """
    Renderiza um ícone SVG inline.

    `titulo` torna o ícone acessível (vira `<title>` e `role="img"`);
    sem ele o ícone é decorativo e recebe `aria-hidden`.
    """
    corpo = ICONES.get(nome, FALLBACK)
    acessibilidade = (
        f'role="img" aria-label="{escape(titulo)}"' if titulo else 'aria-hidden="true"'
    )
    rotulo = f"<title>{escape(titulo)}</title>" if titulo else ""
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round" class="{escape(classe)}" {acessibilidade}>'
        f"{rotulo}{corpo}</svg>"
    )


@register.simple_tag(name="icone_existe")
def icone_existe(nome) -> bool:
    return nome in ICONES
