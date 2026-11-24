"""Presets locais de legenda, expressos nas propriedades que o renderer suporta."""

CAPTION_PRESETS = (
    ('Cinematográfico', 'Arial', 48, '#FFFFFF', '#000000', 4),
    ('YouTube clássico', 'Arial', 44, '#FFFFFF', '#000000', 3),
    ('YouTube moderno', 'Segoe UI', 54, '#FFFFFF', '#101010', 3),
    ('Shorts', 'Arial', 58, '#FFD166', '#000000', 4),
    ('Reels', 'Arial', 54, '#FFFFFF', '#111111', 3),
    ('TikTok dinâmico', 'Arial', 58, '#40E0D0', '#111111', 4),
    ('Palavra por palavra', 'Arial', 56, '#FFFFFF', '#000000', 4),
    ('Karaokê', 'Arial', 54, '#FFE45E', '#171717', 4),
    ('Gaming', 'Arial', 56, '#FFFFFF', '#000000', 5),
    ('Gaming neon', 'Arial', 56, '#69F0FF', '#24104F', 5),
    ('Gaming amarelo', 'Arial', 56, '#FFE600', '#111111', 5),
    ('Gaming vermelho', 'Arial', 56, '#FF5555', '#111111', 5),
    ('Podcast', 'Segoe UI', 42, '#FFFFFF', '#161616', 3),
    ('Podcast minimalista', 'Segoe UI', 38, '#F2F5F8', '#111111', 1),
    ('Documentário', 'Georgia', 42, '#FFFFFF', '#000000', 2),
    ('Educacional', 'Arial', 46, '#FFFFFF', '#14213D', 3),
    ('Jornalístico', 'Arial', 44, '#FFFFFF', '#101010', 3),
    ('Alto contraste', 'Arial', 52, '#FFFFFF', '#000000', 6),
    ('Caixa preta', 'Arial', 42, '#FFFFFF', '#000000', 0),
    ('Caixa transparente', 'Arial', 42, '#FFFFFF', '#202020', 1),
    ('Branco com contorno preto', 'Arial', 46, '#FFFFFF', '#000000', 4),
    ('Amarelo com contorno preto', 'Arial', 48, '#FFE600', '#000000', 4),
    ('Destaque progressivo', 'Arial', 54, '#FFD166', '#000000', 4),
    ('Minimalista elegante', 'Georgia', 40, '#F7F3EA', '#1A1A1A', 1),
)

def preset_properties(index: int) -> dict[str, object]:
    """Index 1-based para manter compatibilidade com o preset legado."""
    name, family, size, color, stroke, width = CAPTION_PRESETS[index - 1]
    extra={
        19:{'background_color':'#000000','background_opacity':0.92,'stroke_width':0},
        20:{'background_color':'#202020','background_opacity':0.55,'stroke_width':1},
        21:{'font_weight':'bold'},22:{'font_weight':'bold'},
        23:{'font_weight':'bold'},24:{'font_weight':'normal'},
    }.get(index,{})
    return {'font_family': family, 'font_size': size, 'font_color': color,
            'stroke_color': stroke, 'stroke_width': width, 'preset_name': name,
            **extra}
