"""Cartões de abertura, créditos e encerramento no padrão da PASCOM (placa floral + textos), a partir
de um JSON de parâmetros. Pensado para virar um gerador de cartões do DMaker depois."""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
D = Path(__file__).parent
P = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SCRIPT = str(D / "GreatVibes-Regular.ttf")
SERIF_IT = str(D / "PlayfairDisplay-Italic.ttf")
SERIF = "C:/Windows/Fonts/georgia.ttf"
INK = (26, 26, 26)
W, H = 1920, 1080

def plate() -> Image.Image:
    return Image.open(D / P.get("placa", "plate.png")).convert("RGBA")

def text_center(img, text, font_path, size, y, color=INK, shadow=True, x=W / 2):
    """Texto centrado em x, com sombra suave como no cartão original."""
    font = ImageFont.truetype(font_path, size)
    w = font.getlength(text)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x - w / 2 + 4, y + 5), text, font=font, fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(4))
        img.alpha_composite(sh)
    ImageDraw.Draw(img).text((x - w / 2, y), text, font=font, fill=color)
    return font.getbbox(text)[3] - font.getbbox(text)[1]

def opening():
    img = plate()
    text_center(img, P["data"], SERIF_IT, 118, 190)
    text_center(img, P["titulo"], SCRIPT, 200, 400)
    names = P.get("nomes") or []
    y = 640
    if len(names) <= 1:
        if names: text_center(img, names[0], SCRIPT, 140, y)
    else:  # vários casais: duas linhas menores, separadas por ponto
        size, y = 75, 632  # duas linhas, um pouco à esquerda para não encostar no buquê da direita
        half = (len(names) + 1) // 2
        for line in (names[:half], names[half:]):
            text_center(img, "   ·   ".join(line), SCRIPT, size, y, x=850); y += 88
    text_center(img, P["igreja"], SERIF, 54, 880)
    text_center(img, P["cidade"], SERIF, 54, 945)
    img.convert("RGB").save(OUT / "abertura.png")

def credits():
    img = plate()
    blocks = P["creditos"]  # lista de [titulo, subtitulo]
    heights = [70 + 52 * len(sub.split("\n")) + 60 for _, sub in blocks]
    y = (H - sum(heights)) / 2 + 20
    for (title, sub), h in zip(blocks, heights):
        text_center(img, title, SERIF, 52, y)
        yy = y + 66
        for line in sub.split("\n"):
            text_center(img, line, SERIF, 38, yy); yy += 46
        y += h
    img.convert("RGB").save(OUT / "creditos.png")

def multiply_logo(img, path, width, pos):
    """Logo com fundo branco (ou transparente) sobre a placa clara: mistura por multiplicação."""
    logo = Image.open(path).convert("RGBA")
    logo = logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)
    base = Image.new("RGBA", logo.size, (255, 255, 255, 255)); base.alpha_composite(logo)
    region = img.crop((pos[0], pos[1], pos[0] + logo.width, pos[1] + logo.height)).convert("RGB")
    from PIL import ImageChops
    mixed = ImageChops.multiply(region, base.convert("RGB"))
    img.paste(mixed.convert("RGBA"), pos)

def closing():
    img = plate()
    multiply_logo(img, P["logo_paroquia"], 760, (880, 40))
    multiply_logo(img, P["logo_pascom"], 600, (440, 420))
    img.convert("RGB").save(OUT / "encerramento.png")

opening(); credits(); closing()
print("ok:", OUT)
