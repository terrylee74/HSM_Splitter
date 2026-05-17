import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import re
import threading

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

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

class ExcelDataEditor(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._highlight_job = None
        self.count_var = tk.StringVar()
        self._build_ui()

    def _build_ui(self):
        # 전체를 좌우로 분할 (왼쪽: 규칙 설정, 오른쪽: 데이터 입출력)
        main_paned = ttk.PanedWindow(self, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=10, pady=10)

        # ─── 왼쪽: 룰(Rule) 설정 영역 ───
        rule_frame = ttk.Frame(main_paned)
        main_paned.add(rule_frame, weight=1)

        # 1. 다중행 삭제 블록
        delete_frame = ttk.LabelFrame(rule_frame, text="1. 다중행 삭제 (동일 구조 일괄 삭제)")
        delete_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(delete_frame, text="삭제할 텍스트 블록 (있는 그대로 붙여넣기):").pack(anchor="w", padx=5, pady=2)
        self.text_delete = tk.Text(delete_frame, height=6, width=40)
        self.text_delete.pack(fill="x", padx=5, pady=5)

        # 2. 타이틀 다중 치환 블록
        title_frame = ttk.LabelFrame(rule_frame, text="2. 타이틀 추출 및 다중 치환")
        title_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        search_frame = ttk.Frame(title_frame)
        search_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(search_frame, text="타이틀 공통 단어:").pack(side="left")
        self.entry_title_keyword = ttk.Entry(search_frame, width=15)
        self.entry_title_keyword.pack(side="left", padx=5)
        ttk.Button(search_frame, text="타이틀 추출", command=self.extract_titles).pack(side="left")

        self.lbl_title_count = ttk.Label(title_frame, text="추출된 원본: 0 개  |  바꿀 타이틀: 0 개", foreground="blue")
        self.lbl_title_count.pack(anchor="w", padx=5, pady=2)

        title_paned = ttk.PanedWindow(title_frame, orient="horizontal")
        title_paned.pack(fill="both", expand=True, padx=5, pady=5)

        orig_title_frame = ttk.Frame(title_paned)
        title_paned.add(orig_title_frame, weight=1)
        ttk.Label(orig_title_frame, text="원본 타이틀 (자동추출)").pack(anchor="w")
        self.text_orig_titles = tk.Text(orig_title_frame, height=10, width=20, wrap="none", bg="#f0f0f0")
        self.text_orig_titles.pack(fill="both", expand=True)

        new_title_frame = ttk.Frame(title_paned)
        title_paned.add(new_title_frame, weight=1)
        ttk.Label(new_title_frame, text="새 타이틀 (여기에 붙여넣기)").pack(anchor="w")
        self.text_new_titles = tk.Text(new_title_frame, height=10, width=20, wrap="none")
        self.text_new_titles.pack(fill="both", expand=True)
        self.text_new_titles.bind("<KeyRelease>", self.update_counts)

        # 3. 엑셀 행 병합 옵션
        merge_frame = ttk.LabelFrame(rule_frame, text="3. 구조 병합 옵션")
        merge_frame.pack(fill="x", pady=(0, 10))
        self.var_merge = tk.BooleanVar(value=True)
        ttk.Checkbutton(merge_frame, text="1열 구조일 때 이전 행 2열로 병합 (타이틀은 예외처리)", variable=self.var_merge).pack(anchor="w", padx=5, pady=10)

        # 4. 데이터 재배치 및 자동 넘버링 옵션
        reformat_frame = ttk.LabelFrame(rule_frame, text="4. 데이터 재배치 및 자동 넘버링")
        reformat_frame.pack(fill="x", pady=(0, 10))
        self.var_reformat = tk.BooleanVar(value=True)
        ttk.Checkbutton(reformat_frame, text="타이틀 아래 헤더 삽입 및 열 이동 (번호 부여)", variable=self.var_reformat).pack(anchor="w", padx=5, pady=10)

        # 5. 특수 단어 보호 옵션
        escape_frame = ttk.LabelFrame(rule_frame, text="5. 특수 단어(true/false) 보호")
        escape_frame.pack(fill="x", pady=(0, 10))
        self.var_escape_bool = tk.BooleanVar(value=True)
        ttk.Checkbutton(escape_frame, text='엑셀 수식(="false") 적용 (클래스카드 업로드용)', variable=self.var_escape_bool).pack(anchor="w", padx=5, pady=10)

        # ─── 오른쪽: 원본 데이터 및 결과 영역 ───
        data_frame = ttk.Frame(main_paned)
        main_paned.add(data_frame, weight=2)

        btn_frame = ttk.Frame(data_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="엑셀 파일 열기", command=self.open_excel_file).pack(side="left", padx=(0, 5))
        ttk.Button(btn_frame, text="▶ 전체 프로세스 실행", command=self.apply_process).pack(side="left")
        ttk.Button(btn_frame, text="결과 복사", command=self.copy_result).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="결과 저장(.txt)", command=self.save_result).pack(side="left")
        ttk.Button(btn_frame, text="전체 초기화", command=self.clear_all).pack(side="left", padx=5)

        data_paned = ttk.PanedWindow(data_frame, orient="vertical")
        data_paned.pack(fill="both", expand=True)

        input_frame = ttk.LabelFrame(data_paned, text="원본 데이터 (엑셀에서 복사하여 붙여넣기)")
        data_paned.add(input_frame, weight=1)
        
        self.text_input = tk.Text(input_frame, wrap="none")
        in_scroll_y = ttk.Scrollbar(input_frame, orient="vertical", command=self.text_input.yview)
        in_scroll_x = ttk.Scrollbar(input_frame, orient="horizontal", command=self.text_input.xview)
        in_scroll_x.pack(side="bottom", fill="x")
        in_scroll_y.pack(side="right", fill="y")
        self.text_input.pack(side="left", fill="both", expand=True)
        self.text_input.configure(yscrollcommand=in_scroll_y.set, xscrollcommand=in_scroll_x.set)

        # 하이라이트 태그 설정 (삭제=빨간색, 타이틀=녹색)
        self.text_input.tag_config("delete", background="#ffcccc", foreground="#cc0000")
        self.text_input.tag_config("title", background="#ccffcc", foreground="#006600")
        
        self.text_input.bind("<KeyRelease>", self.schedule_highlight)
        self.text_input.bind("<<Paste>>", self.schedule_highlight)
        self.text_delete.bind("<KeyRelease>", self.schedule_highlight)
        self.text_delete.bind("<<Paste>>", self.schedule_highlight)

        output_frame = ttk.LabelFrame(data_paned, text="결과 데이터")
        data_paned.add(output_frame, weight=1)

        self.text_output = tk.Text(output_frame, wrap="none")
        out_scroll_y = ttk.Scrollbar(output_frame, orient="vertical", command=self.text_output.yview)
        out_scroll_x = ttk.Scrollbar(output_frame, orient="horizontal", command=self.text_output.xview)
        out_scroll_x.pack(side="bottom", fill="x")
        out_scroll_y.pack(side="right", fill="y")
        self.text_output.pack(side="left", fill="both", expand=True)
        self.text_output.configure(yscrollcommand=out_scroll_y.set, xscrollcommand=out_scroll_x.set)

    def _highlight_pattern(self, pattern, tag, regexp=False):
        if not pattern:
            return
        
        start_idx = "1.0"
        while True:
            pos = self.text_input.search(pattern, start_idx, stopindex="end", count=self.count_var, regexp=regexp)
            if not pos:
                break
            
            match_len = self.count_var.get()
            if not match_len or int(match_len) == 0:
                start_idx = f"{pos}+1c"
                continue
                
            end_pos = f"{pos}+{match_len}c"
            self.text_input.tag_add(tag, pos, end_pos)
            start_idx = end_pos

    def schedule_highlight(self, event=None):
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        # 300ms 동안 추가 입력이 없으면 하이라이트 업데이트 (디바운싱)
        self._highlight_job = self.after(300, self.update_highlights)

    def update_highlights(self):
        self.text_input.tag_remove("delete", "1.0", "end")
        self.text_input.tag_remove("title", "1.0", "end")
        
        # 1. PAGE 패턴 강조 (정규식 검색)
        self._highlight_pattern(r"PAGE[ \t]*[0-9]+/[0-9]+", "delete", regexp=True)
        
        # 2. 다중행 삭제 블록 강조
        delete_block = self.text_delete.get("1.0", "end-1c").strip()
        if delete_block:
            self._highlight_pattern(delete_block, "delete", regexp=False)
            
        # 3. 추출된 타이틀 강조
        orig_titles = self.text_orig_titles.get("1.0", "end-1c").strip().split('\n')
        for t in orig_titles:
            t = t.strip()
            if t:
                self._highlight_pattern(t, "title", regexp=False)

    def normalize_text(self, text):
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def update_counts(self, event=None):
        orig_text = self.text_orig_titles.get("1.0", "end-1c").strip()
        new_text = self.text_new_titles.get("1.0", "end-1c").strip()
        
        orig_count = len(orig_text.split('\n')) if orig_text else 0
        new_count = len(new_text.split('\n')) if new_text else 0
        
        color = "blue" if orig_count == new_count else "red"
        self.lbl_title_count.config(text=f"추출된 원본: {orig_count} 개  |  바꿀 타이틀: {new_count} 개", foreground=color)

    def extract_titles(self):
        keyword = self.entry_title_keyword.get().strip()
        if not keyword:
            messagebox.showwarning("경고", "추출할 타이틀 공통 단어를 입력하세요.")
            return
        
        raw_data = self.normalize_text(self.text_input.get("1.0", "end-1c"))
        titles = []
        for line in raw_data.split('\n'):
            if keyword in line:
                # 타이틀이 들어있는 라인에서 첫 번째 열을 타이틀로 인식
                title = line.split('\t')[0] 
                titles.append(title)
                
        self.text_orig_titles.configure(state="normal")
        self.text_orig_titles.delete("1.0", "end")
        self.text_orig_titles.insert("1.0", "\n".join(titles))
        self.update_counts()
        self.update_highlights()
        messagebox.showinfo("완료", f"{len(titles)}개의 타이틀을 찾았습니다.")

    def apply_process(self):
        raw_data = self.normalize_text(self.text_input.get("1.0", "end-1c"))
        
        if not raw_data.strip():
            messagebox.showwarning("경고", "원본 데이터를 먼저 입력해주세요.")
            return

        # --- 1단계: 다중행 삭제 ---
        delete_block = self.normalize_text(self.text_delete.get("1.0", "end-1c").strip())
        if delete_block:
            # 앞뒤 줄바꿈을 포함하여 깔끔하게 삭제
            raw_data = raw_data.replace(delete_block + "\n", "")
            raw_data = raw_data.replace(delete_block, "")

        # --- 1.5단계: 'PAGE 숫자/숫자' 패턴 자동 삭제 ---
        raw_data = re.sub(r"(?m)^PAGE[ \t]*\d+/\d+[ \t]*\n?", "", raw_data)

        # --- 2단계: 타이틀 치환 및 이중 대괄호[[]] 감싸기 ---
        orig_titles = self.normalize_text(self.text_orig_titles.get("1.0", "end-1c")).strip().split('\n')
        new_titles = self.normalize_text(self.text_new_titles.get("1.0", "end-1c")).strip().split('\n')
        
        current_titles = []
        title_map = {}
        if orig_titles != [''] and new_titles != ['']:
            if len(orig_titles) != len(new_titles):
                if not messagebox.askyesno("경고", f"원본 타이틀({len(orig_titles)}개)과 새 타이틀({len(new_titles)}개)의 개수가 다릅니다.\n그래도 진행하시겠습니까?"):
                    return
            
            for old_t, new_t in zip(orig_titles, new_titles):
                if old_t and new_t:
                    clean_t = new_t.strip()
                    # 이미 [[ ]] 로 감싸져 있다면 중복 감싸기 방지
                    if clean_t.startswith('[[') and clean_t.endswith(']]'):
                        wrapped_t = clean_t
                    else:
                        wrapped_t = f"[[{clean_t}]]"
                    title_map[old_t] = wrapped_t
                    current_titles.append(wrapped_t)
        else:
            if orig_titles != ['']:
                for old_t in orig_titles:
                    if old_t:
                        clean_t = old_t.strip()
                        if clean_t.startswith('[[') and clean_t.endswith(']]'):
                            wrapped_t = clean_t
                        else:
                            wrapped_t = f"[[{clean_t}]]"
                        title_map[old_t] = wrapped_t
                        current_titles.append(wrapped_t)

        # 타이틀 치환 적용 (긴 문자열부터 치환하여 부분 문자열 겹침으로 인한 괄호 중첩 오류 방지)
        sorted_olds = sorted(title_map.keys(), key=len, reverse=True)
        replaced_lines = []
        for line in raw_data.split('\n'):
            for old_t in sorted_olds:
                if old_t in line:
                    line = line.replace(old_t, title_map[old_t], 1)
                    break  # 한 줄에 한 번 치환하면 다음 줄로 넘어감
            replaced_lines.append(line)
        raw_data = "\n".join(replaced_lines)

        # --- 3단계: 단일 열 병합 ---
        lines = raw_data.split('\n')
        processed_lines = []
        
        for line in lines:
            if not line.strip():
                continue
            
            cols = line.split('\t')
            
            # 타이틀인지 확인
            is_title = any(t in line for t in current_titles if t)
            
            # 옵션이 켜져 있고 타이틀이 아니며 1열 구조일 때만 병합
            if self.var_merge.get() and (len(cols) == 1 or (len(cols) >= 2 and not cols[1].strip())) and not is_title:
                single_data = cols[0].strip()
                
                if processed_lines and len(processed_lines[-1]) >= 2:
                    prev_c2 = processed_lines[-1][1]
                    
                    # 리스트 형태로 뜻풀이 누적 보관
                    if isinstance(prev_c2, list):
                        prev_c2.append(single_data)
                    else:
                        # 기존 찌꺼기 따옴표 제거 (혹시 있다면)
                        if isinstance(prev_c2, str) and prev_c2.startswith('"') and prev_c2.endswith('"'):
                            prev_c2 = prev_c2[1:-1]
                        if single_data.startswith('"') and single_data.endswith('"'):
                            single_data = single_data[1:-1]
                            
                        processed_lines[-1][1] = [prev_c2.strip(), single_data.strip()]
                else:
                    processed_lines.append(cols)
            else:
                processed_lines.append(cols)

        # --- 4단계: 컬럼 재배치 및 넘버링 ---
        def format_cell(data):
            if isinstance(data, list):
                # Excel 수식(CHAR 10)을 적용하여 Windows 클립보드의 \r 간섭을 원천 차단
                escaped = ['"' + str(x).replace('"', '""') + '"' for x in data]
                return "=" + " & CHAR(10) & ".join(escaped)
            else:
                s = str(data).strip()
                if s.startswith('"') and s.endswith('"'):
                    s = s[1:-1]
                return s.strip()

        if self.var_reformat.get():
            restructured_lines = []
            counter = 1
            
            for cols in processed_lines:
                # 타이틀 확인을 위한 임시 텍스트 변환
                plain_cols = [(" ".join(c) if isinstance(c, list) else str(c)) for c in cols]
                line_str = "\t".join(plain_cols)
                
                is_title = any(t in line_str for t in current_titles if t)
                        
                if is_title:
                    restructured_lines.append(line_str)
                    # 타이틀 바로 아래에 헤더 삽입
                    restructured_lines.append("번호\t단어\t뜻\t예문(해석)")
                    counter = 1  # 번호 초기화
                else:
                    word = format_cell(cols[0]) if len(cols) > 0 else ""
                    meaning = format_cell(cols[1]) if len(cols) > 1 else ""
                    # 번호(1열), 단어(2열), 뜻(3열), 빈열(4열, 탭으로 끝남)
                    restructured_lines.append(f"{counter}\t{word}\t{meaning}\t")
                    counter += 1
                    
            final_data = "\n".join(restructured_lines)
        else:
            final_lines = []
            for cols in processed_lines:
                formatted_cols = [format_cell(c) for c in cols]
                final_lines.append("\t".join(formatted_cols))
            final_data = "\n".join(final_lines)

        # --- 5단계: Excel Boolean(true/false) 자동 변환 방지 ---
        # 엑셀에서 true/false를 논리값으로 자동 변환하지 못하도록 엑셀 수식(="false") 형태로 텍스트 인식시킵니다.
        if self.var_escape_bool.get():
            final_data = re.sub(r"(^|\t)(true|false)(?=\t|$)", lambda m: f'{m.group(1)}="{m.group(2).lower()}"', final_data, flags=re.IGNORECASE | re.MULTILINE)

        # --- 결과 출력 ---
        self.text_output.delete("1.0", "end")
        self.text_output.insert("1.0", final_data)
        messagebox.showinfo("성공", "프로세스가 완료되었습니다.")

    def copy_result(self):
        result_data = self.text_output.get("1.0", "end-1c")
        if not result_data.strip():
            messagebox.showwarning("경고", "복사할 결과 데이터가 없습니다.")
            return
            
        self.clipboard_clear()
        self.clipboard_append(result_data)
        messagebox.showinfo("성공", "결과 데이터가 클립보드에 복사되었습니다.")

    def save_result(self):
        result_data = self.text_output.get("1.0", "end-1c")
        if not result_data.strip():
            messagebox.showwarning("경고", "저장할 결과 데이터가 없습니다.")
            return
            
        file_path = filedialog.asksaveasfilename(
            title="결과 저장",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("TSV Files", "*.tsv"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(result_data)
                messagebox.showinfo("성공", f"결과가 성공적으로 저장되었습니다:\n{file_path}")
            except Exception as e:
                messagebox.showerror("오류", f"파일 저장 중 오류가 발생했습니다:\n{e}")

    def clear_all(self):
        self.text_delete.delete("1.0", "end")
        self.entry_title_keyword.delete(0, 'end')
        self.text_orig_titles.delete("1.0", "end")
        self.text_new_titles.delete("1.0", "end")
        self.text_input.delete("1.0", "end")
        self.text_output.delete("1.0", "end")
        self.update_counts()
        self.update_highlights()

    def open_excel_file(self):
        file_path = filedialog.askopenfilename(
            title="엑셀 파일 선택",
            filetypes=[("Excel Files", "*.xlsx *.xlsm"), ("All Files", "*.*")]
        )
        if not file_path:
            return
            
        if not HAS_OPENPYXL:
            messagebox.showerror(
                "오류", 
                "엑셀 파일을 읽기 위해 'openpyxl' 라이브러리가 필요합니다.\n명령 프롬프트에서 'pip install openpyxl'을 실행해주세요."
            )
            return
            
        # 로딩 창 UI 구성 (메인 창 중앙 배치)
        loading_popup = tk.Toplevel(self)
        loading_popup.title("로딩 중")
        loading_popup.geometry("300x100")
        loading_popup.transient(self.winfo_toplevel())
        loading_popup.grab_set()  # 다른 창 클릭 방지 (모달)
        
        self.update_idletasks()
        x = self.winfo_toplevel().winfo_x() + (self.winfo_toplevel().winfo_width() // 2) - 150
        y = self.winfo_toplevel().winfo_y() + (self.winfo_toplevel().winfo_height() // 2) - 50
        loading_popup.geometry(f"+{x}+{y}")
        
        ttk.Label(loading_popup, text="엑셀 파일을 불러오는 중입니다...\n잠시만 기다려주세요.", justify="center").pack(expand=True)
        self.update_idletasks()

        def worker():
            try:
                # data_only=True: 엑셀 수식 대신 계산된 결과값만 가져옴
                wb = openpyxl.load_workbook(file_path, data_only=True)
                sheet = wb.active
                
                tsv_lines = []
                for row in sheet.iter_rows(values_only=True):
                    row_data = [str(cell) if cell is not None else "" for cell in row]
                    tsv_lines.append("\t".join(row_data))
                    
                result_text = "\n".join(tsv_lines)
                
                def update_ui():
                    self.text_input.delete("1.0", "end")
                    self.text_input.insert("1.0", result_text)
                    self.schedule_highlight()
                    
                self.after(0, update_ui)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("오류", f"엑셀 파일을 읽는 중 오류가 발생했습니다:\n{err}"))
            finally:
                self.after(0, loading_popup.destroy)
                
        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    if HAS_TTKBOOTSTRAP:
        root = tb.Window(themename="litera")
    else:
        root = tk.Tk()
        if HAS_SV_TTK:
            sv_ttk.set_theme("light")

    root.title("Excel TSV Advanced Processor")
    root.geometry("1200x800")
    
    # 기본 폰트 설정 (크기 조절: 10 -> 11 또는 12)
    default_font = ("맑은 고딕", 11)
    root.option_add("*Font", default_font)
    
    # ttk 위젯(ttkbootstrap 포함) 전체에 폰트 강제 적용
    ttk.Style(root).configure('.', font=default_font)
    
    app = ExcelDataEditor(root)
    app.pack(fill="both", expand=True)
    root.mainloop()