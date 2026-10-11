a = Analysis(['SpikeAI.py'], pathex=[], binaries=[],
    datas=[('assets/templates/*.png', 'assets/templates'),
           ('assets/templates/presence.npz', 'assets/templates'),
           ('assets/derived/library.json', 'assets/derived'),
           ('assets/voice/*.wav', 'assets/voice'), ('assets/voice/manifest.json', 'assets/voice'),
           ('assets/logo/spike-ai.ico', 'assets/logo'), ('assets/logo/spike-ai-mark.png', 'assets/logo'), ('licenses/*', 'licenses'),
           ('assets/art/*.jpg', 'assets/art'), ('assets/art/provenance.json', 'assets/art'),
           ('ATTRIBUTIONS.md', '.')],
    hiddenimports=['mss.windows', 'winrt.windows.applicationmodel', 'winrt.windows.applicationmodel.activation', 'winrt.windows.foundation', 'winrt.windows.foundation.collections'],
    excludes=['soundcard', 'scipy', 'matplotlib', 'pandas', 'pytest', 'ruff', 'PIL',
              'IPython', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick', 'onnxruntime', 'kokoro_onnx', 'soundfile', 'psutil', 'development'],
    noarchive=False, optimize=1)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], name='Spike AI', debug=False,
          exclude_binaries=True, strip=False, upx=False, console=False, uac_admin=False,
          icon=['assets/logo/spike-ai.ico'], version='version_info.txt',
          manifest='<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                   '<application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
                   '<dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>'
                   '<dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>'
                   '</windowsSettings></application></assembly>')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Spike AI')
