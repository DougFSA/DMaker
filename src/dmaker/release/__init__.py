"""Release do DMaker: monta o pacote instalável (Python portátil, binários, modelos) e o instalador de cada sistema.

O que decide (manifesto, nomes, marcador, lançadores, licenças, notas) são funções puras; o que executa (pip, npm,
ISCC, tar) entra por `CommandRunner`, como o ffmpeg entra por `FFmpegRunner`, para o teste usar o falso.
"""
