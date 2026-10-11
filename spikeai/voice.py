import ctypes
from ctypes import wintypes
import threading
import wave
from pathlib import Path
import numpy as np
from .clock import NS, now_ns
from .resources import resource_path
from .logsys import log

MARKS = ((0, "spike_planted"), (18, "20_seconds"), (28, "10_seconds"), (33, "5_seconds"))


def read_voice(path):
    with wave.open(str(path), "rb") as wav:
        if (
            wav.getsampwidth() != 2
            or wav.getcomptype() != "NONE"
            or wav.getnchannels() not in (1, 2)
            or not 8000 <= wav.getframerate() <= 96000
            or not 0 < wav.getnframes() / wav.getframerate() <= 12
        ):
            raise ValueError("Use a PCM16 mono/stereo WAV, 8–96 kHz, with a maximum duration of 12 s.")
        return wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels()


class VoicePlan:
    OPENING_LATE_S = 2.5

    def __init__(self, plant_ns, max_late_s=0.75):
        self.plant_ns = plant_ns
        self.max_late_ns = int(max_late_s * NS)
        self.opening_late_ns = int(max(max_late_s, self.OPENING_LATE_S) * NS)
        self.used = set()

    def due(self, t_ns):
        eligible = []
        for offset, name in MARKS:
            due = self.plant_ns + offset * NS
            if name not in self.used and t_ns >= due:
                self.used.add(name)
                limit = self.opening_late_ns if offset == 0 else self.max_late_ns
                if t_ns - due <= limit:
                    eligible.append(name)
        return eligible[-1] if eligible else None


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


class WavePlayer:
    def play(self, sound, cancel):
        if cancel.is_set():
            return
        pcm, sr, channels = sound
        winmm = ctypes.WinDLL("winmm")
        handle = ctypes.c_void_p()
        fmt = WAVEFORMATEX(1, channels, sr, sr * channels * 2, channels * 2, 16, 0)

        def checked(code):
            if code:
                raise OSError(f"waveOut error {code}")

        checked(winmm.waveOutOpen(ctypes.byref(handle), ctypes.c_uint(-1), ctypes.byref(fmt), 0, 0, 0))
        buffer = ctypes.create_string_buffer(pcm)
        header = WAVEHDR(ctypes.cast(buffer, ctypes.c_void_p), len(pcm), 0, 0, 0, 0, None, 0)
        prepared = False
        try:
            checked(winmm.waveOutPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header)))
            prepared = True
            if cancel.is_set():
                return
            checked(winmm.waveOutWrite(handle, ctypes.byref(header), ctypes.sizeof(header)))
            while not header.dwFlags & 1:
                if cancel.wait(0.01):
                    break
        finally:
            winmm.waveOutReset(handle)
            if prepared:
                winmm.waveOutUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            winmm.waveOutClose(handle)


class VoiceEngine:
    def __init__(self, volume=0.65, muted=False, player=None):
        self.player = player or WavePlayer()
        self.bank = {}
        for _, name in MARKS:
            path = Path(resource_path("assets", "voice", name + ".wav"))
            with wave.open(str(path), "rb") as wav:
                if wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
                    raise ValueError(f"Expected PCM16: {path}")
                self.bank[name] = (wav.readframes(wav.getnframes()), wav.getframerate(), wav.getnchannels())
        self.volume, self.muted = float(volume), bool(muted)
        self.originals = self.bank.copy()
        self.enabled = {}
        self.test_name = None
        self.condition = threading.Condition()
        self.token = threading.Event()
        self.plan = None
        self.closed = False
        self.played = []
        self.failures = []
        self.on_playing = None
        self.thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self.thread.start()

    def start(self, plant_ns):
        with self.condition:
            self.token.set()
            self.token = threading.Event()
            self.plan = VoicePlan(plant_ns)
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.token.set()
            self.plan = None
            self.test_name = None
            self.condition.notify_all()

    def customize(self, files, enabled):
        bank = self.originals.copy()
        for name, path in files.items():
            if name in bank and path:
                try:
                    bank[name] = read_voice(path)
                except (OSError, ValueError, wave.Error):
                    log.exception("Custom voice unavailable, using original: %s", name)
        with self.condition:
            self.bank = bank
            self.enabled = dict(enabled)

    def preview(self, name):
        with self.condition:
            if name not in self.bank:
                return
            self.token.set()
            self.token = threading.Event()
            self.test_name = name
            self.condition.notify_all()

    def configure(self, volume, muted):
        with self.condition:
            self.volume = min(1, max(0, float(volume)))
            self.muted = bool(muted)
            if self.muted or self.volume == 0:
                self.token.set()
                self.token = threading.Event()

    def _run(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                testing = self.test_name is not None
                name = self.test_name or (self.plan.due(now_ns()) if self.plan else None)
                self.test_name = None
                if name is None:
                    self.condition.wait(0.01 if self.plan else None)
                    continue
                token, volume, muted = self.token, self.volume, self.muted
                sound = self.bank.get(name)
                enabled = self.enabled.get(name, True)
            if muted or volume <= 0 or token.is_set() or (not testing and not enabled):
                continue
            pcm, sr, channels = sound
            scaled = (np.frombuffer(pcm, "<i2").astype(np.float32) * volume).astype("<i2").tobytes()
            try:
                if not testing and self.on_playing:
                    self.on_playing()
                self.player.play((scaled, sr, channels), token)
                if not token.is_set():
                    self.played.append(name)
                    log.info("Voice completed: %s", name)
            except Exception as error:
                self.failures.append(str(error))
                log.exception("Voice playback failed: %s", name)

    def close(self):
        with self.condition:
            self.closed = True
            self.token.set()
            self.condition.notify_all()
        self.thread.join(timeout=2)
