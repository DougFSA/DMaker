# Origem do código em `openvoice/`

Trecho de inferência do conversor de timbre do **OpenVoice V2** (MyShell.ai), licença **MIT** (arquivo
`LICENSE` ao lado), repositório https://github.com/myshell-ai/OpenVoice no commit
`74a1d147b17a8c3092dd5430504bd83ef6c7eb23`.

Por que o código está aqui e não o pacote: o `setup.py` do OpenVoice fixa `numpy==1.22.0`, `librosa==0.9.1`,
`gradio==3.48.0`, `faster-whisper==0.9.0` e outras versões que quebram o que o DMaker já usa (omnivoice,
demucs, kokoro-onnx, faster-whisper atual). O conversor em si só precisa de PyTorch.

O que foi copiado (arquivos `commons.py`, `attentions.py`, `modules.py`, `transforms.py`, `models.py`):
igual ao original, só com os imports trocados de `from openvoice import x` para `from . import x`.
`mel_processing.py` mantém apenas `spectrogram_torch` (sem a dependência do librosa).

O que não foi copiado: a síntese de texto (BaseSpeakerTTS, `text/`), a extração de embedding por
segmentos com Whisper (`se_extractor.py`) e a marca d'água `wavmark`.

Pesos: `myshell-ai/OpenVoiceV2` no Hugging Face, `converter/checkpoint.pth` e `converter/config.json`
(licença MIT), baixados para `cache/models/openvoice` com versão e SHA-256 fixados em
`dmaker/voice/openvoice_converter.py`.
