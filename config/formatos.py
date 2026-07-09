"""
Formatos de impresión en px a 300 DPI.

  Referencia de medidas reales:
    5 cm  = 591 px   (5  / 2.54 * 300)
    10 cm = 1181 px  (10 / 2.54 * 300)
    15 cm = 1772 px  (15 / 2.54 * 300)

  Nota de impresión:
    La tira 5×15 se imprime DE A DOS en una hoja 10×15.
    PrinterManager.preparar_para_impresion() genera el 2-up automáticamente.
"""

FORMATOS = [
    {
        "key":          "tira_5x15",
        "label":        "Tira 5×15 cm  (imprime 2 por hoja)",
        "desc":         "Tira vertical clásica. 3 fotos + panel de branding. "
                        "Se envían 2 tiras lado a lado (10×15 cm físicos).",
        "w":            600,    # px a 300 dpi — 2" exacto para Kodak 305
        "h":            1800,
        "n_fotos":      3,
        "cols":         1,
        "filas":        3,
        "print_2up":    True,
        "print_w":      1200,   # 4" exacto a 300 dpi — canvas 2-up sin escalado
        "print_h":      1800,
        "print_w_mm":   101.6,  # 4" exactos en mm — evita asimetría de 1px al escalar
        "print_h_mm":   152.4,  # 6" exactos en mm
    },
    {
        "key":          "foto_10x15",
        "label":        "Foto 10×15 cm  (1 foto por hoja)",
        "desc":         "Formato foto estándar. 4 fotos en 2×2 + panel de branding. "
                        "Ocupa 10×15 cm físicos.",
        "w":            1200,
        "h":            1800,
        "n_fotos":      4,
        "cols":         2,
        "filas":        2,
        "print_2up":    False,
        "print_w":      1200,
        "print_h":      1800,
        "print_w_mm":   101.6,
        "print_h_mm":   152.4,
    },
]

FORMATO_MAP = {f["key"]: f for f in FORMATOS}


def get_formato(key: str) -> dict:
    return FORMATO_MAP.get(key, FORMATOS[0])
