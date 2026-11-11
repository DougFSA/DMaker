"""`python -m dmaker ...`: o ponto de entrada do programa instalado, que não tem o `dmaker.exe` do pip (ele guarda o
caminho absoluto do Python e quebra quando a pasta muda)."""

from .cli import app

if __name__ == "__main__":
    app()
