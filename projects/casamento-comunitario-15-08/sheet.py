"""Grade de quadros por intervalo da sessão: linha de cima câmera 1, linha de baixo câmera 2, 1 quadro a cada N s."""
import subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw
V = Path("D:/casamento comunitario 15-08/Videos")
FF = "D:/DMaker/bin/ffmpeg/bin/ffmpeg.exe"
CAM1 = [("c1a", V/"Camera1/20260815_110334.mp4", 0.0, 589.1), ("c1b", V/"Camera1/20260815_111336.mp4", 601.738, 65.25),
        ("c1c", V/"Camera1/20260815_111503.mp4", 688.454, 61.33), ("c1d", V/"Camera1/20260815_111628.mp4", 773.695, 41.56),
        ("c1e", V/"Camera1/20260815_111740.mp4", 846.060, 2806.1), ("c1f", V/"Camera1/20260815_120431.mp4", 3656.239, 1117.06),
        ("c1g", V/"Camera1/20260815_122328.mp4", 4793.599, 541.56)]
CAM2 = [("7830", V/"Camera2/MVI_7830.MP4", 19.526, 405.77), ("7831", V/"Camera2/MVI_7831-003.MP4", 469.720, 1799.06),
        ("7832", V/"Camera2/MVI_7832.MP4", 2303.787, 1155.39), ("7833", V/"Camera2/MVI_7833-002.MP4", 3464.148, 1759.69)]
def file_at(cam, t):
    for name, path, off, dur in cam:
        if off <= t < off + dur: return path, t - off
    return None, None
def grab(path, ft, w):
    out = subprocess.run([FF, "-v", "error", "-ss", f"{ft:.2f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:-1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    import io; return Image.open(io.BytesIO(out)).convert("RGB") if out else None
a, b, step = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
w, h = 240, 135
times = [a + i*step for i in range(int((b-a)/step)+1)]
cols = min(len(times), 8); rows = -(-len(times)//cols)
sheet = Image.new("RGB", (cols*w, rows*(2*h+14)), "black")
d = ImageDraw.Draw(sheet)
for i, t in enumerate(times):
    x = (i % cols)*w; y = (i // cols)*(2*h+14)
    d.text((x+4, y+1), f"{t:.0f}s", fill="yellow")
    for k, cam in enumerate((CAM1, CAM2)):
        path, ft = file_at(cam, t)
        if path:
            im = grab(path, ft, w)
            if im: sheet.paste(im, (x, y+14+k*h))
out = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(__file__).parent / f"sheet_{int(a)}_{int(b)}.png"
sheet.save(out); print(out)
