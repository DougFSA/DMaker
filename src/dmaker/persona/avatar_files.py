"""De onde vem o personagem 3D pronto: o arquivo, o commit do repositório que o guarda e o hash esperado.

O TalkingHead (MIT) é vendorizado em `assets/html/persona/3d/vendor/talkinghead` a partir do mesmo commit. O avatar
`mpfb.glb` (feito com Blender e MPFB, CC0) é grande demais para o git e baixa para `cache/models`. Os outros
avatares do repositório são de uso não comercial e as animações Mixamo não podem ser redistribuídas: não entram.
"""

from __future__ import annotations

from ..media.downloads import RemoteFile

TALKINGHEAD_COMMIT = "1563de184c19b310de4b636664d5835e2c74dbba"
MPFB_AVATAR = RemoteFile(
    name="mpfb.glb",
    url=f"https://raw.githubusercontent.com/met4citizen/TalkingHead/{TALKINGHEAD_COMMIT}/avatars/mpfb.glb",
    size=36_815_920,
    sha256="63c645a2a863b9972e9a9c2ed576a1de4c390b8475508e1473e69c87a3ee299c",
)
