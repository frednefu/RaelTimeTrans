# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 获取Python库路径
PYTHON_LIB_PATH = os.path.dirname(sys.executable)

# 收集whisper模块的所有依赖
whisper_datas, whisper_binaries, whisper_hiddenimports = collect_all('whisper')
pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all('PySide6')
trans_datas, trans_binaries, trans_hiddenimports = collect_all('googletrans')

# 合并所有依赖
datas = whisper_datas + pyside_datas + trans_datas
binaries = whisper_binaries + pyside_binaries + trans_binaries
hiddenimports = whisper_hiddenimports + pyside_hiddenimports + trans_hiddenimports + ['torch', 'numpy']

# 添加项目自身的数据文件
datas.append(('LICENSE', '.'))
datas.append(('README.md', '.'))
datas.append(('Subtitles', 'Subtitles'))

# 确保Python DLL包含在内
binaries.append((os.path.join(PYTHON_LIB_PATH, 'python38.dll'), '.'))

a = Analysis(['main.py'],
             pathex=['.', PYTHON_LIB_PATH],
             binaries=binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='RealTimeTranslation',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None,
          icon='icon.ico' if os.path.exists('icon.ico') else None)

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='RealTimeTranslation')
