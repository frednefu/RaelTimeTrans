from setuptools import setup, find_packages

setup(
    name="RealTimeTrans",
    version="0.1.0",
    description="实时翻译软件，使用Whisper进行语音识别并翻译为多种语言",
    author="RealTimeTrans",
    packages=find_packages(),
    install_requires=[
        "torch>=2.0.1",
        "torchaudio>=2.0.2",
        "openai-whisper>=20231117",
        "python-dotenv>=1.0.0",
        "pydub>=0.25.1",
        "pyaudio>=0.2.13",
        "sounddevice>=0.4.6",
        "PyQt6>=6.5.2",
        "googletrans>=4.0.0-rc1",
    ],
    entry_points={
        'console_scripts': [
            'realtimetrans=main:main',
        ],
    },
    python_requires='>=3.8',
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
    ],
) 