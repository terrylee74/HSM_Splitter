import os
import sys
import json
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog

try:
    import ttkbootstrap as tb
    HAS_TTKBOOTSTRAP = True
except ImportError:
    HAS_TTKBOOTSTRAP = False

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

TRACK_RE = re.compile(r"TRACK\s+(\d{2})\s+AUDIO", re.IGNORECASE)
TITLE_RE = re.compile(r'TITLE\s+"(.*)"', re.IGNORECASE)
INDEX_RE = re.compile(r"INDEX\s+01\s+(\d{2}):(\d{2}):(\d{2})", re.IGNORECASE)
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ───────────────────────── 설정 저장/불러오기 ─────────────────────────

SETTINGS_FILE = Path(__file__).resolve().parent / "hsm_splitter_settings.json"

def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_settings(data: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

CUE_ENCODINGS = [
    ("utf-8-sig", "UTF-8 BOM"),
    ("cp949",     "CP949 (한국어 Windows)"),
    ("euc-kr",    "EUC-KR"),
    ("latin-1",   "Latin-1"),
]


def sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name)
    return name[:180] if name else 'track'


def cue_time_to_seconds(mm: str, ss: str, ff: str) -> float:
    return int(mm) * 60 + int(ss) + int(ff) / 75.0


def ffmpeg_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def run_hidden(cmd: List[str], stop_event: threading.Event) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    while proc.poll() is None:
        if stop_event.is_set():
            proc.terminate()
            proc.wait()
            raise InterruptedError("사용자가 처리를 중단했습니다.")
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def get_ffmpeg_tool(name: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent
    local = base_path / f"{name}.exe"
    if local.exists():
        return str(local)
    return f"{name}.exe" if os.name == "nt" else name


def probe_duration(audio_path: Path, stop_event: threading.Event) -> float:
    ffprobe = get_ffmpeg_tool("ffprobe")
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = run_hidden(cmd, stop_event)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe 실행 실패: {audio_path.name}")
    return float(result.stdout.strip())


@dataclass
class Track:
    number: int
    title: str = ""
    start: float = 0.0
    end: Optional[float] = None


@dataclass
class CueData:
    cue_path: Path
    tracks: List[Track] = field(default_factory=list)


def parse_cue(cue_path: Path) -> CueData:
    text = None
    tried = []
    for enc, enc_label in CUE_ENCODINGS:
        try:
            text = cue_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            tried.append(enc_label)
        except Exception as e:
            tried.append(f"{enc_label} ({e})")

    if text is None:
        tried_str = ", ".join(tried)
        raise RuntimeError(
            f"CUE 파일을 읽을 수 없습니다: {cue_path.name}\n"
            f"시도한 인코딩: {tried_str}\n"
            f"파일이 손상되었거나 지원하지 않는 인코딩일 수 있습니다."
        )

    data = CueData(cue_path=cue_path)
    current: Optional[Track] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = TRACK_RE.match(line)
        if m:
            current = Track(number=int(m.group(1)))
            data.tracks.append(current)
            continue

        m = TITLE_RE.match(line)
        if m and current is not None:
            current.title = m.group(1).strip()
            continue

        m = INDEX_RE.match(line)
        if m and current is not None:
            current.start = cue_time_to_seconds(*m.groups())
            continue

    if not data.tracks:
        raise RuntimeError(
            f"트랙 정보를 찾을 수 없습니다: {cue_path.name}\n"
            f"CUE 파일 형식이 올바른지 확인하세요. (TRACK XX AUDIO 항목 필요)"
        )

    for i in range(len(data.tracks) - 1):
        data.tracks[i].end = data.tracks[i + 1].start
    return data


def resolve_audio_for_cue(cue_path: Path) -> Path:
    """CUE와 같은 이름의 MP3 파일을 찾습니다.
    탐색 순서:
      1. CUE와 같은 폴더
      2. CUE 폴더의 하위 폴더 전체 (재귀)
    """
    target_name = cue_path.stem.lower()
    base_dir = cue_path.parent

    # 1. 같은 폴더
    mp3_same = base_dir / (cue_path.stem + ".mp3")
    if mp3_same.exists():
        return mp3_same

    # 2. 하위 폴더 재귀 탐색
    for mp3_path in base_dir.rglob("*.mp3"):
        if mp3_path.stem.lower() == target_name:
            return mp3_path

    raise FileNotFoundError(
        f"MP3 파일을 찾을 수 없습니다.\n"
        f"찾는 파일명: {cue_path.stem}.mp3\n"
        f"탐색 위치: {base_dir} (하위 폴더 포함)\n"
        f"CUE 파일과 같은 이름의 MP3 파일이 해당 폴더 또는 하위 폴더에 있어야 합니다."
    )


def build_split_command(
    mp3_path: Path, output_path: Path, start: float, end: Optional[float],
    trim_silence: bool = False, silence_db: str = "-50",
    pad_start: float = 0.0, pad_end: float = 0.0
) -> List[str]:
    ffmpeg = get_ffmpeg_tool("ffmpeg")

    # 입력 seek으로 빠르게 근처까지 이동 후
    # atrim 필터로 샘플 단위 정밀 절단 → silenceremove가 이미 잘린 구간 안에서만 동작
    # (-t를 출력 옵션으로 쓰면 silenceremove가 줄인 만큼 다음 트랙 오디오가 딸려 옴)
    PRE_SEEK_BUFFER = 5.0
    pre_seek = max(0.0, start - PRE_SEEK_BUFFER)
    atrim_start = start - pre_seek

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-ss", ffmpeg_time(pre_seek),
        "-i", str(mp3_path),
    ]

    af_filters = []
    if end is not None and end > start:
        af_filters.append(f"atrim=start={atrim_start:.3f}:end={atrim_start + (end - start):.3f}")
    else:
        af_filters.append(f"atrim=start={atrim_start:.3f}")
    af_filters.append("asetpts=PTS-STARTPTS")

    if trim_silence:
        # stop_periods 제거: 트랙 중간 무음 구간에서 오디오가 끊기는 버그 방지
        af_filters.append(f"silenceremove=start_periods=1:start_threshold={silence_db}dB")
    if pad_start > 0:
        delay_ms = int(pad_start * 1000)
        af_filters.append(f"adelay=delays={delay_ms}:all=1")
    if pad_end > 0:
        af_filters.append(f"apad=pad_dur={pad_end}")
        
    if af_filters:
        cmd += ["-af", ", ".join(af_filters)]
        
    cmd += [
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "44100",
        "-ac", "1",
        "-b:a", "64k",
        str(output_path),
    ]
    return cmd


class HSMSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HSM Splitter")
        self.root.geometry("980x950")
        self.root.resizable(True, True)

        self.selected_cues: List[Path] = []
        self.output_root: Optional[Path] = None
        self.is_running = False
        self._stop_event = threading.Event()

        self.cue_count_var = tk.StringVar(value="선택된 CUE: 0")
        self.output_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="준비됨")

        settings = load_settings()
        saved_mode = settings.get("naming_mode", "mode2")
        self.naming_mode = tk.StringVar(value=saved_mode)
        
        self.trim_silence_var = tk.BooleanVar(value=settings.get("trim_silence", True))
        self.silence_db_var = tk.StringVar(value=settings.get("silence_db", "-50"))
        self.pad_start_var = tk.StringVar(value=str(settings.get("pad_start", "0.5")))
        self.pad_end_var = tk.StringVar(value=str(settings.get("pad_end", "0.5")))

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ───────────────────────── UI 구성 ─────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=12)

        # 입력
        row1 = ttk.LabelFrame(top, text="입력")
        row1.pack(fill="x", pady=(0, 8))
        ttk.Button(row1, text="CUE 파일 추가", command=self.choose_cues).pack(side="left", padx=8, pady=8)
        ttk.Label(row1, textvariable=self.cue_count_var).pack(side="left", padx=8)

        # 출력
        row2 = ttk.LabelFrame(top, text="출력")
        row2.pack(fill="x", pady=(0, 8))
        ttk.Entry(row2, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(row2, text="출력 폴더 선택", command=self.choose_output).pack(side="left", padx=8, pady=8)

        # 파일명 옵션
        row3 = ttk.LabelFrame(top, text="파일명 옵션")
        row3.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(
            row3,
            text="옵션 1: 첫 음원명 폴더 하나 / 모든 트랙을 한 폴더에 연속 번호 저장",
            variable=self.naming_mode,
            value="mode2",
        ).pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Radiobutton(
            row3,
            text="옵션 2: 각 음원별 폴더 / track 001부터 다시 시작",
            variable=self.naming_mode,
            value="mode1",
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # 오디오 처리 옵션
        row3_5 = ttk.LabelFrame(top, text="오디오 후처리 (무음 정리 및 삽입)")
        row3_5.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(row3_5, text="원음 앞뒤 무음 제거 (기준: ", variable=self.trim_silence_var).pack(side="left", padx=(8, 0), pady=8)
        ttk.Entry(row3_5, textvariable=self.silence_db_var, width=4).pack(side="left")
        ttk.Label(row3_5, text="dB)  |  시작 무음 추가: ").pack(side="left")
        ttk.Entry(row3_5, textvariable=self.pad_start_var, width=4).pack(side="left")
        ttk.Label(row3_5, text="초  |  끝 무음 추가: ").pack(side="left")
        ttk.Entry(row3_5, textvariable=self.pad_end_var, width=4).pack(side="left")
        ttk.Label(row3_5, text="초").pack(side="left", padx=(0, 8))

        # 버튼 영역
        row4 = ttk.Frame(top)
        row4.pack(fill="x", pady=(0, 4))
        self.btn_start = ttk.Button(row4, text="처리 시작", command=self.start_processing)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row4, text="처리 중단", command=self.stop_processing, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(row4, text="로그 지우기", command=self.clear_log).pack(side="left")
        ttk.Label(row4, textvariable=self.status_var).pack(side="right")

        # 진행률 바
        prog_frame = ttk.Frame(top)
        prog_frame.pack(fill="x", pady=(4, 0))
        ttk.Label(prog_frame, text="전체 진행:").pack(side="left")
        self.progress_total = ttk.Progressbar(prog_frame, mode="determinate", length=400)
        self.progress_total.pack(side="left", padx=8, fill="x", expand=True)
        self.progress_total_label = tk.StringVar(value="0 / 0")
        ttk.Label(prog_frame, textvariable=self.progress_total_label).pack(side="left")

        prog_frame2 = ttk.Frame(top)
        prog_frame2.pack(fill="x", pady=(2, 0))
        ttk.Label(prog_frame2, text="현재 트랙:").pack(side="left")
        self.progress_track = ttk.Progressbar(prog_frame2, mode="determinate", length=400)
        self.progress_track.pack(side="left", padx=8, fill="x", expand=True)
        self.progress_track_label = tk.StringVar(value="0 / 0")
        ttk.Label(prog_frame2, textvariable=self.progress_track_label).pack(side="left")

        # CUE 목록
        middle = ttk.LabelFrame(self.root, text="선택된 CUE 목록")
        middle.pack(fill="both", expand=False, padx=12, pady=(8, 4))

        list_frame = ttk.Frame(middle)
        list_frame.pack(fill="both", expand=True, padx=8, pady=4)

        self.listbox = tk.Listbox(list_frame, height=8, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)

        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        list_scroll.pack(side="left", fill="y")
        self.listbox.configure(yscrollcommand=list_scroll.set)

        btn_list = ttk.Frame(middle)
        btn_list.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_list, text="▲ 위로", command=self.move_up).pack(side="left", padx=2)
        ttk.Button(btn_list, text="▼ 아래로", command=self.move_down).pack(side="left", padx=2)
        ttk.Button(btn_list, text="이름 정렬", command=self.sort_by_name).pack(side="left", padx=2)
        ttk.Button(btn_list, text="시간 정렬", command=self.sort_by_time).pack(side="left", padx=2)
        ttk.Button(btn_list, text="선택 삭제", command=self.delete_selected).pack(side="left", padx=2)
        ttk.Button(btn_list, text="전체 삭제", command=self.delete_all).pack(side="left", padx=2)

        # 로그
        bottom = ttk.LabelFrame(self.root, text="처리 로그")
        bottom.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        log_frame = ttk.Frame(bottom)
        log_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.log = tk.Text(log_frame, wrap="word")
        self.log.pack(side="left", fill="both", expand=True)

        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        log_scroll.pack(side="left", fill="y")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.configure(state="disabled")

    # ───────────────────────── 스레드 안전 로그 ─────────────────────────

    def _safe_after(self, fn, *args):
        """메인 스레드에서 안전하게 UI 업데이트"""
        self.root.after(0, fn, *args)

    def append_log(self, text: str):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self._safe_after(_do)

    def clear_log(self):
        def _do():
            self.log.configure(state=tk.NORMAL)
            self.log.delete("1.0", tk.END)
            self.log.configure(state=tk.DISABLED)
        self._safe_after(_do)
        self._reset_progress()
        self._set_status("준비됨")

    def _set_status(self, text: str):
        self._safe_after(self.status_var.set, text)

    def _set_progress_total(self, value: int, maximum: int):
        def _do():
            self.progress_total["maximum"] = maximum
            self.progress_total["value"] = value
            self.progress_total_label.set(f"{value} / {maximum}")
        self._safe_after(_do)

    def _set_progress_track(self, value: int, maximum: int):
        def _do():
            self.progress_track["maximum"] = maximum
            self.progress_track["value"] = value
            self.progress_track_label.set(f"{value} / {maximum}")
        self._safe_after(_do)

    def _reset_progress(self):
        def _do():
            self.progress_total["value"] = 0
            self.progress_total_label.set("0 / 0")
            self.progress_track["value"] = 0
            self.progress_track_label.set("0 / 0")
        self._safe_after(_do)

    # ───────────────────────── CUE 목록 관리 ─────────────────────────

    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        for p in self.selected_cues:
            self.listbox.insert("end", str(p))
        self.cue_count_var.set(f"선택된 CUE: {len(self.selected_cues)}")

    def _on_close(self):
        save_settings({
            "naming_mode": self.naming_mode.get(),
            "trim_silence": self.trim_silence_var.get(),
            "silence_db": self.silence_db_var.get(),
            "pad_start": self.pad_start_var.get(),
            "pad_end": self.pad_end_var.get()
        })
        self.root.destroy()

    def choose_cues(self):
        paths = filedialog.askopenfilenames(filetypes=[("CUE files", "*.cue")])
        if not paths:
            return
        existing = set(self.selected_cues)
        added = 0
        for p in paths:
            path = Path(p)
            if path not in existing:
                self.selected_cues.append(path)
                existing.add(path)
                added += 1
        self._refresh_listbox()
        if added > 0 and not self.output_var.get().strip():
            default_out = self.selected_cues[0].parent / "split_output"
            self.output_root = default_out
            self.output_var.set(str(default_out))

    def choose_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output_root = Path(path)
            self.output_var.set(path)

    def move_up(self):
        selected = list(self.listbox.curselection())
        if not selected or selected[0] == 0:
            return
        for idx in selected:
            self.selected_cues[idx - 1], self.selected_cues[idx] = (
                self.selected_cues[idx], self.selected_cues[idx - 1],
            )
        self._refresh_listbox()
        for idx in selected:
            self.listbox.selection_set(idx - 1)

    def move_down(self):
        selected = list(self.listbox.curselection())
        if not selected or selected[-1] == len(self.selected_cues) - 1:
            return
        for idx in reversed(selected):
            self.selected_cues[idx + 1], self.selected_cues[idx] = (
                self.selected_cues[idx], self.selected_cues[idx + 1],
            )
        self._refresh_listbox()
        for idx in selected:
            self.listbox.selection_set(idx + 1)

    def delete_selected(self):
        selected = list(self.listbox.curselection())
        if not selected:
            messagebox.showinfo("안내", "삭제할 항목을 먼저 선택하세요.")
            return
        for idx in reversed(selected):
            del self.selected_cues[idx]
        self._refresh_listbox()

    def delete_all(self):
        if not self.selected_cues:
            return
        self.selected_cues.clear()
        self._refresh_listbox()

    def sort_by_name(self):
        if not self.selected_cues:
            return
        # 파일명 기준 오름차순(가나다순) 정렬 (대소문자 무시)
        self.selected_cues.sort(key=lambda p: p.name.lower())
        self._refresh_listbox()

    def sort_by_time(self):
        if not self.selected_cues:
            return
        # 파일 수정 시간 기준 오름차순(오래된 파일 먼저) 정렬
        # (만약 최신 파일이 먼저 오게 하려면 reverse=True 를 추가하시면 됩니다)
        self.selected_cues.sort(key=lambda p: p.stat().st_mtime)
        self._refresh_listbox()

    # ───────────────────────── 처리 시작 / 중단 ─────────────────────────

    def start_processing(self):
        if self.is_running:
            return
        if not self.selected_cues:
            messagebox.showwarning("안내", "CUE 파일을 먼저 선택하세요.")
            return
        out = self.output_var.get().strip()
        if not out:
            messagebox.showwarning("안내", "출력 폴더를 선택하세요.")
            return
        self.output_root = Path(out)
        
        # 스레드 안전성 보장: 메인 스레드에서 UI 변수 및 데이터를 미리 추출
        cues_to_process = list(self.selected_cues)  # 리스트 복사본 생성
        out_root = Path(out)
        mode = self.naming_mode.get()
        trim_silence = self.trim_silence_var.get()
        silence_db = self.silence_db_var.get().strip() or "-50"
        pad_start_str = self.pad_start_var.get().strip()
        pad_end_str = self.pad_end_var.get().strip()
        
        self.is_running = True
        self._stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._reset_progress()
        threading.Thread(
            target=self._worker,
            args=(cues_to_process, out_root, mode, trim_silence, silence_db, pad_start_str, pad_end_str),
            daemon=True
        ).start()

    def stop_processing(self):
        if self.is_running:
            self._stop_event.set()
            self._set_status("중단 요청 중...")
            self.btn_stop.configure(state="disabled")

    def _finish_processing(self):
        self.is_running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    # ───────────────────────── 처리 워커 ─────────────────────────

    def _next_track_name(self, n: int) -> str:
        return f"track {n:03d}.mp3"

    def _get_unique_folder(self, base_folder: Path) -> Path:
        if not base_folder.exists():
            return base_folder

        parent = base_folder.parent
        stem = base_folder.name
        counter = 1
        suggestion = parent / f"{stem}_{counter}"
        while suggestion.exists():
            counter += 1
            suggestion = parent / f"{stem}_{counter}"

        result = [None]
        done_event = threading.Event()

        def _prompt(prompt_text, initial_val):
            res = simpledialog.askstring(
                "폴더명 중복",
                prompt_text,
                initialvalue=initial_val,
                parent=self.root
            )
            result[0] = res
            done_event.set()

        current_prompt = f"'{stem}' 폴더가 이미 존재합니다.\n새로운 폴더명을 입력하세요:"
        current_initial = suggestion.name

        while True:
            done_event.clear()
            self._safe_after(_prompt, current_prompt, current_initial)
            done_event.wait()

            if result[0] is None:
                raise InterruptedError("사용자가 폴더명 입력을 취소하여 처리가 중단되었습니다.")
            
            new_name = sanitize_filename(result[0].strip())
            if not new_name:
                new_name = "output"
            new_folder = parent / new_name

            if not new_folder.exists():
                return new_folder
            
            current_prompt = f"'{new_folder.name}' 폴더도 이미 존재합니다.\n다른 폴더명을 입력하세요:"
            current_initial = new_folder.name + "_1"

    def _prepare_mode2_folder(self, first_cue: Path, out_root: Path) -> Path:
        first_mp3 = first_cue.with_suffix('.mp3')
        base_name = sanitize_filename(first_mp3.stem)
        folder = out_root / base_name
        folder = self._get_unique_folder(folder)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _worker(self, cues: List[Path], out_root: Path, mode: str, trim_silence: bool, silence_db: str, pad_start_str: str, pad_end_str: str):
        errors: List[str] = []
        success_count = 0
        stopped = False
        try:
            out_root.mkdir(parents=True, exist_ok=True)
            total = len(cues)
            self.append_log(f"총 {total}개 CUE 처리 시작")

            mode2_folder = None
            global_counter = 1

            try:
                pad_start = float(pad_start_str or 0.0)
            except ValueError:
                pad_start = 0.0
            try:
                pad_end = float(pad_end_str or 0.0)
            except ValueError:
                pad_end = 0.0

            if mode == 'mode2':
                mode2_folder = self._prepare_mode2_folder(cues[0], out_root)
                self.append_log(f"옵션 2 폴더 생성: {mode2_folder.name}")

            self._set_progress_total(0, total)

            for idx, cue_path in enumerate(cues, start=1):
                if self._stop_event.is_set():
                    stopped = True
                    break

                self._set_status(f"처리 중 {idx}/{total}")
                self.append_log("")
                self.append_log(f"[{idx}/{total}] CUE: {cue_path.name}")

                try:
                    cue_data = parse_cue(cue_path)
                    mp3_path = resolve_audio_for_cue(cue_path)
                    self.append_log(f"MP3 자동 연결: {mp3_path.name}")
                    duration = probe_duration(mp3_path, self._stop_event)
                    cue_data.tracks[-1].end = duration

                    num_tracks = len(cue_data.tracks)
                    self._set_progress_track(0, num_tracks)

                    if mode == 'mode1':
                        album_folder = out_root / sanitize_filename(mp3_path.stem)
                        album_folder = self._get_unique_folder(album_folder)
                        album_folder.mkdir(parents=True, exist_ok=True)
                        self.append_log(f"출력 폴더 생성: {album_folder}")
                        local_counter = 1
                        for track_index, track in enumerate(cue_data.tracks, start=1):
                            if self._stop_event.is_set():
                                raise InterruptedError("사용자가 처리를 중단했습니다.")
                                
                            # 핵심: skip 필터링 추가 (대소문자 무관)
                            if track.title and "skip" in track.title.lower():
                                self.append_log(f"  - [{track_index}/{num_tracks}] 스킵됨: {track.title}")
                                self._set_progress_track(track_index, num_tracks)
                                continue

                            output_path = album_folder / self._next_track_name(local_counter)
                            self.append_log(f"  - [{track_index}/{num_tracks}] {output_path.name}")
                            cmd = build_split_command(
                                mp3_path, output_path, track.start, track.end,
                                trim_silence=trim_silence, silence_db=silence_db,
                                pad_start=pad_start, pad_end=pad_end
                            )
                            result = run_hidden(cmd, self._stop_event)
                            if result.returncode != 0:
                                raise RuntimeError(
                                    f"트랙 분할 실패: {output_path.name}\n원인: {result.stderr.strip()}"
                                )
                            local_counter += 1
                            self._set_progress_track(track_index, num_tracks)
                    else:
                        for track_index, track in enumerate(cue_data.tracks, start=1):
                            if self._stop_event.is_set():
                                raise InterruptedError("사용자가 처리를 중단했습니다.")
                                
                            # 핵심: skip 필터링 추가 (대소문자 무관)
                            if track.title and "skip" in track.title.lower():
                                self.append_log(f"  - [{track_index}/{num_tracks}] 스킵됨: {track.title}")
                                self._set_progress_track(track_index, num_tracks)
                                continue

                            output_path = mode2_folder / self._next_track_name(global_counter)
                            global_counter += 1
                            self.append_log(f"  - [{track_index}/{num_tracks}] {output_path.parent.name} / {output_path.name}")
                            cmd = build_split_command(
                                mp3_path, output_path, track.start, track.end,
                                trim_silence=trim_silence, silence_db=silence_db,
                                pad_start=pad_start, pad_end=pad_end
                            )
                            result = run_hidden(cmd, self._stop_event)
                            if result.returncode != 0:
                                raise RuntimeError(
                                    f"트랙 분할 실패: {output_path.name}\n원인: {result.stderr.strip()}"
                                )
                            self._set_progress_track(track_index, num_tracks)

                    success_count += 1
                    self.append_log(f"완료: {cue_path.name}")

                except InterruptedError as e:
                    stopped = True
                    self.append_log(f"중단됨: {cue_path.name}")
                    break
                except FileNotFoundError as e:
                    msg = str(e)
                    errors.append(f"{cue_path.name}: {msg}")
                    self.append_log(f"오류 (파일 없음): {msg}")
                    continue
                except RuntimeError as e:
                    msg = str(e)
                    errors.append(f"{cue_path.name}: {msg}")
                    self.append_log(f"오류: {msg}")
                    continue
                except Exception as e:
                    msg = str(e)
                    errors.append(f"{cue_path.name}: {msg}")
                    self.append_log(f"오류 (알 수 없음): {msg}")
                    continue

                self._set_progress_total(idx, total)

            # 최종 상태
            if stopped:
                self._set_status("중단됨")
                self.append_log("")
                self.append_log("처리가 중단되었습니다.")
                self.append_log(f"완료: {success_count}개 / 오류: {len(errors)}개")
            else:
                self._set_status("모든 작업 완료")
                self._set_progress_total(total, total)
                self.append_log("")
                self.append_log(f"완료 파일 수: {success_count}")
                self.append_log(f"오류 파일 수: {len(errors)}")
                if errors:
                    self.append_log("오류 목록:")
                    for e in errors:
                        self.append_log(f"  - {e}")

            # 완료음 재생 함수 추가
            def _play_done_sound():
                try:
                    if os.name == 'nt':
                        import winsound
                        # Windows 기본 알림음 비동기 재생
                        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
                    else:
                        self.root.bell()
                except Exception:
                    self.root.bell()
            self._safe_after(_play_done_sound)

        except Exception as e:
            self._set_status("오류 발생")
            self.append_log(f"치명적 오류: {e}")
            self._safe_after(messagebox.showerror, "오류", str(e))
        finally:
            self._safe_after(self._finish_processing)


def main():
    if HAS_TTKBOOTSTRAP:
        root = tb.Window(themename="litera")
    else:
        root = tk.Tk()
        if HAS_SV_TTK:
            sv_ttk.set_theme("light")
        else:
            style = ttk.Style(root)
            if "vista" in style.theme_names():
                style.theme_use("vista")
    
    # 기본 폰트 설정 (크기 조절: 10 -> 11 또는 12)
    default_font = ("맑은 고딕", 11)
    root.option_add("*Font", default_font)
    
    # ttk 위젯(ttkbootstrap 포함) 전체에 폰트 강제 적용
    ttk.Style(root).configure('.', font=default_font)
    
    HSMSplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()